import json
import sys
import types
from pathlib import Path

import pytest

from vamc.analysis.inventory import AnalysisError
from vamc.cli import main
from vamc.migration import MigrationResult
from vamc.models import TranslationStatus
from vamc.project import Project


def _load_generated_module(
    migration: MigrationResult, package_name: str, suffix: str
) -> types.ModuleType:
    artifacts = {item.path: item.content for item in migration.artifacts}
    package = types.ModuleType(package_name)
    package.__path__ = []
    package.__package__ = package_name
    runtime_name = f"{package_name}._runtime"
    runtime = types.ModuleType(runtime_name)
    runtime.__package__ = package_name
    sys.modules[package_name] = package
    sys.modules[runtime_name] = runtime
    try:
        exec(  # noqa: S102 - only fixed VAMC-generated test output is executed.
            compile(artifacts[f"src/{package_name}/_runtime.py"], "<generated-runtime>", "exec"),
            runtime.__dict__,
        )
        path = next(
            path
            for path in artifacts
            if path.startswith(f"src/{package_name}/") and path.endswith(f"{suffix}.py")
        )
        module_name = f"{package_name}.{Path(path).stem}"
        module = types.ModuleType(module_name)
        module.__package__ = package_name
        sys.modules[module_name] = module
        exec(  # noqa: S102 - only fixed VAMC-generated test output is executed.
            compile(artifacts[path], "<generated-module>", "exec"), module.__dict__
        )
        return module
    finally:
        for name in tuple(sys.modules):
            if name == package_name or name.startswith(f"{package_name}."):
                sys.modules.pop(name, None)


def test_daxpy_migration_is_deterministic_and_executable() -> None:
    example = Path(__file__).parents[2] / "examples" / "daxpy"
    first = Project.from_path(example).migrate(package_name="generated_daxpy")
    second = Project.from_path(example).migrate(package_name="generated_daxpy")

    assert first.manifest.to_dict() == second.manifest.to_dict()
    assert [(item.path, item.sha256) for item in first.artifacts] == [
        (item.path, item.sha256) for item in second.artifacts
    ]
    assert first.manifest.summary.translated_routines == 1
    assert first.manifest.summary.fallback_routines == 0
    assert len(first.manifest.source_maps) == 1

    module = _load_generated_module(first, "generated_daxpy", "5731f385")
    values = [10.0, 20.0, 30.0]
    module.daxpy(3, 2.0, [1.0, 2.0, 3.0], values)
    assert values == [12.0, 24.0, 36.0]


def test_scalar_output_argument_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "increment.f90"
    source.write_text(
        """subroutine increment(value)
  integer, intent(inout) :: value
  value = value + 1
end subroutine increment
""",
        encoding="utf-8",
    )

    migration = Project.from_path(source).migrate()

    routine = migration.manifest.routines[0]
    assert routine.status is TranslationStatus.FALLBACK_REQUIRED
    assert routine.fallback_reasons == ("scalar_output_argument",)
    assert migration.manifest.summary.fallback_routines == 1
    assert migration.manifest.source_maps == ()


def test_generated_function_condition_and_intrinsic_execute(tmp_path: Path) -> None:
    source = tmp_path / "clamp.f90"
    source.write_text(
        """real(kind=8) function clamp(x)
  real(kind=8), intent(in) :: x
  if (x .lt. 0.0d0) then
    clamp = abs(x)
  else
    clamp = sqrt(x)
  end if
end function clamp
""",
        encoding="utf-8",
    )
    migration = Project.from_path(source).migrate(package_name="generated_clamp")

    assert migration.manifest.summary.translated_routines == 1
    suffix = Path(migration.manifest.routines[0].generated_file or "").stem.split("_", 1)[1]
    module = _load_generated_module(migration, "generated_clamp", suffix)
    assert module.clamp(-4.0) == 4.0
    assert module.clamp(9.0) == 3.0


def test_write_creates_reviewable_package_and_never_clobbers(tmp_path: Path) -> None:
    example = Path(__file__).parents[2] / "examples" / "daxpy"
    migration = Project.from_path(example).migrate()
    output = tmp_path / "modern"

    assert migration.write(output) == output
    manifest = json.loads((output / "modernization.json").read_text(encoding="utf-8"))
    assert manifest["summary"]["translated_routines"] == 1
    assert (output / ".vamc-generated").is_file()
    assert (
        (output / "legacy" / "daxpy.f90").read_text(encoding="utf-8").startswith("subroutine daxpy")
    )

    with pytest.raises(AnalysisError, match="already exists"):
        migration.write(output)


def test_cli_migrate_can_fail_before_writing_unsupported_output(tmp_path: Path) -> None:
    source = tmp_path / "increment.f90"
    source.write_text(
        """subroutine increment(value)
  integer, intent(inout) :: value
  value = value + 1
end subroutine increment
""",
        encoding="utf-8",
    )
    output = tmp_path / "modern"

    with pytest.raises(SystemExit) as caught:
        main(["migrate", str(source), "--output", str(output), "--fail-on-unsupported"])
    assert caught.value.code == 2
    assert not output.exists()
