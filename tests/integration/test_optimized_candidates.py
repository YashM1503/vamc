import importlib
import sys
from pathlib import Path

import numpy as np

from vamc.models import CandidateBackend, CandidateStatus, VerificationStatus
from vamc.project import Project


def test_daxpy_optimization_candidates_are_gated_and_executable(tmp_path: Path) -> None:
    example = Path(__file__).parents[2] / "examples" / "daxpy"
    migration = Project.from_path(example).migrate(optimize=True, parallel="auto")

    assert {item.backend for item in migration.manifest.candidates} == {
        CandidateBackend.NUMPY,
        CandidateBackend.NUMBA_SERIAL,
        CandidateBackend.NUMBA_PARALLEL,
    }
    assert all(
        item.status is CandidateStatus.REQUIRES_VERIFICATION
        for item in migration.manifest.candidates
    )
    static = migration.verify()
    assert static.summary.candidates_statically_checked == 3
    assert all(item.status is VerificationStatus.STATICALLY_CHECKED for item in static.candidates)

    output = migration.write(tmp_path / "modern")
    sys.path.insert(0, str(output / "src"))
    try:
        for candidate in migration.manifest.candidates:
            module_name = ".".join(Path(candidate.generated_file).with_suffix("").parts[1:])
            function = importlib.import_module(module_name).daxpy
            values = np.array([10.0, 20.0, 30.0])
            function(3, 2.0, np.array([1.0, 2.0, 3.0]), values)
            assert values.tolist() == [12.0, 24.0, 36.0]
    finally:
        sys.path.pop(0)
        for name in tuple(sys.modules):
            if name == "vamc_modernized" or name.startswith("vamc_modernized."):
                sys.modules.pop(name, None)


def test_parallel_off_never_generates_prange_candidate() -> None:
    example = Path(__file__).parents[2] / "examples" / "daxpy"

    migration = Project.from_path(example).migrate(optimize=True, parallel="off")

    assert CandidateBackend.NUMBA_PARALLEL not in {
        item.backend for item in migration.manifest.candidates
    }
