"""Project-level Fortran inventory orchestration."""

import os
import stat
from collections.abc import Iterable
from dataclasses import dataclass, replace
from importlib.metadata import version
from pathlib import Path

from vamc._version import __version__
from vamc.config import AnalysisConfig
from vamc.frontends.fortran import FORTRAN_SUFFIXES, analyze_fortran_source
from vamc.frontends.psyir import enrich_with_psyir
from vamc.models import (
    AnalysisLimits,
    AnalysisProvenance,
    AnalysisResult,
    AnalysisSummary,
    CallGraphEdge,
    CallResolution,
    ParserStatus,
    RoutineDigest,
    SourceFileDigest,
    SupportStatus,
)

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


@dataclass(frozen=True)
class LoadedSource:
    """A source file captured through the bounded, root-anchored reader."""

    relative_path: str
    text: str


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

    def fail_walk(error: OSError) -> None:
        raise AnalysisError(f"cannot traverse source directory: {error.filename}") from error

    for directory, names, files in os.walk(str(root), followlinks=False, onerror=fail_walk):
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


def _open_root_directory(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise AnalysisError("source root is not a directory")
        return descriptor
    except OSError as error:
        raise AnalysisError("cannot safely open the source root") from error


def _open_anchored(root_descriptor: int, relative: Path, flags: int) -> tuple[int, os.stat_result]:
    """Open a relative path beneath an already-open directory descriptor."""

    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise AnalysisError("invalid source path discovered beneath source root")
    directory_descriptor = os.dup(root_descriptor)
    try:
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        for component in relative.parts[:-1]:
            next_descriptor = os.open(component, directory_flags, dir_fd=directory_descriptor)
            os.close(directory_descriptor)
            directory_descriptor = next_descriptor
        before = os.stat(relative.name, dir_fd=directory_descriptor, follow_symlinks=False)
        descriptor = os.open(relative.name, flags, dir_fd=directory_descriptor)
        return descriptor, before
    finally:
        os.close(directory_descriptor)


def _read_regular_file(
    root_descriptor: int, relative: Path, display_path: Path, config: AnalysisConfig
) -> bytes:
    """Read one bounded regular file through a root-anchored descriptor."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor, before = _open_anchored(root_descriptor, relative, flags)
        if not stat.S_ISREG(before.st_mode):
            os.close(descriptor)
            raise AnalysisError(f"source is not a regular file: {display_path.name}")
    except (OSError, ValueError) as error:
        raise AnalysisError(f"cannot safely open source file: {display_path.name}") from error

    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise AnalysisError(f"source is not a regular file: {display_path.name}")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise AnalysisError(f"source changed while being opened: {display_path.name}")
        if opened.st_size > config.max_file_bytes:
            raise AnalysisError(f"source file exceeds size limit: {display_path.name}")

        chunks: list[bytes] = []
        remaining = config.max_file_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > config.max_file_bytes:
            raise AnalysisError(f"source file exceeds size limit: {display_path.name}")
        return data
    except OSError as error:
        raise AnalysisError(f"cannot safely read source file: {display_path.name}") from error
    finally:
        os.close(descriptor)


def _validate_text_bounds(data: bytes, path: Path, config: AnalysisConfig) -> None:
    lines = data.splitlines()
    if len(lines) > config.max_lines_per_file:
        raise AnalysisError(f"source file exceeds line-count limit: {path.name}")
    if any(len(line) > config.max_line_bytes for line in lines):
        raise AnalysisError(f"source file contains an overlong line: {path.name}")


def _call_graph(files: tuple[SourceFileDigest, ...]) -> tuple[CallGraphEdge, ...]:
    definitions: dict[str, list[tuple[str, str]]] = {}
    for file_digest in files:
        for routine in file_digest.routines:
            definitions.setdefault(routine.name, []).append((file_digest.path, routine.name))

    edges: list[CallGraphEdge] = []
    for file_digest in files:
        for routine in file_digest.routines:
            for callee in routine.calls:
                targets = definitions.get(callee, [])
                if len(targets) == 1:
                    resolution = CallResolution.RESOLVED
                    target_file, target_routine = targets[0]
                elif len(targets) > 1:
                    resolution = CallResolution.AMBIGUOUS
                    target_file = None
                    target_routine = None
                else:
                    resolution = CallResolution.UNRESOLVED
                    target_file = None
                    target_routine = None
                edges.append(
                    CallGraphEdge(
                        caller_file=file_digest.path,
                        caller_routine=routine.name,
                        callee=callee,
                        resolution=resolution,
                        target_file=target_file,
                        target_routine=target_routine,
                    )
                )
    return tuple(
        sorted(
            edges,
            key=lambda item: (item.caller_file, item.caller_routine, item.callee),
        )
    )


def _resolved_support(
    files: tuple[SourceFileDigest, ...], edges: tuple[CallGraphEdge, ...]
) -> tuple[SourceFileDigest, ...]:
    by_caller: dict[tuple[str, str], list[CallGraphEdge]] = {}
    for edge in edges:
        by_caller.setdefault((edge.caller_file, edge.caller_routine), []).append(edge)

    resolved_files: list[SourceFileDigest] = []
    for file_digest in files:
        routines: list[RoutineDigest] = []
        for routine in file_digest.routines:
            unsupported = set(routine.unsupported_constructs)
            call_edges = by_caller.get((file_digest.path, routine.name), [])
            if call_edges and all(
                edge.resolution is CallResolution.RESOLVED for edge in call_edges
            ):
                unsupported.discard("unresolved_external_call")
            support = routine.support_status
            if routine.parser_status is ParserStatus.AUTHORITATIVE and not unsupported:
                support = SupportStatus.AUTHORITATIVELY_PARSED
            elif unsupported:
                support = SupportStatus.REQUIRES_FALLBACK
            routines.append(
                replace(
                    routine,
                    support_status=support,
                    unsupported_constructs=tuple(sorted(unsupported)),
                )
            )
        file_fallback = (
            file_digest.parser_status in {ParserStatus.FAILED, ParserStatus.PARTIAL}
            or not routines
            or any(
                routine.support_status is SupportStatus.REQUIRES_FALLBACK for routine in routines
            )
        )
        resolved_files.append(
            replace(
                file_digest,
                routines=tuple(routines),
                support_status=(
                    SupportStatus.REQUIRES_FALLBACK
                    if file_fallback
                    else SupportStatus.AUTHORITATIVELY_PARSED
                ),
            )
        )
    return tuple(resolved_files)


def analyze_project_with_sources(
    input_path: Path, config: AnalysisConfig
) -> tuple[AnalysisResult, tuple[LoadedSource, ...]]:
    """Analyze a project and retain the exact bounded source snapshot in memory."""

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
    loaded_sources: list[LoadedSource] = []
    total_bytes = 0
    root_descriptor = _open_root_directory(source_root)
    try:
        for path in _discover(root, config):
            relative_path = path.relative_to(source_root)
            resolved = path.resolve()
            if not _inside(resolved, source_root):
                raise AnalysisError("source path escapes the requested root")
            try:
                data = _read_regular_file(root_descriptor, relative_path, path, config)
                source = data.decode("utf-8-sig")
            except UnicodeDecodeError as error:
                raise AnalysisError(f"source file is not valid UTF-8: {path.name}") from error
            _validate_text_bounds(data, resolved, config)
            total_bytes += len(data)
            if total_bytes > config.max_total_bytes:
                raise AnalysisError("source tree exceeds total byte limit")
            relative = relative_path.as_posix()
            loaded_sources.append(LoadedSource(relative_path=relative, text=source))
            try:
                lexical = analyze_fortran_source(
                    resolved,
                    relative,
                    data,
                    max_statements=config.max_statements_per_file,
                    max_loop_nesting=config.max_loop_nesting,
                )
                digests.append(
                    enrich_with_psyir(
                        source,
                        lexical,
                        max_ir_nodes=config.max_ir_nodes_per_file,
                    )
                )
            except ValueError as error:
                raise AnalysisError(f"cannot analyze {path.name}: {error}") from error
    finally:
        os.close(root_descriptor)

    ordered = tuple(sorted(digests, key=lambda item: item.path))
    graph = _call_graph(ordered)
    ordered = _resolved_support(ordered, graph)
    routines = [routine for file_digest in ordered for routine in file_digest.routines]
    resolutions = [edge.resolution for edge in graph]
    result = AnalysisResult(
        schema_version="0.3.0",
        source_root=source_root.name,
        provenance=AnalysisProvenance(
            tool_version=__version__,
            frontend="vamc.psyir-fortran.v1",
            limits=AnalysisLimits(
                max_file_bytes=config.max_file_bytes,
                max_total_bytes=config.max_total_bytes,
                max_files=config.max_files,
                max_lines_per_file=config.max_lines_per_file,
                max_line_bytes=config.max_line_bytes,
                max_statements_per_file=config.max_statements_per_file,
                max_loop_nesting=config.max_loop_nesting,
                include_hidden=config.include_hidden,
                max_ir_nodes_per_file=config.max_ir_nodes_per_file,
            ),
            authoritative_frontend=f"PSyclone {version('psyclone')} / fparser2",
        ),
        files=ordered,
        summary=AnalysisSummary(
            files=len(ordered),
            routines=len(routines),
            loops=sum(len(routine.loops) for routine in routines),
            calls=sum(len(routine.calls) for routine in routines),
            fallback_routines=sum(
                routine.support_status is SupportStatus.REQUIRES_FALLBACK for routine in routines
            ),
            fallback_files=sum(
                item.support_status is SupportStatus.REQUIRES_FALLBACK for item in ordered
            ),
            diagnostics=sum(
                len(item.diagnostics) + sum(len(routine.diagnostics) for routine in item.routines)
                for item in ordered
            ),
            authoritative_files=sum(
                item.parser_status is ParserStatus.AUTHORITATIVE for item in ordered
            ),
            partial_files=sum(item.parser_status is ParserStatus.PARTIAL for item in ordered),
            resolved_calls=resolutions.count(CallResolution.RESOLVED),
            unresolved_calls=resolutions.count(CallResolution.UNRESOLVED),
            ambiguous_calls=resolutions.count(CallResolution.AMBIGUOUS),
        ),
        call_graph=graph,
    )
    return result, tuple(sorted(loaded_sources, key=lambda item: item.relative_path))


def analyze_project(input_path: Path, config: AnalysisConfig) -> AnalysisResult:
    """Analyze a project without executing, importing, or compiling source code."""

    result, _ = analyze_project_with_sources(input_path, config)
    return result
