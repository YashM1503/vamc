from pathlib import Path

from vamc.frontends.fortran import analyze_fortran_source
from vamc.models import EvidenceStatus, LoopPattern, ParallelStatus, SupportStatus


def test_inventory_extracts_routine_symbols_and_map_loop() -> None:
    source = (
        b"subroutine scale(n, x)\n"
        b"  integer :: n, i\n"
        b"  real :: x(n)\n"
        b"  do i = 1, n\n"
        b"    x(i) = 2.0 * x(i)\n"
        b"  end do\n"
        b"end subroutine scale\n"
    )
    digest = analyze_fortran_source(Path("scale.f90"), "scale.f90", source)

    routine = digest.routines[0]
    assert routine.name == "scale"
    assert routine.arguments == ("n", "x")
    assert routine.symbols == ("i", "n", "x")
    assert routine.loops[0].pattern is LoopPattern.MAP
    assert routine.loops[0].parallel_status is ParallelStatus.UNRESOLVED


def test_recurrence_fails_closed() -> None:
    source = (
        b"subroutine prefix(n, x)\n"
        b"  integer :: n, i\n"
        b"  real :: x(n)\n"
        b"  do i = 2, n\n"
        b"    x(i) = x(i-1) + x(i)\n"
        b"  end do\n"
        b"end subroutine prefix\n"
    )
    digest = analyze_fortran_source(Path("prefix.f90"), "prefix.f90", source)

    loop = digest.routines[0].loops[0]
    assert loop.pattern is LoopPattern.RECURRENCE
    assert loop.parallel_status is ParallelStatus.SERIAL


def test_process_execution_requires_fallback() -> None:
    source = b"""subroutine hostile()\n  call system('whoami')\nend subroutine hostile\n"""
    digest = analyze_fortran_source(Path("hostile.f90"), "hostile.f90", source)

    routine = digest.routines[0]
    assert routine.side_effects.process is EvidenceStatus.OBSERVED
    assert routine.support_status is SupportStatus.REQUIRES_FALLBACK
    assert routine.unsupported_constructs == (
        "process_execution",
        "unresolved_external_call",
    )


def test_fixed_form_continuation_is_joined() -> None:
    source = b"""      SUBROUTINE ADDONE(X)\n      REAL X\n      X = X\n     1 + 1.0\n      END\n"""
    digest = analyze_fortran_source(Path("addone.f"), "addone.f", source)

    assert len(digest.routines) == 1
    assert digest.routines[0].name == "addone"


def test_semicolon_statements_and_typed_function_are_recognized() -> None:
    source = b"real(kind=8) function value(x); real(kind=8) :: x; value = x; end function value\n"
    digest = analyze_fortran_source(Path("value.f90"), "value.f90", source)

    assert len(digest.routines) == 1
    assert digest.routines[0].name == "value"
    assert digest.routines[0].symbols == ("x",)
    assert digest.routines[0].support_status is SupportStatus.LEXICALLY_SCANNED


def test_literals_do_not_create_calls_or_unsupported_constructs() -> None:
    source = (
        b'subroutine words()\n  print *, "call foo; equivalence; system"\nend subroutine words\n'
    )
    routine = analyze_fortran_source(Path("words.f90"), "words.f90", source).routines[0]

    assert routine.calls == ()
    assert routine.unsupported_constructs == ()
    assert routine.side_effects.stdout is EvidenceStatus.OBSERVED
    assert routine.side_effects.process is EvidenceStatus.UNKNOWN


def test_standard_computed_go_to_requires_fallback() -> None:
    source = b"subroutine jump(i)\n go to (10, 20), i\n 10 continue\n 20 continue\nend\n"
    routine = analyze_fortran_source(Path("jump.f90"), "jump.f90", source).routines[0]

    assert "computed_goto" in routine.unsupported_constructs
    assert routine.support_status is SupportStatus.REQUIRES_FALLBACK


def test_fixed_form_labeled_do_closes_at_terminal_statement() -> None:
    source = (
        b"      SUBROUTINE WORK(N,X)\n"
        b"      INTEGER I,N\n"
        b"      REAL X(N)\n"
        b"      DO 100 I=1,N\n"
        b"      X(I)=X(I)+1\n"
        b"  100 CONTINUE\n"
        b"      CALL AFTER\n"
        b"      END\n"
    )
    routine = analyze_fortran_source(Path("work.f"), "work.f", source).routines[0]

    assert routine.loops[0].end_line == 6
    assert routine.loops[0].pattern is LoopPattern.MAP


def test_malformed_scopes_fail_closed() -> None:
    source = b"subroutine broken(n,x)\ninteger::n,i\nreal::x(n)\ndo i=1,n\nx(i)=1\n"
    routine = analyze_fortran_source(Path("broken.f90"), "broken.f90", source).routines[0]

    assert routine.support_status is SupportStatus.REQUIRES_FALLBACK
    assert routine.unsupported_constructs == ("unterminated_do", "unterminated_routine")
    assert {item.code for item in routine.diagnostics} == {
        "unterminated_do",
        "unterminated_routine",
    }


def test_stencil_and_recurrence_use_exact_array_names() -> None:
    source = (
        b"subroutine neighbors(n,a,data,y)\ninteger::n,i\nreal::a(n),data(n),y(n)\n"
        b"do i=2,n\na(i)=data(i-1)\nend do\n"
        b"do i=2,n\ny(i)=y(i-1)\nend do\nend\n"
    )
    loops = analyze_fortran_source(Path("neighbors.f90"), "neighbors.f90", source).routines[0].loops

    assert [loop.id for loop in loops] == ["L1", "L2"]
    assert loops[0].pattern is LoopPattern.STENCIL
    assert loops[1].pattern is LoopPattern.RECURRENCE


def test_declaration_regex_does_not_invent_symbols_from_assignments() -> None:
    source = b"subroutine names()\ninteger_value = 1\nrealistic = 2\nend\n"
    routine = analyze_fortran_source(Path("names.f90"), "names.f90", source).routines[0]

    assert routine.symbols == ()


def test_interfaces_are_diagnostic_not_implemented_routines() -> None:
    source = (
        b"module api\ninterface\nsubroutine declared(x)\nreal::x\nend subroutine\n"
        b"end interface\nend module api\n"
    )
    digest = analyze_fortran_source(Path("api.f90"), "api.f90", source)

    assert digest.routines == ()
    assert digest.support_status is SupportStatus.REQUIRES_FALLBACK
    assert {item.code for item in digest.diagnostics} >= {
        "interface_not_scanned",
        "no_supported_program_unit",
    }


def test_nested_loop_ids_follow_source_order() -> None:
    source = (
        b"subroutine nested(n,a)\ninteger::n,i,j\nreal::a(n,n)\n"
        b"do i=1,n\ndo j=1,n\na(i,j)=0\nend do\nend do\nend\n"
    )
    loops = analyze_fortran_source(Path("nested.f90"), "nested.f90", source).routines[0].loops

    assert [(loop.id, loop.start_line) for loop in loops] == [("L1", 4), ("L2", 5)]
