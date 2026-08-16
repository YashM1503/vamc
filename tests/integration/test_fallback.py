import importlib
import json
import sys
from pathlib import Path

import pytest

from vamc.analysis.inventory import AnalysisError
from vamc.fallback import build_fallback
from vamc.models import FallbackBuildStatus
from vamc.project import Project
from vamc.runtime.sandbox import DockerSandbox, SandboxMount, SandboxResult

_IMAGE = "example.invalid/vamc-sandbox@sha256:" + "c" * 64


class _BuildSandbox(DockerSandbox):
    def __init__(self, *, available: bool = True, symlink: bool = False) -> None:
        self.available = available
        self.symlink = symlink

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
        output = next(item.source for item in mounts if item.target == "/output")
        extension = output / "_vamc_legacy.cpython-test.so"
        if self.symlink:
            extension.symlink_to(output / "missing")
        else:
            extension.write_bytes(b"reviewed-test-extension")
        return SandboxResult(arguments, 0, "", False, False)


def _fallback_migration(tmp_path: Path) -> Path:
    source = tmp_path / "increment.f90"
    source.write_text(
        """subroutine increment(value)
  integer, intent(inout) :: value
  value = value + 1
end subroutine increment
""",
        encoding="utf-8",
    )
    return (
        Project.from_path(source)
        .migrate(package_name="generated_fallback")
        .write(tmp_path / "modern")
    )


def test_generated_package_exposes_only_explicit_fallback_dispatch(tmp_path: Path) -> None:
    migration = _fallback_migration(tmp_path)
    sys.path.insert(0, str(migration / "src"))
    try:
        package = importlib.import_module("generated_fallback")
        assert package.FALLBACKS["increment"]["source_file"] == "increment.f90"
        assert not package.fallback_available("increment")
        with pytest.raises(package.FallbackUnavailableError, match="not bound"):
            package.increment(1)

        package.bind_fallback(entrypoints={"increment": lambda value: value + 1})
        assert package.fallback_available("increment")
        assert package.increment(1) == 2
    finally:
        sys.path.remove(str(migration / "src"))
        for name in tuple(sys.modules):
            if name == "generated_fallback" or name.startswith("generated_fallback."):
                sys.modules.pop(name, None)


def test_fallback_routine_name_cannot_shadow_bridge_controls(tmp_path: Path) -> None:
    source = tmp_path / "collision.f90"
    source.write_text(
        """subroutine bind_fallback(value)
  integer, intent(inout) :: value
  value = value + 1
end subroutine bind_fallback
""",
        encoding="utf-8",
    )
    migration = (
        Project.from_path(source)
        .migrate(package_name="generated_collision")
        .write(tmp_path / "collision-modern")
    )
    sys.path.insert(0, str(migration / "src"))
    try:
        package = importlib.import_module("generated_collision")
        package.bind_fallback(entrypoints={"bind_fallback": lambda value: value + 1})
        assert package.fortran_bind_fallback(1) == 2
    finally:
        sys.path.remove(str(migration / "src"))
        for name in tuple(sys.modules):
            if name == "generated_collision" or name.startswith("generated_collision."):
                sys.modules.pop(name, None)


def test_fallback_build_is_sandboxed_and_traceable(tmp_path: Path) -> None:
    migration = _fallback_migration(tmp_path)
    output = tmp_path / "fallback"

    report = build_fallback(
        migration,
        output,
        image=_IMAGE,
        sandbox=_BuildSandbox(),
    )

    assert report.status is FallbackBuildStatus.BUILT
    assert report.artifact is not None
    assert (output / report.artifact).read_bytes() == b"reviewed-test-extension"
    record = json.loads((output / "fallback-build.json").read_text(encoding="utf-8"))
    assert record["artifact_sha256"] == report.artifact_sha256
    assert record["migration_sha256"] == report.migration_sha256


def test_fallback_build_has_no_host_fallback(tmp_path: Path) -> None:
    migration = _fallback_migration(tmp_path)
    output = tmp_path / "fallback"

    report = build_fallback(
        migration,
        output,
        image=_IMAGE,
        sandbox=_BuildSandbox(available=False),
    )

    assert report.status is FallbackBuildStatus.UNAVAILABLE
    assert not output.exists()


def test_fallback_build_rejects_symlinked_compiler_output(tmp_path: Path) -> None:
    migration = _fallback_migration(tmp_path)

    with pytest.raises(AnalysisError, match="symbolic link"):
        build_fallback(
            migration,
            tmp_path / "fallback",
            image=_IMAGE,
            sandbox=_BuildSandbox(symlink=True),
        )
