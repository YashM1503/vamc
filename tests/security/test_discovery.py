import os
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


def test_fifo_with_fortran_suffix_is_rejected_without_opening(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFOs are unavailable")
    fifo = tmp_path / "block.f90"
    os.mkfifo(fifo)

    with pytest.raises(AnalysisError, match="regular file"):
        Project.from_path(tmp_path).analyze()


def test_total_byte_limit_is_enforced(tmp_path: Path) -> None:
    for name in ("one.f90", "two.f90"):
        (tmp_path / name).write_text("program p\nend program p\n", encoding="utf-8")

    with pytest.raises(AnalysisError, match="total byte limit"):
        Project.from_path(tmp_path, AnalysisConfig(max_total_bytes=30)).analyze()


def test_line_and_statement_limits_are_enforced(tmp_path: Path) -> None:
    source = tmp_path / "limits.f90"
    source.write_text("program p\nend program p\n", encoding="utf-8")

    with pytest.raises(AnalysisError, match="line-count limit"):
        Project.from_path(source, AnalysisConfig(max_lines_per_file=1)).analyze()

    source.write_text("program p; integer::i; i=1; end program p", encoding="utf-8")
    with pytest.raises(AnalysisError, match="statement-count limit"):
        Project.from_path(source, AnalysisConfig(max_statements_per_file=3)).analyze()


def test_invalid_utf8_and_overlong_lines_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "invalid.f90"
    source.write_bytes(b"program p\n\xff\nend\n")
    with pytest.raises(AnalysisError, match="valid UTF-8"):
        Project.from_path(source).analyze()

    source.write_text("program p\n123456789\nend\n", encoding="utf-8")
    with pytest.raises(AnalysisError, match="overlong line"):
        Project.from_path(source, AnalysisConfig(max_line_bytes=8)).analyze()


def test_hidden_sources_are_opt_in(tmp_path: Path) -> None:
    (tmp_path / ".hidden.f90").write_text("program p\nend\n", encoding="utf-8")

    assert Project.from_path(tmp_path).analyze().summary.files == 0
    assert (
        Project.from_path(tmp_path, AnalysisConfig(include_hidden=True)).analyze().summary.files
        == 1
    )


def test_loop_nesting_limit_is_enforced(tmp_path: Path) -> None:
    source = tmp_path / "nested.f90"
    source.write_text(
        "subroutine nested(n)\ndo i=1,n\ndo j=1,n\nend do\nend do\nend\n",
        encoding="utf-8",
    )

    with pytest.raises(AnalysisError, match="loop-nesting limit"):
        Project.from_path(source, AnalysisConfig(max_loop_nesting=1)).analyze()


def test_unsupported_single_file_and_missing_input_fail_explicitly(tmp_path: Path) -> None:
    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("not Fortran", encoding="utf-8")

    with pytest.raises(AnalysisError, match="not a supported Fortran source"):
        Project.from_path(unsupported).analyze()
    with pytest.raises(AnalysisError, match="input path does not exist"):
        Project.from_path(tmp_path / "missing.f90").analyze()


def test_source_file_count_limit_is_enforced(tmp_path: Path) -> None:
    for name in ("one.f90", "two.f90"):
        (tmp_path / name).write_text("program p\nend program p\n", encoding="utf-8")

    with pytest.raises(AnalysisError, match="file count"):
        Project.from_path(tmp_path, AnalysisConfig(max_files=1)).analyze()
