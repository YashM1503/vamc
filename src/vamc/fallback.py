"""Container-only native fallback bridge builds."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from vamc.analysis.inventory import AnalysisError
from vamc.models import FallbackBuildReport, FallbackBuildStatus
from vamc.runtime.sandbox import DockerSandbox, SandboxMount
from vamc.verify.static import (
    _load_migration_directory,
    manifest_digest,
    verify_migration_directory,
)

_FORTRAN_SUFFIXES = {".f", ".f03", ".f08", ".f77", ".f90", ".f95", ".for", ".ftn"}
_MAX_EXTENSION_BYTES = 256 * 1024 * 1024
_MODULE_NAME = "_vamc_legacy"


def _report(
    manifest: dict[str, Any],
    image: str,
    status: FallbackBuildStatus,
    diagnostic: str,
    *,
    artifact: str | None = None,
    content: bytes | None = None,
) -> FallbackBuildReport:
    return FallbackBuildReport(
        schema_version="0.1.0",
        migration_sha256=manifest_digest(manifest),
        sandbox_image=image,
        module_name=_MODULE_NAME,
        status=status,
        artifact=artifact,
        artifact_sha256=hashlib.sha256(content).hexdigest() if content is not None else None,
        artifact_size_bytes=len(content) if content is not None else None,
        diagnostics=(diagnostic,) if diagnostic else (),
    )


def _read_extension(path: Path) -> bytes:
    if path.is_symlink():
        raise AnalysisError("fallback compiler produced a symbolic link")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_EXTENSION_BYTES:
            raise AnalysisError("fallback extension is not regular or exceeds its size limit")
        chunks: list[bytes] = []
        remaining = _MAX_EXTENSION_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > _MAX_EXTENSION_BYTES:
            raise AnalysisError("fallback extension exceeds its size limit")
        return content
    finally:
        os.close(descriptor)


def _materialize(output: Path, artifact: str, content: bytes, report: FallbackBuildReport) -> None:
    if output.exists() or output.is_symlink():
        raise AnalysisError(f"fallback output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.vamc-", dir=output.parent))
    try:
        with (temporary / artifact).open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        with (temporary / "fallback-build.json").open("x", encoding="utf-8") as stream:
            json.dump(report.to_dict(), stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.rename(temporary, output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def build_fallback(
    migration_path: str | Path,
    output_path: str | Path,
    *,
    image: str,
    sandbox: DockerSandbox | None = None,
) -> FallbackBuildReport:
    """Compile retained Fortran into a separately reviewable F2PY extension."""

    modern = Path(migration_path).expanduser()
    static = verify_migration_directory(modern)
    if static.summary.failed:
        raise AnalysisError("fallback build refused because migration integrity failed")
    manifest, _ = _load_migration_directory(modern)
    fallback_routines = [
        item
        for item in manifest.get("routines", [])
        if isinstance(item, dict) and item.get("status") == "FALLBACK_REQUIRED"
    ]
    if not fallback_routines:
        raise AnalysisError("migration has no routines requiring native fallback")
    source_paths = sorted(
        PurePosixPath(item["path"]).relative_to("legacy").as_posix()
        for item in manifest.get("artifacts", [])
        if isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and PurePosixPath(item["path"]).parts[0] == "legacy"
        and PurePosixPath(item["path"]).suffix.lower() in _FORTRAN_SUFFIXES
    )
    if not source_paths:
        raise AnalysisError("migration has no captured Fortran source for fallback")
    destination = Path(output_path).expanduser()
    if destination.exists() or destination.is_symlink():
        raise AnalysisError(f"fallback output already exists: {destination}")
    selected_sandbox = sandbox or DockerSandbox(image)
    if not selected_sandbox.probe().succeeded:
        return _report(
            manifest,
            image,
            FallbackBuildStatus.UNAVAILABLE,
            "Docker engine is unavailable; native fallback was not built",
        )
    legacy = modern / "legacy"
    with tempfile.TemporaryDirectory(prefix="vamc-fallback-build-") as build_name:
        build_directory = Path(build_name)
        result = selected_sandbox.run(
            (
                "env",
                "TMPDIR=/output",
                "python",
                "-m",
                "numpy.f2py",
                "-c",
                "--backend",
                "meson",
                "-m",
                _MODULE_NAME,
                *(f"/input/{path}" for path in source_paths),
            ),
            mounts=(
                SandboxMount(legacy, "/input", True),
                SandboxMount(build_directory, "/output", False),
            ),
            working_directory="/output",
        )
        if not result.succeeded:
            return _report(
                manifest,
                image,
                FallbackBuildStatus.FAILED,
                "F2PY fallback compilation failed inside the sandbox",
            )
        extensions = [
            item
            for item in build_directory.iterdir()
            if item.name.startswith(f"{_MODULE_NAME}.") and item.suffix in {".so", ".pyd"}
        ]
        if len(extensions) != 1:
            return _report(
                manifest,
                image,
                FallbackBuildStatus.FAILED,
                "F2PY fallback compilation did not produce exactly one extension",
            )
        extension = extensions[0]
        content = _read_extension(extension)
        report = _report(
            manifest,
            image,
            FallbackBuildStatus.BUILT,
            "",
            artifact=extension.name,
            content=content,
        )
        _materialize(destination, extension.name, content, report)
        return report


__all__ = ["build_fallback"]
