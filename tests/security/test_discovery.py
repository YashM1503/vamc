from pathlib import Path

import pytest

from vamc.analysis.inventory import AnalysisError
from vamc.config import AnalysisConfig
from vamc.project import Project


def test_symlink_input_root_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.f90"
    source.write_text("program safe\nend program safe\n", encoding="utf-8")
    link = tmp_path / "link.f90"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("symlinks are unavailable")

    with pytest.raises(AnalysisError, match="symbolic-link"):
        Project.from_path(link).analyze()


def test_oversized_source_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "large.f90"
    source.write_text("program large\nend program large\n", encoding="utf-8")

    with pytest.raises(AnalysisError, match="size limit"):
        Project.from_path(source, AnalysisConfig(max_file_bytes=8)).analyze()


def test_symlinked_file_inside_tree_is_not_read(tmp_path: Path) -> None:
    outside = tmp_path / "outside.f90"
    outside.write_text("program outside\nend program outside\n", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    try:
        (project / "escape.f90").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable")

    result = Project.from_path(project).analyze()
    assert result.summary.files == 0
