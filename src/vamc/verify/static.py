"""Static verification of migration integrity and generated Python syntax."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import stat
from pathlib import Path, PurePosixPath
from typing import Any

from vamc.analysis.inventory import AnalysisError
from vamc.migration import MigrationResult
from vamc.models import (
    CandidateBackend,
    CandidateVerification,
    ComparisonMetrics,
    NumericalPolicy,
    RoutineVerification,
    VerificationReport,
    VerificationStatus,
    VerificationSummary,
)
from vamc.verify.compare import strict_policy

_MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
_MAX_TOTAL_BYTES = 256 * 1024 * 1024


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise AnalysisError("migration manifest contains an unsafe artifact path")
    return path


def _read_anchored(root_descriptor: int, relative: PurePosixPath, limit: int) -> bytes:
    directory = os.dup(root_descriptor)
    try:
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        for component in relative.parts[:-1]:
            following = os.open(component, directory_flags, dir_fd=directory)
            os.close(directory)
            directory = following
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(relative.name, flags, dir_fd=directory)
    except OSError as error:
        raise AnalysisError(f"cannot safely read migration artifact: {relative}") from error
    finally:
        os.close(directory)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise AnalysisError(f"migration artifact is not a regular file: {relative}")
        if metadata.st_size > limit:
            raise AnalysisError(f"migration artifact exceeds size limit: {relative}")
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > limit:
            raise AnalysisError(f"migration artifact exceeds size limit: {relative}")
        return content
    finally:
        os.close(descriptor)


def _empty_metrics(equal: bool = True) -> ComparisonMetrics:
    return ComparisonMetrics(
        equal=equal,
        compared_values=0,
        max_absolute_error=0.0,
        max_relative_error=0.0,
        nan_mismatches=0,
        infinity_mismatches=0,
        structural_mismatches=0 if equal else 1,
    )


def _verify(
    manifest: dict[str, Any],
    contents: dict[str, bytes],
    policy: NumericalPolicy,
) -> VerificationReport:
    failures: list[str] = []
    declared = manifest.get("artifacts")
    if not isinstance(declared, list):
        raise AnalysisError("migration manifest has no artifact inventory")
    for item in declared:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise AnalysisError("migration manifest contains an invalid artifact entry")
        path = item["path"]
        _safe_relative(path)
        content = contents.get(path)
        if content is None:
            failures.append(f"missing artifact: {path}")
            continue
        if len(content) != item.get("size_bytes"):
            failures.append(f"size mismatch: {path}")
        if hashlib.sha256(content).hexdigest() != item.get("sha256"):
            failures.append(f"digest mismatch: {path}")
        if path.endswith(".py"):
            try:
                ast.parse(content.decode("utf-8"), filename=path)
            except (SyntaxError, UnicodeDecodeError):
                failures.append(f"invalid generated Python: {path}")

    maps_by_routine = {
        (item.get("source_file"), item.get("routine")): item
        for item in manifest.get("source_maps", [])
        if isinstance(item, dict)
    }
    routine_results: list[RoutineVerification] = []
    for item in manifest.get("routines", []):
        if not isinstance(item, dict) or not isinstance(item.get("routine"), str):
            raise AnalysisError("migration manifest contains an invalid routine entry")
        routine = item["routine"]
        if item.get("status") != "TRANSLATED":
            routine_results.append(
                RoutineVerification(
                    routine=routine,
                    status=VerificationStatus.UNAVAILABLE,
                    cases=0,
                    policy=policy,
                    metrics=_empty_metrics(),
                    diagnostics=("routine requires native fallback",),
                )
            )
            continue
        generated_file = item.get("generated_file")
        mapping = maps_by_routine.get((item.get("source_file"), routine))
        routine_failures = []
        if not isinstance(generated_file, str) or generated_file not in contents:
            routine_failures.append("generated file is missing")
        if not isinstance(mapping, dict) or mapping.get("generated_file") != generated_file:
            routine_failures.append("source map is missing or inconsistent")
        if failures:
            routine_failures.append("artifact integrity check failed")
        routine_results.append(
            RoutineVerification(
                routine=routine,
                status=(
                    VerificationStatus.FAILED
                    if routine_failures
                    else VerificationStatus.STATICALLY_CHECKED
                ),
                cases=0,
                policy=policy,
                metrics=_empty_metrics(not routine_failures),
                diagnostics=tuple(routine_failures),
            )
        )

    statuses = [item.status for item in routine_results]
    candidate_results: list[CandidateVerification] = []
    for item in manifest.get("candidates", []):
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or not isinstance(item.get("routine"), str)
            or not isinstance(item.get("backend"), str)
        ):
            raise AnalysisError("migration manifest contains an invalid candidate entry")
        generated_file = item.get("generated_file")
        candidate_failures = []
        if not isinstance(generated_file, str) or generated_file not in contents:
            candidate_failures.append("candidate file is missing")
        if failures:
            candidate_failures.append("artifact integrity check failed")
        try:
            backend = CandidateBackend(item["backend"])
        except ValueError as error:
            raise AnalysisError(
                "migration manifest contains an invalid candidate backend"
            ) from error
        candidate_results.append(
            CandidateVerification(
                candidate_id=item["id"],
                routine=item["routine"],
                backend=backend,
                status=(
                    VerificationStatus.FAILED
                    if candidate_failures
                    else VerificationStatus.STATICALLY_CHECKED
                ),
                cases=0,
                policy=policy,
                metrics=_empty_metrics(not candidate_failures),
                diagnostics=tuple(candidate_failures),
            )
        )
    candidate_statuses = [item.status for item in candidate_results]
    if VerificationStatus.FAILED in statuses or failures:
        overall = VerificationStatus.FAILED
    elif VerificationStatus.STATICALLY_CHECKED in statuses:
        overall = VerificationStatus.STATICALLY_CHECKED
    else:
        overall = VerificationStatus.UNAVAILABLE
    return VerificationReport(
        schema_version="0.1.0",
        migration_schema_version=str(manifest.get("schema_version", "UNKNOWN")),
        status=overall,
        sandbox="none (static analysis only)",
        sandbox_image=None,
        routines=tuple(routine_results),
        summary=VerificationSummary(
            routines=len(routine_results),
            statically_checked=statuses.count(VerificationStatus.STATICALLY_CHECKED),
            verified_for_test_domain=statuses.count(VerificationStatus.VERIFIED_FOR_TEST_DOMAIN),
            failed=statuses.count(VerificationStatus.FAILED),
            unavailable=statuses.count(VerificationStatus.UNAVAILABLE),
            candidates_statically_checked=candidate_statuses.count(
                VerificationStatus.STATICALLY_CHECKED
            ),
            candidates_verified=0,
            candidates_rejected=candidate_statuses.count(VerificationStatus.FAILED),
            candidates_unavailable=0,
        ),
        candidates=tuple(candidate_results),
    )


def verify_migration_result(
    migration: MigrationResult, policy: NumericalPolicy | None = None
) -> VerificationReport:
    """Verify an in-memory migration without importing or executing generated code."""

    manifest = migration.manifest.to_dict()
    contents = {item.path: item.content.encode("utf-8") for item in migration.artifacts}
    return _verify(manifest, contents, policy or strict_policy())


def verify_migration_directory(
    path: str | Path, policy: NumericalPolicy | None = None
) -> VerificationReport:
    """Safely verify artifact hashes and syntax in a materialized migration."""

    manifest, contents = _load_migration_directory(path)
    return _verify(manifest, contents, policy or strict_policy())


def _load_migration_directory(path: str | Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Load a bounded migration through a root-anchored descriptor."""

    root = Path(path).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise AnalysisError("verification input must be a non-symlink migration directory")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        root_descriptor = os.open(root, flags)
    except OSError as error:
        raise AnalysisError("cannot safely open migration directory") from error
    try:
        raw_manifest = _read_anchored(
            root_descriptor, PurePosixPath("modernization.json"), _MAX_MANIFEST_BYTES
        )
        try:
            manifest = json.loads(raw_manifest)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AnalysisError("modernization.json is not valid UTF-8 JSON") from error
        if not isinstance(manifest, dict):
            raise AnalysisError("modernization.json must contain a JSON object")
        declared = manifest.get("artifacts")
        if not isinstance(declared, list):
            raise AnalysisError("migration manifest has no artifact inventory")
        contents: dict[str, bytes] = {}
        total_bytes = 0
        for item in declared:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise AnalysisError("migration manifest contains an invalid artifact entry")
            artifact_path = item["path"]
            relative = _safe_relative(artifact_path)
            content = _read_anchored(root_descriptor, relative, _MAX_ARTIFACT_BYTES)
            total_bytes += len(content)
            if total_bytes > _MAX_TOTAL_BYTES:
                raise AnalysisError("migration artifact inventory exceeds total size limit")
            contents[artifact_path] = content
    finally:
        os.close(root_descriptor)
    return manifest, contents
