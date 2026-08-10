from pathlib import Path

from vamc.models import LoopPattern, ParallelStatus
from vamc.project import Project


def test_dependency_analysis_fails_closed_across_labeled_patterns(tmp_path: Path) -> None:
    samples = {
        "map.f90": """subroutine map(n,a,b)
integer,intent(in)::n
real,intent(in)::a(n)
real,intent(out)::b(n)
integer::i
do i=1,n
  b(i)=2*a(i)
end do
end
""",
        "recurrence.f90": """subroutine recurrence(n,a)
integer,intent(in)::n
real,intent(inout)::a(n)
integer::i
do i=2,n
  a(i)=a(i-1)+1
end do
end
""",
        "reduction.f90": """real function total(n,a)
integer,intent(in)::n
real,intent(in)::a(n)
integer::i
total=0
do i=1,n
  total=total+a(i)
end do
end
""",
        "scatter.f90": """subroutine scatter(n,idx,a,b)
integer,intent(in)::n,idx(n)
real,intent(in)::a(n)
real,intent(out)::b(n)
integer::i
do i=1,n
  b(idx(i))=a(i)
end do
end
""",
        "stencil.f90": """subroutine stencil(n,a,b)
integer,intent(in)::n
real,intent(in)::a(n)
real,intent(out)::b(n)
integer::i
do i=2,n-1
  b(i)=a(i-1)+a(i)+a(i+1)
end do
end
""",
    }
    for name, source in samples.items():
        (tmp_path / name).write_text(source, encoding="utf-8")

    analysis = Project.from_path(tmp_path).analyze()
    loops = {item.path: item.routines[0].loops[0] for item in analysis.files}

    assert (loops["map.f90"].pattern, loops["map.f90"].parallel_status) == (
        LoopPattern.MAP,
        ParallelStatus.CONDITIONALLY_SAFE,
    )
    assert (loops["recurrence.f90"].pattern, loops["recurrence.f90"].parallel_status) == (
        LoopPattern.RECURRENCE,
        ParallelStatus.SERIAL,
    )
    assert (loops["reduction.f90"].pattern, loops["reduction.f90"].parallel_status) == (
        LoopPattern.REDUCTION,
        ParallelStatus.CONDITIONALLY_SAFE,
    )
    assert loops["scatter.f90"].parallel_status is ParallelStatus.SERIAL
    assert (loops["stencil.f90"].pattern, loops["stencil.f90"].parallel_status) == (
        LoopPattern.STENCIL,
        ParallelStatus.CONDITIONALLY_SAFE,
    )
