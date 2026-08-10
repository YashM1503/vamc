"""Public project API."""

from pathlib import Path

from vamc.analysis.inventory import analyze_project
from vamc.config import AnalysisConfig
from vamc.migration import MigrationResult, migrate_project
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
        """Create a bounded semantic inventory without executing source code."""

        return analyze_project(self.path, self.config)

    def migrate(
        self,
        *,
        target: str = "python",
        package_name: str = "vamc_modernized",
        optimize: bool = False,
        parallel: str = "off",
    ) -> MigrationResult:
        """Generate an in-memory, fail-closed migration for explicit review and writing."""

        return migrate_project(
            self.path,
            self.config,
            target=target,
            package_name=package_name,
            optimize=optimize,
            parallel=parallel,
        )
