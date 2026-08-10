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
from vamc.verify import scientific_default_policy, strict_policy, verify_migration_directory
from vamc.verify.native import verify_native_directory


def _add_analysis_limits(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-file-bytes", type=int, default=2 * 1024 * 1024)
    parser.add_argument("--max-total-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--max-files", type=int, default=10_000)
    parser.add_argument("--max-lines-per-file", type=int, default=200_000)
    parser.add_argument("--max-line-bytes", type=int, default=64 * 1024)
    parser.add_argument("--max-statements-per-file", type=int, default=100_000)
    parser.add_argument("--max-loop-nesting", type=int, default=128)
    parser.add_argument("--max-ir-nodes-per-file", type=int, default=250_000)
    parser.add_argument("--include-hidden", action="store_true")


def _config(args: argparse.Namespace) -> AnalysisConfig:
    return AnalysisConfig(
        max_file_bytes=args.max_file_bytes,
        max_total_bytes=args.max_total_bytes,
        max_files=args.max_files,
        max_lines_per_file=args.max_lines_per_file,
        max_line_bytes=args.max_line_bytes,
        max_statements_per_file=args.max_statements_per_file,
        max_loop_nesting=args.max_loop_nesting,
        max_ir_nodes_per_file=args.max_ir_nodes_per_file,
        include_hidden=args.include_hidden,
    )


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
    analyze.add_argument(
        "--force", action="store_true", help="replace an existing report without following symlinks"
    )
    _add_analysis_limits(analyze)
    analyze.set_defaults(handler=_run_analyze)

    migrate = subparsers.add_parser(
        "migrate", help="generate reviewed serial Python and an explicit fallback registry"
    )
    migrate.add_argument("path", type=Path, help="Fortran file or source directory")
    migrate.add_argument("--target", choices=("python",), default="python")
    migrate.add_argument("--output", type=Path, required=True)
    migrate.add_argument("--package-name", default="vamc_modernized")
    migrate.add_argument(
        "--optimize", action="store_true", help="generate unaccepted NumPy/Numba candidates"
    )
    migrate.add_argument(
        "--parallel",
        choices=("off", "auto"),
        default="off",
        help="generate prange candidates only when dependency analysis permits",
    )
    migrate.add_argument("--json", action="store_true", help="write the manifest to stdout")
    migrate.add_argument(
        "--fail-on-unsupported",
        action="store_true",
        help="do not write output if any routine requires fallback",
    )
    _add_analysis_limits(migrate)
    migrate.set_defaults(handler=_run_migrate)

    verify = subparsers.add_parser(
        "verify", help="verify migration integrity and generated Python syntax without execution"
    )
    verify.add_argument("path", type=Path, help="materialized migration directory")
    verify.add_argument(
        "--verification-profile",
        choices=("strict", "scientific_default"),
        default="strict",
    )
    verify.add_argument("--json", action="store_true", help="write the report to stdout")
    verify.add_argument("--output", type=Path, help="write verification JSON to this file")
    verify.add_argument(
        "--cases",
        type=Path,
        help="run differential cases against a native F2PY oracle inside Docker",
    )
    verify.add_argument(
        "--sandbox-image",
        help="digest-pinned Docker image containing Python, NumPy, Meson, and gfortran",
    )
    verify.add_argument(
        "--force", action="store_true", help="replace an existing report without following symlinks"
    )
    verify.set_defaults(handler=_run_verify)
    return parser


def _run_analyze(args: argparse.Namespace) -> int:
    result = Project.from_path(args.path, config=_config(args)).analyze()
    rendered = None
    if args.output or args.json:
        rendered = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
    if args.output:
        if rendered is None:
            raise RuntimeError("report rendering invariant failed")
        _atomic_write(args.output, rendered, overwrite=args.force)
    if args.json:
        if rendered is None:
            raise RuntimeError("report rendering invariant failed")
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


def _run_migrate(args: argparse.Namespace) -> int:
    migration = Project.from_path(args.path, config=_config(args)).migrate(
        target=args.target,
        package_name=args.package_name,
        optimize=args.optimize,
        parallel=args.parallel,
    )
    summary = migration.manifest.summary
    if args.fail_on_unsupported and summary.fallback_routines:
        raise AnalysisError(
            f"{summary.fallback_routines} routine(s) require fallback; output was not written"
        )
    destination = migration.write(args.output)
    if args.json:
        sys.stdout.write(json.dumps(migration.manifest.to_dict(), indent=2, sort_keys=True) + "\n")
    else:
        print(
            f"Translated {summary.translated_routines}/{summary.routines} routine(s); "
            f"{summary.fallback_routines} require fallback."
        )
        print(f"Wrote {destination}")
    return 0


def _run_verify(args: argparse.Namespace) -> int:
    policy = (
        strict_policy() if args.verification_profile == "strict" else scientific_default_policy()
    )
    if bool(args.cases) != bool(args.sandbox_image):
        raise ValueError("--cases and --sandbox-image must be supplied together")
    report = (
        verify_native_directory(
            args.path,
            args.cases,
            image=args.sandbox_image,
            policy=policy,
        )
        if args.cases
        else verify_migration_directory(args.path, policy=policy)
    )
    rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"
    if args.output:
        _atomic_write(args.output, rendered, overwrite=args.force)
    if args.json:
        sys.stdout.write(rendered)
    else:
        print(
            f"Verification status: {report.status.value}; "
            f"{report.summary.statically_checked} routine(s) statically checked, "
            f"{report.summary.verified_for_test_domain} verified for the test domain, "
            f"{report.summary.unavailable} unavailable."
        )
        if args.output:
            print(f"Wrote {args.output}")
    if report.summary.failed:
        return 1
    if args.cases and report.summary.unavailable:
        return 3
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
