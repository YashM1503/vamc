"""Deterministic numerical comparison with explicit error accounting."""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import Any

from vamc.models import ComparisonMetrics, NumericalPolicy


def strict_policy() -> NumericalPolicy:
    return NumericalPolicy(
        name="strict",
        relative_tolerance=1.0e-12,
        absolute_tolerance=1.0e-14,
    )


def scientific_default_policy() -> NumericalPolicy:
    return NumericalPolicy(
        name="scientific_default",
        relative_tolerance=1.0e-8,
        absolute_tolerance=1.0e-10,
    )


@dataclass
class _Accumulator:
    equal: bool = True
    compared_values: int = 0
    max_absolute_error: float = 0.0
    max_relative_error: float = 0.0
    nan_mismatches: int = 0
    infinity_mismatches: int = 0
    structural_mismatches: int = 0

    def metrics(self) -> ComparisonMetrics:
        return ComparisonMetrics(
            equal=self.equal,
            compared_values=self.compared_values,
            max_absolute_error=self.max_absolute_error,
            max_relative_error=self.max_relative_error,
            nan_mismatches=self.nan_mismatches,
            infinity_mismatches=self.infinity_mismatches,
            structural_mismatches=self.structural_mismatches,
        )


def _numeric(expected: Real, actual: Real, policy: NumericalPolicy, result: _Accumulator) -> None:
    result.compared_values += 1
    expected_float = float(expected)
    actual_float = float(actual)
    if math.isnan(expected_float) or math.isnan(actual_float):
        both_nan = math.isnan(expected_float) and math.isnan(actual_float)
        if not both_nan or not policy.equal_nan:
            result.equal = False
            result.nan_mismatches += 1
        return
    if math.isinf(expected_float) or math.isinf(actual_float):
        if expected_float != actual_float:
            result.equal = False
            result.infinity_mismatches += 1
        return
    absolute_error = abs(expected_float - actual_float)
    denominator = abs(expected_float)
    relative_error = (
        absolute_error / denominator
        if denominator
        else (0.0 if absolute_error == 0.0 else math.inf)
    )
    result.max_absolute_error = max(result.max_absolute_error, absolute_error)
    result.max_relative_error = max(result.max_relative_error, relative_error)
    if not math.isclose(
        expected_float,
        actual_float,
        rel_tol=policy.relative_tolerance,
        abs_tol=policy.absolute_tolerance,
    ):
        result.equal = False


def _compare(expected: Any, actual: Any, policy: NumericalPolicy, result: _Accumulator) -> None:
    if isinstance(expected, bool) or isinstance(actual, bool):
        result.compared_values += 1
        if type(expected) is not type(actual) or expected != actual:
            result.equal = False
            result.structural_mismatches += 1
        return
    if isinstance(expected, Real) and isinstance(actual, Real):
        _numeric(expected, actual, policy, result)
        return
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            result.equal = False
            result.structural_mismatches += 1
            return
        for expected_item, actual_item in zip(expected, actual, strict=True):
            _compare(expected_item, actual_item, policy, result)
        return
    if isinstance(expected, dict) and isinstance(actual, dict):
        if expected.keys() != actual.keys():
            result.equal = False
            result.structural_mismatches += 1
            return
        for key in sorted(expected):
            _compare(expected[key], actual[key], policy, result)
        return
    result.compared_values += 1
    if type(expected) is not type(actual) or expected != actual:
        result.equal = False
        result.structural_mismatches += 1


def compare_values(
    expected: Any,
    actual: Any,
    policy: NumericalPolicy | None = None,
) -> ComparisonMetrics:
    """Compare decoded JSON-compatible values under a named numerical policy."""

    selected = policy or scientific_default_policy()
    if selected.relative_tolerance < 0 or selected.absolute_tolerance < 0:
        raise ValueError("numerical tolerances must be non-negative")
    result = _Accumulator()
    _compare(expected, actual, selected, result)
    return result.metrics()
