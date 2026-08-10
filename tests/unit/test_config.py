import pytest

from vamc.config import AnalysisConfig


@pytest.mark.parametrize(
    "field",
    [
        "max_file_bytes",
        "max_total_bytes",
        "max_files",
        "max_lines_per_file",
        "max_line_bytes",
        "max_statements_per_file",
        "max_loop_nesting",
    ],
)
def test_analysis_limits_must_be_positive(field: str) -> None:
    with pytest.raises(ValueError, match=rf"{field} must be positive"):
        AnalysisConfig(**{field: 0})  # type: ignore[arg-type]
