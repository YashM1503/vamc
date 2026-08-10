"""Verified Adaptive Modernization Compiler."""

from vamc._version import __version__
from vamc.migration import MigrationResult
from vamc.models import AnalysisResult, MigrationManifest
from vamc.project import Project

__all__ = ["AnalysisResult", "MigrationManifest", "MigrationResult", "Project", "__version__"]
