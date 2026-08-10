"""Configuration and bounded-input defaults."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisConfig:
    """Limits applied while analyzing untrusted source trees."""

    max_file_bytes: int = 2 * 1024 * 1024
    max_files: int = 10_000
    include_hidden: bool = False

    def __post_init__(self) -> None:
        if self.max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        if self.max_files <= 0:
            raise ValueError("max_files must be positive")
