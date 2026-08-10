import json
from pathlib import Path

from vamc.cli import main
from vamc.project import Project


def test_example_analysis_is_deterministic() -> None:
    example = Path(__file__).parents[2] / "examples" / "daxpy"
    first = Project.from_path(example).analyze().to_dict()
    second = Project.from_path(example).analyze().to_dict()

    assert first == second
    assert first["summary"] == {
        "calls": 0,
        "fallback_routines": 0,
        "files": 1,
        "loops": 1,
        "routines": 1,
    }
    assert first["files"][0]["routines"][0]["symbols"] == ["a", "i", "n", "x", "y"]


def test_cli_writes_machine_readable_report(tmp_path: Path) -> None:
    example = Path(__file__).parents[2] / "examples" / "daxpy"
    output = tmp_path / "analysis.json"

    assert main(["analyze", str(example), "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema_version"] == "0.1.0"
    assert report["files"][0]["routines"][0]["name"] == "daxpy"
