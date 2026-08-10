import json
import sys
from pathlib import Path

import pytest

from vamc.analysis.inventory import AnalysisError
from vamc.models import VerificationStatus
from vamc.project import Project
from vamc.runtime.sandbox import (
    DockerSandbox,
    SandboxLimits,
    SandboxMount,
    SandboxResult,
)
from vamc.verify.native import load_cases, verify_native_directory

_IMAGE = "example.invalid/vamc-sandbox@sha256:" + "a" * 64


class _FakeSandbox(DockerSandbox):
    def __init__(self, *, mismatch: bool = False, compile_failure: bool = False) -> None:
        self.mismatch = mismatch
        self.compile_failure = compile_failure

    def probe(self) -> SandboxResult:
        return SandboxResult(("probe",), 0, "", False, False)

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        mounts: tuple[SandboxMount, ...] = (),
        working_directory: str = "/work",
    ) -> SandboxResult:
        del working_directory
        if "numpy.f2py" in arguments:
            return SandboxResult(
                arguments,
                1 if self.compile_failure else 0,
                "",
                False,
                False,
            )
        module = arguments[arguments.index("--module") + 1]
        output = next(item.source for item in mounts if item.target == "/result")
        values = [12.0, 24.0, 36.0]
        if self.mismatch and module != "vamc_oracle":
            values[-1] = 99.0
        response: dict[str, object] = {
            "arguments": [3, 2.0, [1.0, 2.0, 3.0], values],
            "keywords": {},
            "return": None,
            "status": "returned",
        }
        (output / "result.json").write_text(json.dumps(response), encoding="utf-8")
        return SandboxResult(arguments, 0, "", False, False)


def test_docker_command_has_mandatory_isolation_controls(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    sandbox = DockerSandbox(_IMAGE, executable=sys.executable)

    command = sandbox.command(("python", "-V"), mounts=(SandboxMount(source, "/input", True),))

    assert "--network=none" in command
    assert "--read-only" in command
    assert "--cap-drop=ALL" in command
    assert "--security-opt=no-new-privileges:true" in command
    assert any(item.startswith("--pids-limit=") for item in command)
    assert any(item.startswith("--memory=") for item in command)
    assert any(item.startswith("--cpus=") for item in command)
    assert "--env=HOME=/tmp" in command
    assert command[-3:] == (_IMAGE, "python", "-V")
    mount = command[command.index("--mount") + 1]
    assert mount.endswith(",target=/input,readonly")


def test_sandbox_requires_pinned_image_and_positive_limits() -> None:
    with pytest.raises(ValueError, match="pinned"):
        DockerSandbox("python:latest", executable=sys.executable)
    with pytest.raises(ValueError, match="positive"):
        SandboxLimits(wall_seconds=0)


def test_case_schema_is_bounded_and_unique(tmp_path: Path) -> None:
    cases = tmp_path / "cases.json"
    cases.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "cases": [
                    {
                        "id": "small",
                        "routine": "daxpy",
                        "arguments": [
                            {"kind": "scalar", "value": 3},
                            {"kind": "array", "dtype": "float64", "value": [1, 2, 3]},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_cases(cases)
    assert loaded[0].routine == "daxpy"
    assert loaded[0].oracle_routine == "daxpy"

    cases.write_text(
        '{"schema_version":"0.1.0","cases":['
        '{"id":"same","routine":"x"},{"id":"same","routine":"x"}]}',
        encoding="utf-8",
    )
    with pytest.raises(AnalysisError, match="unique"):
        load_cases(cases)


def test_native_verification_reports_unavailable_without_host_fallback(tmp_path: Path) -> None:
    example = Path(__file__).parents[2] / "examples" / "daxpy"
    modern = Project.from_path(example).migrate().write(tmp_path / "modern")
    cases = tmp_path / "cases.json"
    cases.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "cases": [{"id": "small", "routine": "daxpy", "arguments": []}],
            }
        ),
        encoding="utf-8",
    )
    unavailable = DockerSandbox(
        _IMAGE,
        executable=sys.executable,
        limits=SandboxLimits(wall_seconds=2),
    )

    report = verify_native_directory(
        modern,
        cases,
        image=_IMAGE,
        sandbox=unavailable,
    )

    assert report.status is VerificationStatus.UNAVAILABLE
    assert report.summary.unavailable == 1
    assert "unavailable" in report.routines[0].diagnostics[0].lower()


def test_native_verification_records_domain_scoped_pass_and_failure(tmp_path: Path) -> None:
    example = Path(__file__).parents[2] / "examples" / "daxpy"
    modern = Project.from_path(example).migrate().write(tmp_path / "modern")
    cases = tmp_path / "cases.json"
    cases.write_text(
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

    passing = verify_native_directory(
        modern,
        cases,
        image=_IMAGE,
        sandbox=_FakeSandbox(),
    )
    failing = verify_native_directory(
        modern,
        cases,
        image=_IMAGE,
        sandbox=_FakeSandbox(mismatch=True),
    )

    assert passing.status is VerificationStatus.VERIFIED_FOR_TEST_DOMAIN
    assert passing.routines[0].cases == 1
    assert passing.routines[0].metrics.compared_values > 0
    assert failing.status is VerificationStatus.FAILED
    assert failing.routines[0].metrics.max_absolute_error == 63.0


def test_native_verification_reports_oracle_compile_failure(tmp_path: Path) -> None:
    example = Path(__file__).parents[2] / "examples" / "daxpy"
    modern = Project.from_path(example).migrate().write(tmp_path / "modern")
    cases = tmp_path / "cases.json"
    cases.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "cases": [{"id": "small", "routine": "daxpy"}],
            }
        ),
        encoding="utf-8",
    )

    report = verify_native_directory(
        modern,
        cases,
        image=_IMAGE,
        sandbox=_FakeSandbox(compile_failure=True),
    )

    assert report.status is VerificationStatus.UNAVAILABLE
    assert "compilation failed" in report.routines[0].diagnostics[0]
