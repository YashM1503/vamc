"""Migration orchestration and safe artifact materialization."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from vamc._version import __version__
from vamc.analysis.inventory import AnalysisError, analyze_project_with_sources
from vamc.backends.optimized import generate_optimized_candidates
from vamc.backends.python import generate_python
from vamc.config import AnalysisConfig
from vamc.models import (
    AnalysisResult,
    ArtifactDigest,
    GeneratedArtifact,
    MigrationManifest,
    MigrationSummary,
    TranslationStatus,
)

if TYPE_CHECKING:
    from vamc.models import VerificationReport


def _json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _artifact(path: str, content: str) -> GeneratedArtifact:
    import hashlib

    encoded = content.encode("utf-8")
    return GeneratedArtifact(path=path, content=content, sha256=hashlib.sha256(encoded).hexdigest())


def _validate_artifact_path(path: str) -> PurePosixPath:
    candidate = PurePosixPath(path)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise AnalysisError("generated artifact contains an unsafe path")
    return candidate


@dataclass(frozen=True)
class MigrationResult:
    """An immutable migration prepared in memory until ``write`` is requested."""

    analysis: AnalysisResult
    manifest: MigrationManifest
    artifacts: tuple[GeneratedArtifact, ...]

    def verify(self) -> VerificationReport:
        """Perform non-executing integrity and generated-syntax verification."""

        from vamc.verify.static import verify_migration_result

        return verify_migration_result(self)

    def write(self, output: str | Path) -> Path:
        """Atomically create a new output directory without overwriting user data."""

        destination = Path(output).expanduser()
        if destination.is_symlink() or destination.exists():
            raise AnalysisError(f"migration output already exists: {destination}")
        parent = destination.parent
        parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.vamc-", dir=parent))
        try:
            for artifact in self.artifacts:
                relative = _validate_artifact_path(artifact.path)
                target = temporary.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("x", encoding="utf-8", newline="\n") as stream:
                    stream.write(artifact.content)
                    stream.flush()
                    os.fsync(stream.fileno())
            os.rename(temporary, destination)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return destination


def migrate_project(
    input_path: Path,
    config: AnalysisConfig,
    *,
    target: str = "python",
    package_name: str = "vamc_modernized",
    optimize: bool = False,
    parallel: str = "off",
) -> MigrationResult:
    """Build a fail-closed serial Python migration from a bounded source snapshot."""

    if target != "python":
        raise ValueError("only the 'python' migration target is currently supported")
    if parallel not in {"off", "auto"}:
        raise ValueError("parallel must be 'off' or 'auto'")
    if not package_name.isidentifier() or package_name.startswith("_"):
        raise ValueError("package_name must be a public Python identifier")

    analysis, loaded = analyze_project_with_sources(input_path, config)
    sources = tuple((item.relative_path, item.text) for item in loaded)
    generated = generate_python(analysis, sources, package_name=package_name)
    optimized = (
        generate_optimized_candidates(
            analysis,
            sources,
            generated.routines,
            package_name=package_name,
            parallel=parallel,
        )
        if optimize or parallel == "auto"
        else None
    )
    translated = sum(item.status is TranslationStatus.TRANSLATED for item in generated.routines)
    fallback = len(generated.routines) - translated

    artifacts = list(generated.artifacts)
    candidates = optimized.candidates if optimized else ()
    if optimized:
        artifacts.extend(optimized.artifacts)
    artifacts.extend(
        (
            _artifact(
                "pyproject.toml",
                "\n".join(
                    (
                        "[build-system]",
                        'requires = ["setuptools>=68"]',
                        'build-backend = "setuptools.build_meta"',
                        "",
                        "[project]",
                        'name = "vamc-modernized"',
                        'version = "0.0.0"',
                        'description = "Serial Python generated by VAMC"',
                        'requires-python = ">=3.11"',
                        "",
                        "[tool.setuptools.packages.find]",
                        'where = ["src"]',
                        "",
                        "[project.optional-dependencies]",
                        'optimized = ["numpy>=2.4,<2.5", "numba>=0.66,<0.67"]',
                        "",
                    )
                ),
            ),
            _artifact("analysis.json", _json(analysis.to_dict())),
            _artifact(
                "fallback-registry.json",
                _json(
                    {
                        "routines": [
                            {
                                "source_file": item.source_file,
                                "routine": item.routine,
                                "reasons": list(item.fallback_reasons),
                            }
                            for item in generated.routines
                            if item.status is TranslationStatus.FALLBACK_REQUIRED
                        ],
                        "schema_version": "0.1.0",
                    }
                ),
            ),
            _artifact(
                "README_MODERNIZATION.md",
                "\n".join(
                    (
                        "# VAMC modernization output",
                        "",
                        "This package contains deterministic serial Python translated from the",
                        "captured Fortran snapshot.",
                        "",
                        "A routine appears in `fallback-registry.json` whenever VAMC could not",
                        "preserve its semantics.",
                        "Fallback entries are not silently exposed as translated Python.",
                        "",
                        "Install for local review with `python -m pip install -e .`.",
                        "Review `modernization.json`, `analysis.json`, and source maps before",
                        "production use. Generated translations are not called verified until",
                        "differential verification records pass.",
                        "Optimization candidates are isolated under `_candidates` and are never",
                        "selected while their manifest status is `REQUIRES_VERIFICATION`.",
                        "",
                    )
                ),
            ),
            _artifact(".vamc-generated", f"vamc {__version__}\n"),
        )
    )
    for source_path, source in sources:
        _validate_artifact_path(source_path)
        artifacts.append(_artifact(f"legacy/{source_path}", source))

    ordered = tuple(sorted(artifacts, key=lambda item: item.path))
    digests = tuple(
        ArtifactDigest(
            path=item.path,
            sha256=item.sha256,
            size_bytes=len(item.content.encode("utf-8")),
        )
        for item in ordered
    )
    manifest = MigrationManifest(
        schema_version="0.1.0",
        generator_version=__version__,
        source_root=analysis.source_root,
        target=target,
        package_name=package_name,
        analysis_schema_version=analysis.schema_version,
        artifacts=digests,
        candidates=candidates,
        source_maps=generated.source_maps,
        routines=generated.routines,
        summary=MigrationSummary(
            files=analysis.summary.files,
            routines=analysis.summary.routines,
            translated_routines=translated,
            fallback_routines=fallback,
        ),
    )
    manifest_artifact = _artifact("modernization.json", _json(manifest.to_dict()))
    return MigrationResult(
        analysis=analysis,
        manifest=manifest,
        artifacts=tuple(sorted((*ordered, manifest_artifact), key=lambda item: item.path)),
    )
