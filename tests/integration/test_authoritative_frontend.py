from pathlib import Path

import pytest

from vamc.analysis.inventory import AnalysisError
from vamc.config import AnalysisConfig
from vamc.models import (
    ArgumentAccess,
    CallResolution,
    DataType,
    ParserStatus,
    SupportStatus,
)
from vamc.project import Project


def test_multifile_calls_resolve_and_clear_lexical_fallback(tmp_path: Path) -> None:
    (tmp_path / "caller.f90").write_text(
        """subroutine caller(n, x)
integer, intent(in) :: n
real, intent(inout) :: x(n)
call callee(n, x)
end subroutine caller
""",
        encoding="utf-8",
    )
    (tmp_path / "callee.f90").write_text(
        """subroutine callee(n, x)
integer, intent(in) :: n
real, intent(inout) :: x(n)
x(1) = x(1) + n
end subroutine callee
""",
        encoding="utf-8",
    )

    result = Project.from_path(tmp_path).analyze()

    assert result.summary.authoritative_files == 2
    assert result.summary.resolved_calls == 1
    assert result.summary.unresolved_calls == 0
    assert result.call_graph[0].resolution is CallResolution.RESOLVED
    assert result.call_graph[0].target_file == "callee.f90"
    caller = next(
        routine
        for file_digest in result.files
        for routine in file_digest.routines
        if routine.name == "caller"
    )
    assert caller.support_status is SupportStatus.AUTHORITATIVELY_PARSED
    assert "unresolved_external_call" not in caller.unsupported_constructs


def test_duplicate_routine_names_make_call_resolution_ambiguous(tmp_path: Path) -> None:
    (tmp_path / "caller.f90").write_text(
        "subroutine caller()\ncall duplicate()\nend\n", encoding="utf-8"
    )
    for name in ("one.f90", "two.f90"):
        (tmp_path / name).write_text("subroutine duplicate()\nend\n", encoding="utf-8")

    result = Project.from_path(tmp_path).analyze()

    assert result.summary.ambiguous_calls == 1
    assert result.call_graph[0].resolution is CallResolution.AMBIGUOUS
    caller = result.files[0].routines[0]
    assert caller.support_status is SupportStatus.REQUIRES_FALLBACK
    assert "unresolved_external_call" in caller.unsupported_constructs


def test_symbol_types_shapes_and_intents_come_from_psyir(tmp_path: Path) -> None:
    source = tmp_path / "types.f90"
    source.write_text(
        """subroutine types(n, source, target)
integer, intent(in) :: n
real(kind=8), intent(in) :: source(n)
real(kind=8), intent(out) :: target(:)
target(1) = source(1)
end subroutine types
""",
        encoding="utf-8",
    )

    routine = Project.from_path(source).analyze().files[0].routines[0]
    symbols = {symbol.name: symbol for symbol in routine.symbol_details}

    assert symbols["n"].data_type is DataType.INTEGER
    assert symbols["n"].argument_access is ArgumentAccess.READ
    assert symbols["source"].precision == "8"
    assert symbols["source"].shape == ("1:n",)
    assert symbols["target"].argument_access is ArgumentAccess.WRITE
    assert symbols["target"].shape == (":",)


def test_authoritative_parse_failure_is_explicit_fallback(tmp_path: Path) -> None:
    source = tmp_path / "broken.f90"
    source.write_text("subroutine broken(\nthis is not fortran\n", encoding="utf-8")

    result = Project.from_path(source).analyze()

    assert result.files[0].parser_status is ParserStatus.FAILED
    assert result.files[0].support_status is SupportStatus.REQUIRES_FALLBACK
    assert {item.code for item in result.files[0].diagnostics} >= {"authoritative_parse_failed"}


def test_psyir_codeblocks_are_partial_and_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "output.f90"
    source.write_text("subroutine output(x)\nreal :: x\nprint *, x\nend\n", encoding="utf-8")

    result = Project.from_path(source).analyze()

    assert result.files[0].parser_status is ParserStatus.PARTIAL
    assert result.files[0].support_status is SupportStatus.REQUIRES_FALLBACK
    assert "psyir_codeblock" in result.files[0].routines[0].unsupported_constructs


def test_psyir_node_limit_is_enforced(tmp_path: Path) -> None:
    source = tmp_path / "small.f90"
    source.write_text("program small\ninteger :: i\ni = 1\nend\n", encoding="utf-8")

    with pytest.raises(AnalysisError, match="PSyIR node count exceeds"):
        Project.from_path(source, AnalysisConfig(max_ir_nodes_per_file=1)).analyze()
