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
from vamc.benchmark import benchmark_migration_directory
from vamc.config import AnalysisConfig
from vamc.fallback import build_fallback
from vamc.models import FallbackBuildStatus
from vamc.project import Project
from vamc.report import build_report
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

    benchmark = subparsers.add_parser(
        "benchmark", help="benchmark only candidates verified for the exact case set"
    )
    benchmark.add_argument("path", type=Path, help="materialized migration directory")
    benchmark.add_argument("--verification", type=Path, required=True)
    benchmark.add_argument("--cases", type=Path, required=True)
    benchmark.add_argument("--sandbox-image", required=True)
    benchmark.add_argument("--warmups", type=int, default=2)
    benchmark.add_argument("--repeats", type=int, default=7)
    benchmark.add_argument("--iterations", type=int, default=10)
    benchmark.add_argument("--json", action="store_true", help="write the report to stdout")
    benchmark.add_argument("--output", type=Path, help="write benchmark JSON to this file")
    benchmark.add_argument(
        "--force", action="store_true", help="replace an existing report without following symlinks"
    )
    benchmark.set_defaults(handler=_run_benchmark)

    report = subparsers.add_parser(
        "report", help="render validated migration evidence as JSON and self-contained HTML"
    )
    report.add_argument("path", type=Path, help="materialized migration directory")
    report.add_argument("--verification", type=Path)
    report.add_argument("--benchmark", type=Path)
    report.add_argument(
        "--output-dir",
        type=Path,
        help="destination directory (default: PATH/reports)",
    )
    report.add_argument("--json", action="store_true", help="also write report JSON to stdout")
    report.add_argument(
        "--force",
        action="store_true",
        help="replace existing report files without following symlinks",
    )
    report.set_defaults(handler=_run_report)

    fallback = subparsers.add_parser(
        "build-fallback", help="compile retained Fortran in Docker into a reviewed bridge"
    )
    fallback.add_argument("path", type=Path, help="materialized migration directory")
    fallback.add_argument("--output", type=Path, required=True)
    fallback.add_argument("--sandbox-image", required=True)
    fallback.add_argument("--json", action="store_true", help="write the build record to stdout")
    fallback.set_defaults(handler=_run_build_fallback)
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


def _run_benchmark(args: argparse.Namespace) -> int:
    report = benchmark_migration_directory(
        args.path,
        args.cases,
        args.verification,
        image=args.sandbox_image,
        warmups=args.warmups,
        repeats=args.repeats,
        iterations=args.iterations,
    )
    rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"
    if args.output:
        _atomic_write(args.output, rendered, overwrite=args.force)
    if args.json:
        sys.stdout.write(rendered)
    else:
        print(
            f"Benchmarked {report.summary.benchmarked_candidates}/"
            f"{report.summary.eligible_candidates} verified candidate(s)."
        )
        for selection in report.selections:
            print(
                f"Selected {selection.candidate_id} for {selection.routine}: "
                f"{selection.speedup_over_serial:.3f}x serial."
            )
        if args.output:
            print(f"Wrote {args.output}")
    return 3 if report.summary.unavailable_candidates else 0


def _run_report(args: argparse.Namespace) -> int:
    bundle = build_report(
        args.path,
        verification_path=args.verification,
        benchmark_path=args.benchmark,
    )
    output_directory = args.output_dir or args.path / "reports"
    json_path = output_directory / "modernization-report.json"
    html_path = output_directory / "modernization-report.html"
    for destination in (json_path, html_path):
        if not args.force and (destination.exists() or destination.is_symlink()):
            raise AnalysisError(f"output already exists (use --force): {destination}")
    _atomic_write(json_path, bundle.json_text, overwrite=args.force)
    _atomic_write(html_path, bundle.html_text, overwrite=args.force)
    if args.json:
        sys.stdout.write(bundle.json_text)
    else:
        print(f"Wrote {json_path}")
        print(f"Wrote {html_path}")
    return 0


def _run_build_fallback(args: argparse.Namespace) -> int:
    report = build_fallback(
        args.path,
        args.output,
        image=args.sandbox_image,
    )
    if args.json:
        sys.stdout.write(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n")
    else:
        print(f"Fallback build status: {report.status.value}")
        if report.status is FallbackBuildStatus.BUILT:
            print(f"Wrote {args.output}")
        for diagnostic in report.diagnostics:
            print(diagnostic)
    if report.status is FallbackBuildStatus.FAILED:
        return 1
    if report.status is FallbackBuildStatus.UNAVAILABLE:
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
