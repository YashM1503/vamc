from pathlib import Path

import pytest

from vamc.analysis.inventory import AnalysisError
from vamc.benchmark.runner import (
    _environment,
    _read_json,
    _samples,
    benchmark_migration_directory,
)
from vamc.report.render import _decode_object, _join_strings, _render_html, _validate_analysis


def test_report_json_boundary_rejects_invalid_and_non_object_documents() -> None:
    with pytest.raises(AnalysisError, match="valid bounded JSON"):
        _decode_object(b"{", "report.json")

    with pytest.raises(AnalysisError, match="JSON object"):
        _decode_object(b"[]", "report.json")


@pytest.mark.parametrize(
    "document, message",
    [
        ({"schema_version": "0.2.0", "files": []}, "schema"),
        (
            {"schema_version": "0.3.0", "files": [{"routines": "invalid"}]},
            "routine inventory",
        ),
        (
            {
                "schema_version": "0.3.0",
                "files": [{"routines": [{"loops": "invalid"}]}],
            },
            "loop inventory",
        ),
    ],
)
def test_report_analysis_boundary_rejects_malformed_inventories(
    document: dict[str, object], message: str
) -> None:
    with pytest.raises(AnalysisError, match=message):
        _validate_analysis(document)


def test_report_string_list_boundary_marks_malformed_records() -> None:
    assert _join_strings(["valid", 3]) == "invalid record"


def test_report_renderer_skips_malformed_nested_records() -> None:
    rendered = _render_html(
        {
            "analysis": {"files": ["invalid", {"routines": ["invalid"]}]},
            "benchmark": None,
            "migration": {
                "candidates": [
                    "invalid",
                    {
                        "backend": "numpy",
                        "id": "scale.numpy",
                        "routine": "scale",
                        "status": "PROPOSED",
                    },
                ],
                "routines": [],
                "source_maps": [],
                "summary": {},
            },
            "migration_sha256": "<unsafe>",
            "verification": {
                "candidates": ["invalid"],
                "routines": [{"diagnostics": [], "metrics": "invalid", "routine": "scale"}],
                "sandbox": None,
                "sandbox_image": None,
                "status": "STATICALLY_CHECKED",
            },
            "verification_sha256": "0" * 64,
        }
    )

    assert "&lt;unsafe&gt;" in rendered
    assert "scale.numpy" in rendered
    assert "<unsafe>" not in rendered


def test_benchmark_evidence_reader_rejects_unsafe_or_malformed_inputs(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)

    with pytest.raises(AnalysisError, match="symbolic link"):
        _read_json(link)
    with pytest.raises(AnalysisError, match="safely open"):
        _read_json(tmp_path / "missing.json")
    with pytest.raises(AnalysisError, match="not regular"):
        _read_json(tmp_path)

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(AnalysisError, match="valid bounded JSON"):
        _read_json(invalid)

    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    with pytest.raises(AnalysisError, match="JSON object"):
        _read_json(array)


def test_benchmark_result_boundary_rejects_invalid_environment_and_samples() -> None:
    assert _environment({"environment": {"python": "3.14"}}) is None
    assert _samples(None, 2) is None
    assert _samples({"status": "benchmarked", "samples_ns": [1, -1]}, 2) is None


def test_benchmark_configuration_boundary_rejects_out_of_range_values() -> None:
    with pytest.raises(ValueError, match="out of bounds"):
        benchmark_migration_directory(
            "migration", "cases", "verification", image="image", repeats=0
        )
