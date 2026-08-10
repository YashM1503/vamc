"""Command-line interface."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Optional

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
        "analyze", help="build a deterministic, non-executing semantic inventory"
    )
    analyze.add_argument("path", type=Path, help="Fortran file or source directory")
    analyze.add_argument("--json", action="store_true", help="write JSON to stdout")
    analyze.add_argument("--output", type=Path, help="write the JSON report to this file")
    analyze.add_argument("--max-file-bytes", type=int, default=2 * 1024 * 1024)
    analyze.set_defaults(handler=_run_analyze)
    return parser


def _run_analyze(args: argparse.Namespace) -> int:
    config = AnalysisConfig(max_file_bytes=args.max_file_bytes)
    result = Project.from_path(args.path, config=config).analyze()
    rendered = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if args.json:
        sys.stdout.write(rendered)
    else:
        summary = result.summary
        print(
            f"Analyzed {summary.files} file(s): {summary.routines} routine(s), "
            f"{summary.loops} loop(s), {summary.calls} call edge(s)."
        )
        if summary.fallback_routines:
            print(f"Fallback required for {summary.fallback_routines} routine(s).")
        if args.output:
            print(f"Wrote {args.output}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (AnalysisError, ValueError, OSError) as error:
        parser.exit(2, f"vamc: error: {error}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
