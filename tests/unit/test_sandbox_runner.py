from typing import Any

from vamc.verify.sandbox_runner import _f2py_arguments


class _F2PYRoutine:
    __doc__ = "daxpy(a,x,y,[n])"

    def __call__(self, *arguments: Any) -> None:
        del arguments


def test_f2py_argument_adapter_uses_wrapper_order() -> None:
    values = [3, 2.0, [1.0, 2.0, 3.0], [10.0, 20.0, 30.0]]

    positional, keywords = _f2py_arguments(
        _F2PYRoutine(),
        "daxpy",
        values,
        {},
        ["n", "a", "x", "y"],
    )

    assert positional == [values[1], values[2], values[3], values[0]]
    assert keywords == {}
