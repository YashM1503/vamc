"""Container-only F2PY oracle compilation and differential case execution."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from vamc.analysis.inventory import AnalysisError
from vamc.models import (
    ComparisonMetrics,
    NumericalPolicy,
    RoutineVerification,
    VerificationReport,
    VerificationStatus,
    VerificationSummary,
)
from vamc.runtime.sandbox import DockerSandbox, SandboxMount
from vamc.verify.compare import compare_values, scientific_default_policy
from vamc.verify.static import _load_migration_directory, verify_migration_directory

_FORTRAN_SUFFIXES = {".f", ".f03", ".f08", ".f77", ".f90", ".f95", ".for", ".ftn"}
_MAX_CASE_FILE_BYTES = 4 * 1024 * 1024
_MAX_CASES = 10_000


@dataclass(frozen=True)
class VerificationCase:
    identifier: str
    routine: str
    oracle_routine: str
    arguments: tuple[Any, ...]
    keywords: dict[str, Any]


@dataclass
class _RoutineState:
    cases: int = 0
    comparisons: list[ComparisonMetrics] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


def _read_case_file(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise AnalysisError("verification case file may not be a symbolic link")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise AnalysisError("cannot safely open verification case file") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_CASE_FILE_BYTES:
            raise AnalysisError("verification case file is not regular or exceeds its size limit")
        data = os.read(descriptor, _MAX_CASE_FILE_BYTES + 1)
        if len(data) > _MAX_CASE_FILE_BYTES:
            raise AnalysisError("verification case file exceeds its size limit")
    finally:
        os.close(descriptor)
    try:
        decoded = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise AnalysisError("verification case file is not valid bounded JSON") from error
    if not isinstance(decoded, dict):
        raise AnalysisError("verification case file must contain a JSON object")
    return decoded


def _entrypoint(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(not item.isidentifier() or item.startswith("_") for item in value.split("."))
    ):
        raise AnalysisError(f"verification case has an invalid {field_name}")
    return value.lower()


def load_cases(path: str | Path) -> tuple[VerificationCase, ...]:
    """Load and validate the bounded public differential-case schema."""

    document = _read_case_file(Path(path).expanduser())
    if document.get("schema_version") != "0.1.0" or not isinstance(document.get("cases"), list):
        raise AnalysisError("verification case schema must be version 0.1.0")
    raw_cases = document["cases"]
    if len(raw_cases) > _MAX_CASES:
        raise AnalysisError("verification case count exceeds configured limit")
    cases: list[VerificationCase] = []
    identifiers: set[str] = set()
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise AnalysisError("verification case entry must be an object")
        identifier = raw.get("id")
        if not isinstance(identifier, str) or not identifier or len(identifier) > 128:
            raise AnalysisError("verification case id is invalid")
        if identifier in identifiers:
            raise AnalysisError("verification case ids must be unique")
        identifiers.add(identifier)
        routine = _entrypoint(raw.get("routine"), "routine")
        oracle = _entrypoint(raw.get("oracle_routine", routine), "oracle_routine")
        arguments = raw.get("arguments", [])
        keywords = raw.get("keywords", {})
        if (
            not isinstance(arguments, list)
            or not isinstance(keywords, dict)
            or any(not isinstance(key, str) or not key.isidentifier() for key in keywords)
        ):
            raise AnalysisError("verification case arguments or keywords are invalid")
        cases.append(
            VerificationCase(
                identifier=identifier,
                routine=routine,
                oracle_routine=oracle,
                arguments=tuple(arguments),
                keywords=keywords,
            )
        )
    return tuple(cases)


def _zero_metrics(equal: bool) -> ComparisonMetrics:
    return ComparisonMetrics(
        equal=equal,
        compared_values=0,
        max_absolute_error=0.0,
        max_relative_error=0.0,
        nan_mismatches=0,
        infinity_mismatches=0,
        structural_mismatches=0 if equal else 1,
    )


def _combine(comparisons: list[ComparisonMetrics]) -> ComparisonMetrics:
    if not comparisons:
        return _zero_metrics(True)
    return ComparisonMetrics(
        equal=all(item.equal for item in comparisons),
        compared_values=sum(item.compared_values for item in comparisons),
        max_absolute_error=max(item.max_absolute_error for item in comparisons),
        max_relative_error=max(item.max_relative_error for item in comparisons),
        nan_mismatches=sum(item.nan_mismatches for item in comparisons),
        infinity_mismatches=sum(item.infinity_mismatches for item in comparisons),
        structural_mismatches=sum(item.structural_mismatches for item in comparisons),
    )


def _report(
    manifest: dict[str, Any],
    states: dict[str, _RoutineState],
    policy: NumericalPolicy,
    image: str,
    global_diagnostic: str | None = None,
) -> VerificationReport:
    results: list[RoutineVerification] = []
    for item in manifest.get("routines", []):
        if not isinstance(item, dict) or not isinstance(item.get("routine"), str):
            continue
        routine = item["routine"]
        state = states.setdefault(routine, _RoutineState())
        if global_diagnostic:
            state.diagnostics.append(global_diagnostic)
        metrics = _combine(state.comparisons)
        if item.get("status") != "TRANSLATED":
            status = VerificationStatus.UNAVAILABLE
            state.diagnostics.append("routine requires fallback")
        elif state.diagnostics:
            status = VerificationStatus.FAILED if state.cases else VerificationStatus.UNAVAILABLE
        elif state.cases and metrics.equal:
            status = VerificationStatus.VERIFIED_FOR_TEST_DOMAIN
        elif state.cases:
            status = VerificationStatus.FAILED
        else:
            status = VerificationStatus.UNAVAILABLE
            state.diagnostics.append("no differential cases supplied")
        results.append(
            RoutineVerification(
                routine=routine,
                status=status,
                cases=state.cases,
                policy=policy,
                metrics=metrics,
                diagnostics=tuple(dict.fromkeys(state.diagnostics)),
            )
        )
    statuses = [item.status for item in results]
    if VerificationStatus.FAILED in statuses:
        overall = VerificationStatus.FAILED
    elif VerificationStatus.VERIFIED_FOR_TEST_DOMAIN in statuses:
        overall = VerificationStatus.VERIFIED_FOR_TEST_DOMAIN
    else:
        overall = VerificationStatus.UNAVAILABLE
    return VerificationReport(
        schema_version="0.1.0",
        migration_schema_version=str(manifest.get("schema_version", "UNKNOWN")),
        status=overall,
        sandbox="docker (network disabled, read-only, capability-free)",
        sandbox_image=image,
        routines=tuple(results),
        summary=VerificationSummary(
            routines=len(results),
            statically_checked=0,
            verified_for_test_domain=statuses.count(VerificationStatus.VERIFIED_FOR_TEST_DOMAIN),
            failed=statuses.count(VerificationStatus.FAILED),
            unavailable=statuses.count(VerificationStatus.UNAVAILABLE),
        ),
    )


def _write_case(directory: Path, case: VerificationCase) -> Path:
    path = directory / "case.json"
    payload = {
        "arguments": list(case.arguments),
        "keywords": case.keywords,
    }
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, allow_nan=True, sort_keys=True)
        stream.write("\n")
    return path


def _run_one(
    sandbox: DockerSandbox,
    *,
    module: str,
    routine: str,
    module_root: str,
    module_source: Path,
    case_directory: Path,
    output_directory: Path,
) -> dict[str, Any] | None:
    runner = Path(__file__).with_name("sandbox_runner.py").parent
    result = sandbox.run(
        (
            "python",
            "/runner/sandbox_runner.py",
            "--module-root",
            module_root,
            "--module",
            module,
            "--routine",
            routine,
            "--case",
            "/case/case.json",
            "--output",
            "/result/result.json",
        ),
        mounts=(
            SandboxMount(runner, "/runner", True),
            SandboxMount(module_source, module_root, True),
            SandboxMount(case_directory, "/case", True),
            SandboxMount(output_directory, "/result", False),
        ),
        working_directory="/result",
    )
    output = output_directory / "result.json"
    if not result.succeeded or not output.is_file() or output.stat().st_size > _MAX_CASE_FILE_BYTES:
        return None
    try:
        decoded = json.loads(output.read_bytes())
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
        return None
    return decoded if isinstance(decoded, dict) else None


def verify_native_directory(
    migration_path: str | Path,
    cases_path: str | Path,
    *,
    image: str,
    policy: NumericalPolicy | None = None,
    sandbox: DockerSandbox | None = None,
) -> VerificationReport:
    """Compile the original with F2PY and compare cases only inside Docker."""

    selected_policy = policy or scientific_default_policy()
    modern = Path(migration_path).expanduser().resolve()
    static = verify_migration_directory(modern, policy=selected_policy)
    if static.status is VerificationStatus.FAILED:
        raise AnalysisError("native verification refused because static verification failed")
    manifest, contents = _load_migration_directory(modern)
    del contents
    cases = load_cases(cases_path)
    translated = {
        item["routine"]
        for item in manifest.get("routines", [])
        if isinstance(item, dict)
        and item.get("status") == "TRANSLATED"
        and isinstance(item.get("routine"), str)
    }
    for case in cases:
        if case.routine not in translated:
            raise AnalysisError(
                f"verification case targets a non-translated routine: {case.routine}"
            )
    selected_sandbox = sandbox or DockerSandbox(image)
    states = {routine: _RoutineState() for routine in translated}
    if not selected_sandbox.probe().succeeded:
        return _report(
            manifest,
            states,
            selected_policy,
            image,
            "Docker engine is unavailable; native verification did not run",
        )

    legacy = modern / "legacy"
    source_paths = sorted(
        PurePosixPath(item["path"]).relative_to("legacy").as_posix()
        for item in manifest.get("artifacts", [])
        if isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and PurePosixPath(item["path"]).suffix.lower() in _FORTRAN_SUFFIXES
        and PurePosixPath(item["path"]).parts[0] == "legacy"
    )
    if not source_paths:
        return _report(
            manifest, states, selected_policy, image, "no captured Fortran sources are available"
        )

    with tempfile.TemporaryDirectory(prefix="vamc-oracle-") as oracle_name:
        oracle = Path(oracle_name)
        compile_arguments = (
            "python",
            "-m",
            "numpy.f2py",
            "-c",
            "--backend",
            "meson",
            "-m",
            "vamc_oracle",
            *(f"/input/{path}" for path in source_paths),
        )
        compiled = selected_sandbox.run(
            compile_arguments,
            mounts=(
                SandboxMount(legacy, "/input", True),
                SandboxMount(oracle, "/output", False),
            ),
            working_directory="/output",
        )
        if not compiled.succeeded:
            return _report(
                manifest,
                states,
                selected_policy,
                image,
                "F2PY oracle compilation failed inside the sandbox",
            )

        package_name = manifest.get("package_name")
        if not isinstance(package_name, str) or not package_name.isidentifier():
            raise AnalysisError("migration package name is invalid")
        for case in cases:
            with tempfile.TemporaryDirectory(prefix="vamc-case-") as case_name:
                case_directory = Path(case_name)
                _write_case(case_directory, case)
                oracle_result_dir = case_directory / "oracle-result"
                candidate_result_dir = case_directory / "candidate-result"
                oracle_result_dir.mkdir()
                candidate_result_dir.mkdir()
                oracle_result = _run_one(
                    selected_sandbox,
                    module="vamc_oracle",
                    routine=case.oracle_routine,
                    module_root="/oracle",
                    module_source=oracle,
                    case_directory=case_directory,
                    output_directory=oracle_result_dir,
                )
                candidate_result = _run_one(
                    selected_sandbox,
                    module=package_name,
                    routine=case.routine,
                    module_root="/modern/src",
                    module_source=modern / "src",
                    case_directory=case_directory,
                    output_directory=candidate_result_dir,
                )
                state = states[case.routine]
                state.cases += 1
                if oracle_result is None or candidate_result is None:
                    state.diagnostics.append(f"sandbox execution failed for case {case.identifier}")
                    continue
                state.comparisons.append(
                    compare_values(oracle_result, candidate_result, selected_policy)
                )
        return _report(manifest, states, selected_policy, image)
