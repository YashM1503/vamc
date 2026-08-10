from pathlib import Path

from vamc.frontends.fortran import analyze_fortran_source
from vamc.models import LoopPattern, ParallelStatus, SupportStatus


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
    assert routine.side_effects.process
    assert routine.support_status is SupportStatus.REQUIRES_FALLBACK
    assert routine.unsupported_constructs == ("process_execution",)


def test_fixed_form_continuation_is_joined() -> None:
    source = b"""      SUBROUTINE ADDONE(X)\n      REAL X\n      X = X\n     1 + 1.0\n      END\n"""
    digest = analyze_fortran_source(Path("addone.f"), "addone.f", source)

    assert len(digest.routines) == 1
    assert digest.routines[0].name == "addone"
