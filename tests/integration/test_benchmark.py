import json
from pathlib import Path

import pytest

from vamc.analysis.inventory import AnalysisError
from vamc.benchmark import benchmark_migration_directory
from vamc.models import BenchmarkStatus, CandidateBackend
from vamc.project import Project
from vamc.runtime.sandbox import DockerSandbox, SandboxMount, SandboxResult
from vamc.verify.native import verify_native_directory

_IMAGE = "example.invalid/vamc-sandbox@sha256:" + "b" * 64


class _BenchmarkSandbox(DockerSandbox):
    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    def probe(self) -> SandboxResult:
        return SandboxResult(("probe",), 0 if self.available else 1, "", False, False)

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        mounts: tuple[SandboxMount, ...] = (),
        working_directory: str = "/work",
    ) -> SandboxResult:
        del working_directory
        if "numpy.f2py" in arguments:
            return SandboxResult(arguments, 0, "", False, False)
        module = arguments[arguments.index("--module") + 1]
        output = next(item.source for item in mounts if item.target == "/result")
        if "/runner/benchmark_runner.py" in arguments:
            repeats = int(arguments[arguments.index("--repeats") + 1])
            timing = 1_000
            if "numba_parallel" in module:
                timing = 200
            elif "numpy" in module:
                timing = 300
            elif "numba_serial" in module:
                timing = 400
            payload: dict[str, object] = {
                "environment": {
                    "machine": "test-machine",
                    "numba": "test-numba",
                    "numpy": "test-numpy",
                    "platform": "test-platform",
                    "python": "test-python",
                },
                "samples_ns": [timing] * repeats,
                "status": "benchmarked",
            }
        else:
            payload = {
                "arguments": [3, 2.0, [1.0, 2.0, 3.0], [12.0, 24.0, 36.0]],
                "keywords": {},
                "return": None,
                "status": "returned",
            }
        (output / "result.json").write_text(json.dumps(payload), encoding="utf-8")
        return SandboxResult(arguments, 0, "", False, False)


def _case_file(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "cases": [
                    {
                        "id": "small",
                        "routine": "daxpy",
                        "arguments": [
                            {"kind": "scalar", "value": 3},
                            {"kind": "scalar", "value": 2.0},
                            {"kind": "array", "dtype": "float64", "value": [1, 2, 3]},
                            {"kind": "array", "dtype": "float64", "value": [10, 20, 30]},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _verified_migration(tmp_path: Path) -> tuple[Path, Path, Path]:
    example = Path(__file__).parents[2] / "examples" / "daxpy"
    modern = (
        Project.from_path(example)
        .migrate(optimize=True, parallel="auto")
        .write(tmp_path / "modern")
    )
    cases = _case_file(tmp_path / "cases.json")
    verification = verify_native_directory(
        modern,
        cases,
        image=_IMAGE,
        sandbox=_BenchmarkSandbox(),
    )
    verification_path = tmp_path / "verification.json"
    verification_path.write_text(json.dumps(verification.to_dict()), encoding="utf-8")
    return modern, cases, verification_path


def test_benchmark_ranks_only_verified_candidates(tmp_path: Path) -> None:
    modern, cases, verification = _verified_migration(tmp_path)

    report = benchmark_migration_directory(
        modern,
        cases,
        verification,
        image=_IMAGE,
        repeats=3,
        iterations=2,
        sandbox=_BenchmarkSandbox(),
    )

    assert report.summary.eligible_candidates == 3
    assert report.summary.benchmarked_candidates == 3
    assert report.summary.unavailable_candidates == 0
    assert report.environment is not None
    assert report.environment.machine == "test-machine"
    assert report.selections[0].backend is CandidateBackend.NUMBA_PARALLEL
    assert report.selections[0].speedup_over_serial == 5.0
    assert all(item.status is BenchmarkStatus.BENCHMARKED for item in report.measurements)


def test_benchmark_rejects_stale_case_evidence(tmp_path: Path) -> None:
    modern, cases, verification = _verified_migration(tmp_path)
    _case_file(cases)
    document = json.loads(cases.read_text(encoding="utf-8"))
    document["cases"][0]["arguments"][0]["value"] = 4
    cases.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(AnalysisError, match="case set"):
        benchmark_migration_directory(
            modern,
            cases,
            verification,
            image=_IMAGE,
            sandbox=_BenchmarkSandbox(),
        )


def test_benchmark_reports_unavailable_without_host_fallback(tmp_path: Path) -> None:
    modern, cases, verification = _verified_migration(tmp_path)

    report = benchmark_migration_directory(
        modern,
        cases,
        verification,
        image=_IMAGE,
        repeats=2,
        sandbox=_BenchmarkSandbox(available=False),
    )

    assert report.summary.benchmarked_candidates == 0
    assert report.summary.unavailable_candidates == 3
    assert report.selections == ()
