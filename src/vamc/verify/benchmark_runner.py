"""Benchmark protocol runner intended only for the hardened container boundary."""

from __future__ import annotations

import argparse
import gc
import importlib
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any

from sandbox_runner import _decode, _resolve, _write  # type: ignore[import-not-found]


def _inputs(case: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
    positional = [_decode(item) for item in case.get("arguments", [])]
    keywords = {key: _decode(item) for key, item in case.get("keywords", {}).items()}
    return positional, keywords


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--module", required=True)
    parser.add_argument("--module-root", required=True)
    parser.add_argument("--routine", required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmups", type=int, required=True)
    parser.add_argument("--repeats", type=int, required=True)
    parser.add_argument("--iterations", type=int, required=True)
    arguments = parser.parse_args()
    if (
        not arguments.module_root.startswith("/")
        or ".." in Path(arguments.module_root).parts
        or not 0 <= arguments.warmups <= 100
        or not 1 <= arguments.repeats <= 100
        or not 1 <= arguments.iterations <= 100_000
    ):
        raise ValueError("invalid benchmark configuration")
    sys.path.insert(0, arguments.module_root)
    with arguments.cases.open("r", encoding="utf-8") as stream:
        document = json.load(stream)
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("benchmark requires at least one case")

    payload: dict[str, Any]
    try:
        module = importlib.import_module(arguments.module)
        routine = _resolve(module, arguments.routine)
        for _ in range(arguments.warmups):
            for case in cases:
                positional, keywords = _inputs(case)
                routine(*positional, **keywords)
        samples: list[int] = []
        for _ in range(arguments.repeats):
            elapsed = 0
            calls = 0
            gc.disable()
            try:
                for _ in range(arguments.iterations):
                    for case in cases:
                        positional, keywords = _inputs(case)
                        started = time.perf_counter_ns()
                        routine(*positional, **keywords)
                        elapsed += time.perf_counter_ns() - started
                        calls += 1
            finally:
                gc.enable()
            samples.append(elapsed // calls)
        import numba
        import numpy

        payload = {
            "environment": {
                "machine": platform.machine(),
                "numba": numba.__version__,
                "numpy": numpy.__version__,
                "platform": platform.platform(),
                "python": platform.python_version(),
            },
            "samples_ns": samples,
            "status": "benchmarked",
        }
    except Exception as error:
        payload = {"exception_type": type(error).__name__, "status": "failed"}
    _write(arguments.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
