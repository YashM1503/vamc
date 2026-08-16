import json
from pathlib import Path

import pytest

from vamc.analysis.inventory import AnalysisError
from vamc.cli import main
from vamc.models import VerificationStatus
from vamc.project import Project
from vamc.verify.static import verify_migration_directory


def test_in_memory_and_materialized_static_verification(tmp_path: Path) -> None:
    example = Path(__file__).parents[2] / "examples" / "daxpy"
    migration = Project.from_path(example).migrate()

    in_memory = migration.verify()
    assert in_memory.status is VerificationStatus.STATICALLY_CHECKED
    assert in_memory.summary.statically_checked == 1
    assert in_memory.summary.verified_for_test_domain == 0

    output = migration.write(tmp_path / "modern")
    materialized = verify_migration_directory(output)
    assert materialized.to_dict() == in_memory.to_dict()
    assert main(["verify", str(output)]) == 0


def test_tampering_is_detected_without_importing_generated_code(tmp_path: Path) -> None:
    example = Path(__file__).parents[2] / "examples" / "daxpy"
    output = Project.from_path(example).migrate().write(tmp_path / "modern")
    generated = next((output / "src" / "vamc_modernized").glob("daxpy_*.py"))
    generated.write_text("raise RuntimeError('must never execute')\n", encoding="utf-8")

    report = verify_migration_directory(output)

    assert report.status is VerificationStatus.FAILED
    assert report.summary.failed == 1
    assert any("integrity" in item for item in report.routines[0].diagnostics)


def test_verifier_rejects_symlinked_artifact(tmp_path: Path) -> None:
    example = Path(__file__).parents[2] / "examples" / "daxpy"
    output = Project.from_path(example).migrate().write(tmp_path / "modern")
    analysis = output / "analysis.json"
    target = tmp_path / "target.json"
    target.write_text(analysis.read_text(encoding="utf-8"), encoding="utf-8")
    analysis.unlink()
    try:
        analysis.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are not available")

    with pytest.raises(AnalysisError, match="safely read"):
        verify_migration_directory(output)


def test_verifier_rejects_duplicate_manifest_identities(tmp_path: Path) -> None:
    example = Path(__file__).parents[2] / "examples" / "daxpy"
    output = Project.from_path(example).migrate().write(tmp_path / "modern")
    manifest_path = output / "modernization.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"].append(manifest["artifacts"][0])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(AnalysisError, match="duplicated"):
        verify_migration_directory(output)
