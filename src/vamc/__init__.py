"""Verified Adaptive Modernization Compiler."""

from vamc._version import __version__
from vamc.models import AnalysisResult
from vamc.project import Project

__all__ = ["AnalysisResult", "Project", "__version__"]
