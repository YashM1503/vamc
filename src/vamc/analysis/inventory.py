"""Project-level Fortran inventory orchestration."""

import os
from collections.abc import Iterable
from pathlib import Path

from vamc.config import AnalysisConfig
from vamc.frontends.fortran import FORTRAN_SUFFIXES, analyze_fortran_source
from vamc.models import AnalysisResult, AnalysisSummary, SourceFileDigest, SupportStatus

_IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}


class AnalysisError(RuntimeError):
    """Raised when safe, bounded analysis cannot proceed."""


def _inside(candidate: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((str(candidate), str(root))) == str(root)
    except ValueError:
        return False


def _discover(root: Path, config: AnalysisConfig) -> Iterable[Path]:
    if root.is_file():
        if root.suffix.lower() not in FORTRAN_SUFFIXES:
            raise AnalysisError("input file is not a supported Fortran source")
        yield root
        return

    count = 0
    for directory, names, files in os.walk(str(root), followlinks=False):
        names[:] = sorted(
            name
            for name in names
            if name not in _IGNORED_DIRECTORIES
            and (config.include_hidden or not name.startswith("."))
            and not Path(directory, name).is_symlink()
        )
        for name in sorted(files):
            if not config.include_hidden and name.startswith("."):
                continue
            candidate = Path(directory, name)
            if candidate.is_symlink() or candidate.suffix.lower() not in FORTRAN_SUFFIXES:
                continue
            count += 1
            if count > config.max_files:
                raise AnalysisError("source file count exceeds configured limit")
            yield candidate


def analyze_project(input_path: Path, config: AnalysisConfig) -> AnalysisResult:
    requested = input_path.expanduser()
    if requested.is_symlink():
        raise AnalysisError("symbolic-link input roots are not accepted")
    root = requested.resolve()
    if not root.exists():
        raise AnalysisError(f"input path does not exist: {input_path}")
    if not root.is_file() and not root.is_dir():
        raise AnalysisError("input path must be a regular file or directory")

    source_root = root.parent if root.is_file() else root
    digests: list[SourceFileDigest] = []
    for path in _discover(root, config):
        resolved = path.resolve()
        if not _inside(resolved, source_root):
            raise AnalysisError("source path escapes the requested root")
        size = resolved.stat().st_size
        if size > config.max_file_bytes:
            raise AnalysisError(f"source file exceeds size limit: {path.name}")
        try:
            data = resolved.read_bytes()
            data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise AnalysisError(f"source file is not valid UTF-8: {path.name}") from error
        relative = resolved.relative_to(source_root).as_posix()
        digests.append(analyze_fortran_source(resolved, relative, data))

    ordered: tuple[SourceFileDigest, ...] = tuple(sorted(digests, key=lambda item: item.path))
    routines = [routine for file_digest in ordered for routine in file_digest.routines]
    return AnalysisResult(
        schema_version="0.1.0",
        source_root=root.name,
        files=ordered,
        summary=AnalysisSummary(
            files=len(ordered),
            routines=len(routines),
            loops=sum(len(routine.loops) for routine in routines),
            calls=sum(len(routine.calls) for routine in routines),
            fallback_routines=sum(
                routine.support_status is SupportStatus.REQUIRES_FALLBACK for routine in routines
            ),
        ),
    )
