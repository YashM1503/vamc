import json
from pathlib import Path

import pytest

from vamc.cli import main
from vamc.project import Project


def test_example_analysis_is_deterministic() -> None:
    example = Path(__file__).parents[2] / "examples" / "daxpy"
    first = Project.from_path(example).analyze().to_dict()
    second = Project.from_path(example).analyze().to_dict()

    assert first == second
    assert first["provenance"]["frontend"] == "vamc.psyir-fortran.v1"
    assert first["provenance"]["authoritative_frontend"].startswith("PSyclone ")
    assert first["summary"] == {
        "ambiguous_calls": 0,
        "authoritative_files": 1,
        "calls": 0,
        "diagnostics": 0,
        "fallback_files": 0,
        "fallback_routines": 0,
        "files": 1,
        "loops": 1,
        "partial_files": 0,
        "resolved_calls": 0,
        "routines": 1,
        "unresolved_calls": 0,
    }
    assert first["files"][0]["routines"][0]["symbols"] == ["a", "i", "n", "x", "y"]
    assert first["files"][0]["parser_status"] == "AUTHORITATIVE"
    assert first["files"][0]["routines"][0]["support_status"] == "AUTHORITATIVELY_PARSED"


def test_cli_writes_machine_readable_report(tmp_path: Path) -> None:
    example = Path(__file__).parents[2] / "examples" / "daxpy"
    output = tmp_path / "analysis.json"

    assert main(["analyze", str(example), "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema_version"] == "0.3.0"
    assert report["files"][0]["routines"][0]["name"] == "daxpy"


def test_cli_does_not_clobber_existing_report_without_force(tmp_path: Path) -> None:
    example = Path(__file__).parents[2] / "examples" / "daxpy"
    output = tmp_path / "analysis.json"
    output.write_text("keep", encoding="utf-8")

    with pytest.raises(SystemExit) as caught:
        main(["analyze", str(example), "--output", str(output)])
    assert caught.value.code == 2
    assert output.read_text(encoding="utf-8") == "keep"

    assert main(["analyze", str(example), "--output", str(output), "--force"]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == "0.3.0"


def test_cli_output_does_not_follow_symlink(tmp_path: Path) -> None:
    example = Path(__file__).parents[2] / "examples" / "daxpy"
    target = tmp_path / "target"
    target.write_text("keep", encoding="utf-8")
    output = tmp_path / "analysis.json"
    try:
        output.symlink_to(target)
    except OSError:
        return

    with pytest.raises(SystemExit) as caught:
        main(["analyze", str(example), "--output", str(output)])
    assert caught.value.code == 2
    assert target.read_text(encoding="utf-8") == "keep"

    assert main(["analyze", str(example), "--output", str(output), "--force"]) == 0
    assert target.read_text(encoding="utf-8") == "keep"
    assert not output.is_symlink()
    assert output.stat().st_mode & 0o777 == 0o600
