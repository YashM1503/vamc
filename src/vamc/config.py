"""Configuration and bounded-input defaults."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisConfig:
    """Limits applied while analyzing untrusted source trees."""

    max_file_bytes: int = 2 * 1024 * 1024
    max_total_bytes: int = 64 * 1024 * 1024
    max_files: int = 10_000
    max_lines_per_file: int = 200_000
    max_line_bytes: int = 64 * 1024
    max_statements_per_file: int = 100_000
    max_loop_nesting: int = 128
    include_hidden: bool = False

    def __post_init__(self) -> None:
        if self.max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        if self.max_total_bytes <= 0:
            raise ValueError("max_total_bytes must be positive")
        if self.max_files <= 0:
            raise ValueError("max_files must be positive")
        if self.max_lines_per_file <= 0:
            raise ValueError("max_lines_per_file must be positive")
        if self.max_line_bytes <= 0:
            raise ValueError("max_line_bytes must be positive")
        if self.max_statements_per_file <= 0:
            raise ValueError("max_statements_per_file must be positive")
        if self.max_loop_nesting <= 0:
            raise ValueError("max_loop_nesting must be positive")
