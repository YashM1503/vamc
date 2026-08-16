"""Verified Adaptive Modernization Compiler."""

from vamc._version import __version__
from vamc.fallback import build_fallback
from vamc.migration import MigrationResult
from vamc.models import (
    AnalysisResult,
    BenchmarkReport,
    FallbackBuildReport,
    MigrationManifest,
    VerificationReport,
)
from vamc.project import Project
from vamc.report import ReportBundle, build_report

__all__ = [
    "AnalysisResult",
    "BenchmarkReport",
    "FallbackBuildReport",
    "MigrationManifest",
    "MigrationResult",
    "Project",
    "ReportBundle",
    "VerificationReport",
    "__version__",
    "build_fallback",
    "build_report",
]
