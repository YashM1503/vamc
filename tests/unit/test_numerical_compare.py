import math

import pytest

from vamc.models import NumericalPolicy
from vamc.verify.compare import compare_values, scientific_default_policy, strict_policy


def test_strict_and_scientific_profiles_are_explicit() -> None:
    strict = strict_policy()
    scientific = scientific_default_policy()

    assert strict.name == "strict"
    assert strict.relative_tolerance < scientific.relative_tolerance
    assert strict.absolute_tolerance < scientific.absolute_tolerance


def test_comparator_tracks_numeric_and_structural_failures() -> None:
    close = compare_values([1.0, {"value": 2.0}], [1.0 + 1.0e-13, {"value": 2.0}])
    different = compare_values([1.0, 2.0], [1.0, 4.0])
    structural = compare_values({"left": [1]}, {"right": [1]})

    assert close.equal
    assert close.compared_values == 2
    assert close.max_absolute_error > 0
    assert not different.equal
    assert different.max_absolute_error == 2.0
    assert not structural.equal
    assert structural.structural_mismatches == 1


def test_comparator_handles_nan_infinity_and_boolean_without_coercion() -> None:
    assert compare_values(math.nan, math.nan).equal
    assert not compare_values(math.nan, 0.0).equal
    assert compare_values(math.inf, math.inf).equal
    assert not compare_values(math.inf, -math.inf).equal
    assert not compare_values(True, 1).equal


def test_comparator_rejects_negative_tolerance() -> None:
    policy = NumericalPolicy("invalid", relative_tolerance=-1.0, absolute_tolerance=0.0)

    with pytest.raises(ValueError, match="non-negative"):
        compare_values(1.0, 1.0, policy)
