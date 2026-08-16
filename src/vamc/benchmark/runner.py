"""Verified-only benchmark orchestration inside the Docker sandbox."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import statistics
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from vamc.analysis.inventory import AnalysisError
from vamc.models import (
    BenchmarkEnvironment,
    BenchmarkMeasurement,
    BenchmarkReport,
    BenchmarkSelection,
    BenchmarkStatus,
    BenchmarkSummary,
    CandidateBackend,
)
from vamc.runtime.sandbox import DockerSandbox, SandboxMount
from vamc.verify.io import read_regular_file
from vamc.verify.native import VerificationCase, cases_digest, load_cases
from vamc.verify.static import (
    _load_migration_directory,
    manifest_digest,
    verify_migration_directory,
)

_MAX_EVIDENCE_BYTES = 16 * 1024 * 1024


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise AnalysisError("benchmark evidence may not be a symbolic link")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise AnalysisError("cannot safely open benchmark evidence") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_EVIDENCE_BYTES:
            raise AnalysisError("benchmark evidence is not regular or exceeds its size limit")
        chunks: list[bytes] = []
        remaining = _MAX_EVIDENCE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > _MAX_EVIDENCE_BYTES:
            raise AnalysisError("benchmark evidence exceeds its size limit")
    finally:
        os.close(descriptor)
    try:
        decoded = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise AnalysisError("benchmark evidence is not valid bounded JSON") from error
    if not isinstance(decoded, dict):
        raise AnalysisError("benchmark evidence must be a JSON object")
    return decoded


def _document_digest(document: dict[str, Any]) -> str:
    encoded = json.dumps(document, allow_nan=True, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _write_cases(directory: Path, cases: tuple[VerificationCase, ...]) -> None:
    payload = {
        "cases": [{"arguments": list(case.arguments), "keywords": case.keywords} for case in cases]
    }
    with (directory / "cases.json").open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, allow_nan=True, sort_keys=True)
        stream.write("\n")


def _run(
    sandbox: DockerSandbox,
    *,
    module: str,
    routine: str,
    modern_source: Path,
    case_directory: Path,
    result_directory: Path,
    warmups: int,
    repeats: int,
    iterations: int,
) -> dict[str, Any] | None:
    runner = Path(__file__).parents[1] / "verify"
    result = sandbox.run(
        (
            "python",
            "/runner/benchmark_runner.py",
            "--module-root",
            "/modern/src",
            "--module",
            module,
            "--routine",
            routine,
            "--cases",
            "/case/cases.json",
            "--output",
            "/result/result.json",
            "--warmups",
            str(warmups),
            "--repeats",
            str(repeats),
            "--iterations",
            str(iterations),
        ),
        mounts=(
            SandboxMount(runner, "/runner", True),
            SandboxMount(modern_source, "/modern/src", True),
            SandboxMount(case_directory, "/case", True),
            SandboxMount(result_directory, "/result", False),
        ),
        working_directory="/result",
    )
    if not result.succeeded:
        return None
    data = read_regular_file(result_directory / "result.json", _MAX_EVIDENCE_BYTES)
    if data is None:
        return None
    try:
        decoded = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _environment(result: dict[str, Any]) -> BenchmarkEnvironment | None:
    value = result.get("environment")
    if not isinstance(value, dict) or any(
        not isinstance(value.get(key), str)
        for key in ("python", "platform", "machine", "numpy", "numba")
    ):
        return None
    return BenchmarkEnvironment(
        python=value["python"],
        platform=value["platform"],
        machine=value["machine"],
        numpy=value["numpy"],
        numba=value["numba"],
    )


def _samples(result: dict[str, Any] | None, repeats: int) -> tuple[int, ...] | None:
    if result is None or result.get("status") != "benchmarked":
        return None
    values = result.get("samples_ns")
    if (
        not isinstance(values, list)
        or len(values) != repeats
        or any(type(value) is not int or value < 0 for value in values)
    ):
        return None
    return tuple(values)


def _measurement(
    identifier: str,
    routine: str,
    backend: CandidateBackend,
    samples: tuple[int, ...] | None,
    baseline_median: int | None,
) -> BenchmarkMeasurement:
    if samples is None:
        return BenchmarkMeasurement(
            implementation_id=identifier,
            routine=routine,
            backend=backend,
            status=BenchmarkStatus.UNAVAILABLE,
            samples_ns=(),
            median_ns=None,
            minimum_ns=None,
            maximum_ns=None,
            relative_to_serial=None,
            diagnostics=("sandbox benchmark did not produce valid bounded evidence",),
        )
    median = int(statistics.median(samples))
    relative = baseline_median / median if baseline_median is not None and median > 0 else None
    return BenchmarkMeasurement(
        implementation_id=identifier,
        routine=routine,
        backend=backend,
        status=BenchmarkStatus.BENCHMARKED,
        samples_ns=samples,
        median_ns=median,
        minimum_ns=min(samples),
        maximum_ns=max(samples),
        relative_to_serial=relative,
        diagnostics=(),
    )


def benchmark_migration_directory(
    migration_path: str | Path,
    cases_path: str | Path,
    verification_path: str | Path,
    *,
    image: str,
    warmups: int = 2,
    repeats: int = 7,
    iterations: int = 10,
    sandbox: DockerSandbox | None = None,
) -> BenchmarkReport:
    """Benchmark only candidates verified for the exact migration and case set."""

    if not 0 <= warmups <= 100 or not 1 <= repeats <= 100 or not 1 <= iterations <= 100_000:
        raise ValueError("benchmark warmups, repeats, or iterations are out of bounds")
    modern = Path(migration_path).expanduser().resolve()
    static = verify_migration_directory(modern)
    if static.summary.failed:
        raise AnalysisError("benchmark refused because migration integrity failed")
    manifest, _ = _load_migration_directory(modern)
    migration_sha256 = manifest_digest(manifest)
    verification = _read_json(Path(verification_path).expanduser())
    cases = load_cases(cases_path)
    case_sha256 = cases_digest(cases)
    if verification.get("migration_sha256") != migration_sha256:
        raise AnalysisError("verification evidence does not match this migration")
    if verification.get("cases_sha256") != case_sha256:
        raise AnalysisError("verification evidence does not match this case set")
    if verification.get("sandbox_image") != image:
        raise AnalysisError("benchmark image must match the verification image")

    raw_routines = verification.get("routines")
    raw_candidates = verification.get("candidates")
    if (
        verification.get("schema_version") != "0.2.0"
        or not isinstance(raw_routines, list)
        or not isinstance(raw_candidates, list)
    ):
        raise AnalysisError("verification evidence schema is not supported")
    if any(
        not isinstance(item, dict) or not isinstance(item.get("routine"), str)
        for item in raw_routines
    ) or any(
        not isinstance(item, dict) or not isinstance(item.get("candidate_id"), str)
        for item in raw_candidates
    ):
        raise AnalysisError("verification evidence identities are invalid")
    routine_names = [item["routine"] for item in raw_routines]
    candidate_ids = [item["candidate_id"] for item in raw_candidates]
    if len(routine_names) != len(set(routine_names)) or len(candidate_ids) != len(
        set(candidate_ids)
    ):
        raise AnalysisError("verification evidence contains duplicate identities")

    routine_evidence = {
        item["routine"]: item
        for item in raw_routines
        if isinstance(item, dict) and isinstance(item.get("routine"), str)
    }
    verified_candidates = {
        item["candidate_id"]: item
        for item in raw_candidates
        if isinstance(item, dict)
        and isinstance(item.get("candidate_id"), str)
        and item.get("status") == "VERIFIED_FOR_TEST_DOMAIN"
        and type(item.get("cases")) is int
        and item["cases"] > 0
    }
    candidate_items = [
        item
        for item in manifest.get("candidates", [])
        if isinstance(item, dict)
        and item.get("id") in verified_candidates
        and isinstance(item.get("routine"), str)
        and isinstance(item.get("backend"), str)
        and isinstance(item.get("generated_file"), str)
    ]
    if not candidate_items:
        raise AnalysisError("no candidate is verified for this migration and case set")
    for item in candidate_items:
        routine = item["routine"]
        evidence = routine_evidence.get(routine)
        if (
            not isinstance(evidence, dict)
            or evidence.get("status") != "VERIFIED_FOR_TEST_DOMAIN"
            or type(evidence.get("cases")) is not int
            or evidence["cases"] <= 0
        ):
            raise AnalysisError("candidate routine baseline is not verified for the test domain")
        candidate_evidence = verified_candidates[item["id"]]
        if (
            candidate_evidence.get("routine") != routine
            or candidate_evidence.get("backend") != item["backend"]
        ):
            raise AnalysisError("candidate verification identity does not match the manifest")

    selected_sandbox = sandbox or DockerSandbox(image)
    verification_sha256 = _document_digest(verification)
    measurements: list[BenchmarkMeasurement] = []
    environment: BenchmarkEnvironment | None = None
    by_routine: dict[str, list[dict[str, Any]]] = {}
    for item in candidate_items:
        by_routine.setdefault(item["routine"], []).append(item)
    engine_available = selected_sandbox.probe().succeeded
    for routine, routine_candidates in sorted(by_routine.items()):
        routine_cases = tuple(case for case in cases if case.routine == routine)
        if not routine_cases:
            raise AnalysisError(f"no benchmark case exists for verified routine: {routine}")
        with tempfile.TemporaryDirectory(prefix="vamc-benchmark-") as temporary_name:
            temporary = Path(temporary_name)
            _write_cases(temporary, routine_cases)
            baseline_identifier = f"{routine}.serial-python"
            baseline_result: dict[str, Any] | None = None
            if engine_available:
                result_directory = temporary / "serial-result"
                result_directory.mkdir()
                package_name = manifest.get("package_name")
                if not isinstance(package_name, str) or not package_name.isidentifier():
                    raise AnalysisError("migration package name is invalid")
                baseline_result = _run(
                    selected_sandbox,
                    module=package_name,
                    routine=routine,
                    modern_source=modern / "src",
                    case_directory=temporary,
                    result_directory=result_directory,
                    warmups=warmups,
                    repeats=repeats,
                    iterations=iterations,
                )
            baseline_samples = _samples(baseline_result, repeats)
            baseline = _measurement(
                baseline_identifier,
                routine,
                CandidateBackend.SERIAL_PYTHON,
                baseline_samples,
                None,
            )
            measurements.append(baseline)
            baseline_median = baseline.median_ns
            if baseline_result and environment is None:
                environment = _environment(baseline_result)
            for index, item in enumerate(sorted(routine_candidates, key=lambda value: value["id"])):
                generated = PurePosixPath(item["generated_file"])
                if (
                    len(generated.parts) < 3
                    or generated.parts[0] != "src"
                    or generated.suffix != ".py"
                ):
                    samples = None
                else:
                    module = ".".join((*generated.parts[1:-1], generated.stem))
                    candidate_result = None
                    if engine_available:
                        result_directory = temporary / f"candidate-{index}-result"
                        result_directory.mkdir()
                        candidate_result = _run(
                            selected_sandbox,
                            module=module,
                            routine=routine,
                            modern_source=modern / "src",
                            case_directory=temporary,
                            result_directory=result_directory,
                            warmups=warmups,
                            repeats=repeats,
                            iterations=iterations,
                        )
                    samples = _samples(candidate_result, repeats)
                    if candidate_result and environment is None:
                        environment = _environment(candidate_result)
                measurements.append(
                    _measurement(
                        item["id"],
                        routine,
                        CandidateBackend(item["backend"]),
                        samples,
                        baseline_median,
                    )
                )

    selections: list[BenchmarkSelection] = []
    for routine in sorted(by_routine):
        eligible = [
            item
            for item in measurements
            if item.routine == routine
            and item.status is BenchmarkStatus.BENCHMARKED
            and item.median_ns is not None
        ]
        serial = next(
            (item for item in eligible if item.backend is CandidateBackend.SERIAL_PYTHON),
            None,
        )
        if serial is None:
            continue
        winner = min(eligible, key=lambda item: (item.median_ns or 0, item.implementation_id))
        if serial.median_ns is None or winner.median_ns is None or winner.median_ns == 0:
            continue
        selections.append(
            BenchmarkSelection(
                routine=routine,
                candidate_id=winner.implementation_id,
                backend=winner.backend,
                speedup_over_serial=serial.median_ns / winner.median_ns,
            )
        )
    candidate_measurements = [
        item for item in measurements if item.backend is not CandidateBackend.SERIAL_PYTHON
    ]
    return BenchmarkReport(
        schema_version="0.1.0",
        migration_sha256=migration_sha256,
        verification_sha256=verification_sha256,
        cases_sha256=case_sha256,
        sandbox_image=image,
        warmups=warmups,
        repeats=repeats,
        iterations=iterations,
        environment=environment,
        measurements=tuple(measurements),
        selections=tuple(selections),
        summary=BenchmarkSummary(
            routines=len(by_routine),
            eligible_candidates=len(candidate_measurements),
            benchmarked_candidates=sum(
                item.status is BenchmarkStatus.BENCHMARKED for item in candidate_measurements
            ),
            unavailable_candidates=sum(
                item.status is BenchmarkStatus.UNAVAILABLE for item in candidate_measurements
            ),
        ),
    )
