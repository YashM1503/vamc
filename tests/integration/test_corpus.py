import json
from pathlib import Path

from vamc.project import Project
from vamc.verify.native import load_cases


def test_public_corpus_analyzes_migrates_and_has_valid_cases() -> None:
    root = Path(__file__).parents[2]
    manifest = json.loads((root / "corpus" / "manifest.json").read_text(encoding="utf-8"))

    for item in manifest["projects"]:
        project_path = root / item["path"]
        analysis = Project.from_path(project_path).analyze()
        migration = Project.from_path(project_path).migrate(optimize=True, parallel="auto")
        cases = load_cases(project_path / "cases.json")

        assert analysis.summary.routines == item["expected_routines"]
        assert migration.manifest.summary.routines == item["expected_routines"]
        assert cases
