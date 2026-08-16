import json
from pathlib import Path

import pytest

from vamc.analysis.inventory import AnalysisError
from vamc.cli import main
from vamc.project import Project
from vamc.report import build_report


def _migration(tmp_path: Path) -> Path:
    source = tmp_path / "evil<script>.f90"
    source.write_text(
        """subroutine scale(n, a, x)
  integer, intent(in) :: n
  real(kind=8), intent(in) :: a
  real(kind=8), intent(inout) :: x(n)
  integer :: i
  do i = 1, n
    x(i) = a * x(i)
  end do
end subroutine scale
""",
        encoding="utf-8",
    )
    return Project.from_path(source).migrate().write(tmp_path / "modern")


def test_report_is_self_contained_escaped_and_deterministic(tmp_path: Path) -> None:
    migration = _migration(tmp_path)

    first = build_report(migration)
    second = build_report(migration)

    assert first.json_text == second.json_text
    assert first.html_text == second.html_text
    assert "evil&lt;script&gt;.f90" in first.html_text
    assert "evil<script>.f90" not in first.html_text
    assert "Content-Security-Policy" in first.html_text
    assert "https://" not in first.html_text
    assert first.document["verification"]["status"] == "STATICALLY_CHECKED"


def test_report_cli_writes_both_formats_without_clobbering(tmp_path: Path) -> None:
    migration = _migration(tmp_path)
    output = tmp_path / "evidence"

    assert main(["report", str(migration), "--output-dir", str(output)]) == 0
    assert (
        json.loads((output / "modernization-report.json").read_text(encoding="utf-8"))[
            "schema_version"
        ]
        == "0.1.0"
    )
    assert (
        (output / "modernization-report.html")
        .read_text(encoding="utf-8")
        .startswith("<!doctype html>")
    )

    with pytest.raises(SystemExit) as caught:
        main(["report", str(migration), "--output-dir", str(output)])
    assert caught.value.code == 2


def test_report_rejects_verification_for_another_migration(tmp_path: Path) -> None:
    migration = _migration(tmp_path)
    verification = tmp_path / "verification.json"
    verification.write_text(
        json.dumps(
            {
                "schema_version": "0.2.0",
                "migration_sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(AnalysisError, match="does not match"):
        build_report(migration, verification_path=verification)
