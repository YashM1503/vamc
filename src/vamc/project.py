"""Public project API."""

from pathlib import Path

from vamc.analysis.inventory import analyze_project
from vamc.config import AnalysisConfig
from vamc.models import AnalysisResult


class Project:
    """A legacy source project prepared for deterministic analysis."""

    def __init__(self, path: Path, config: AnalysisConfig) -> None:
        self.path = path
        self.config = config

    @classmethod
    def from_path(cls, path: str | Path, config: AnalysisConfig | None = None) -> "Project":
        return cls(Path(path), config or AnalysisConfig())

    def analyze(self) -> AnalysisResult:
        """Create a bounded lexical inventory without executing source code."""

        return analyze_project(self.path, self.config)
