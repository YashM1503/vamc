"""Command-line interface."""

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from vamc import __version__
from vamc.analysis.inventory import AnalysisError
from vamc.config import AnalysisConfig
from vamc.project import Project


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vamc",
        description="Evidence-first modernization for legacy scientific Fortran.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser(
        "analyze", help="build a deterministic, non-executing lexical inventory"
    )
    analyze.add_argument("path", type=Path, help="Fortran file or source directory")
    analyze.add_argument("--json", action="store_true", help="write JSON to stdout")
    analyze.add_argument("--output", type=Path, help="write the JSON report to this file")
    analyze.add_argument(
        "--force", action="store_true", help="replace an existing report without following symlinks"
    )
    analyze.add_argument("--max-file-bytes", type=int, default=2 * 1024 * 1024)
    analyze.add_argument("--max-total-bytes", type=int, default=64 * 1024 * 1024)
    analyze.add_argument("--max-files", type=int, default=10_000)
    analyze.add_argument("--max-lines-per-file", type=int, default=200_000)
    analyze.add_argument("--max-line-bytes", type=int, default=64 * 1024)
    analyze.add_argument("--max-statements-per-file", type=int, default=100_000)
    analyze.add_argument("--max-loop-nesting", type=int, default=128)
    analyze.add_argument("--include-hidden", action="store_true")
    analyze.set_defaults(handler=_run_analyze)
    return parser


def _run_analyze(args: argparse.Namespace) -> int:
    config = AnalysisConfig(
        max_file_bytes=args.max_file_bytes,
        max_total_bytes=args.max_total_bytes,
        max_files=args.max_files,
        max_lines_per_file=args.max_lines_per_file,
        max_line_bytes=args.max_line_bytes,
        max_statements_per_file=args.max_statements_per_file,
        max_loop_nesting=args.max_loop_nesting,
        include_hidden=args.include_hidden,
    )
    result = Project.from_path(args.path, config=config).analyze()
    rendered = None
    if args.output or args.json:
        rendered = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
    if args.output:
        assert rendered is not None
        _atomic_write(args.output, rendered, overwrite=args.force)
    if args.json:
        assert rendered is not None
        sys.stdout.write(rendered)
    else:
        summary = result.summary
        print(
            f"Analyzed {summary.files} file(s): {summary.routines} routine(s), "
            f"{summary.loops} loop(s), {summary.calls} call edge(s)."
        )
        if summary.fallback_routines:
            print(f"Fallback required for {summary.fallback_routines} routine(s).")
        if summary.fallback_files:
            print(f"Incomplete lexical coverage in {summary.fallback_files} file(s).")
        if args.output:
            print(f"Wrote {args.output}")
    return 0


def _atomic_write(path: Path, content: str, *, overwrite: bool) -> None:
    """Atomically replace a report without following a destination symlink."""

    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path, follow_symlinks=False)
            except FileExistsError as error:
                raise AnalysisError(f"output already exists (use --force): {path}") from error
            temporary.unlink()
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (AnalysisError, ValueError, OSError) as error:
        parser.exit(2, f"vamc: error: {error}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
