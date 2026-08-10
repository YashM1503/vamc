from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from vamc.frontends.fortran import analyze_fortran_source


@settings(max_examples=100, deadline=500)
@given(st.text(alphabet=st.characters(max_codepoint=127), max_size=500))
def test_lexical_frontend_is_deterministic_and_does_not_crash(source: str) -> None:
    data = source.encode("utf-8")

    first = analyze_fortran_source(Path("fuzz.f90"), "fuzz.f90", data)
    second = analyze_fortran_source(Path("fuzz.f90"), "fuzz.f90", data)

    assert first == second
    assert all(routine.start_line <= routine.end_line for routine in first.routines)
    assert all(
        loop.start_line <= loop.end_line for routine in first.routines for loop in routine.loops
    )
