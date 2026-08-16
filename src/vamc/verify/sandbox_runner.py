"""Minimal JSON protocol runner intended only for the hardened container boundary."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


def _decode(value: Any) -> Any:
    if isinstance(value, dict) and value.get("kind") == "array":
        import numpy as np

        return np.array(value.get("value"), dtype=value.get("dtype"), order="F")
    if isinstance(value, dict) and value.get("kind") == "scalar":
        return value.get("value")
    if isinstance(value, list):
        return [_decode(item) for item in value]
    if isinstance(value, dict):
        return {key: _decode(item) for key, item in value.items()}
    return value


def _encode(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _encode(item) for key, item in value.items()}
    if hasattr(value, "tolist"):
        return _encode(value.tolist())
    if hasattr(value, "item"):
        return _encode(value.item())
    raise TypeError(f"unsupported result type: {type(value).__name__}")


def _resolve(module: Any, entrypoint: str) -> Any:
    target = module
    for component in entrypoint.split("."):
        if not component.isidentifier() or component.startswith("_"):
            raise ValueError("invalid routine entrypoint")
        target = getattr(target, component)
    if not callable(target):
        raise TypeError("routine entrypoint is not callable")
    return target


def _f2py_arguments(
    routine: Any,
    entrypoint: str,
    positional: list[Any],
    keywords: dict[str, Any],
    argument_names: list[str],
) -> tuple[list[Any], dict[str, Any]]:
    """Map source-order inputs to the order documented by an F2PY wrapper."""

    if len(positional) > len(argument_names) or any(
        not isinstance(name, str) or not name.isidentifier() for name in argument_names
    ):
        raise ValueError("invalid authoritative argument-name mapping")
    values = dict(zip(argument_names, positional, strict=False))
    for name, value in keywords.items():
        if name in values:
            raise TypeError("argument supplied both positionally and by keyword")
        values[name] = value
    documentation = getattr(routine, "__doc__", None)
    if not isinstance(documentation, str):
        raise TypeError("F2PY wrapper has no inspectable signature")
    marker = f"{entrypoint.split('.')[-1]}("
    start = documentation.lower().find(marker.lower())
    if start < 0:
        raise TypeError("F2PY wrapper signature is unavailable")
    start += len(marker)
    end = documentation.find(")", start)
    if end < 0:
        raise TypeError("F2PY wrapper signature is malformed")
    names = []
    for raw in documentation[start:end].split(","):
        name = raw.strip().strip("[]").split("=", 1)[0].strip()
        if name:
            if not name.isidentifier():
                raise TypeError("F2PY wrapper signature is malformed")
            names.append(name.lower())
    lowered_values = {name.lower(): value for name, value in values.items()}
    return [lowered_values[name] for name in names if name in lowered_values], {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=".vamc-result-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, allow_nan=True, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--module", required=True)
    parser.add_argument("--module-root", action="append", default=[])
    parser.add_argument("--routine", required=True)
    parser.add_argument("--f2py", action="store_true")
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    for module_root in reversed(arguments.module_root):
        if not module_root.startswith("/") or ".." in Path(module_root).parts:
            raise ValueError("invalid module root")
        sys.path.insert(0, module_root)
    with arguments.case.open("r", encoding="utf-8") as stream:
        case = json.load(stream)
    positional = [_decode(item) for item in case.get("arguments", [])]
    keywords = {key: _decode(item) for key, item in case.get("keywords", {}).items()}
    payload: dict[str, Any]
    try:
        module = importlib.import_module(arguments.module)
        routine = _resolve(module, arguments.routine)
        call_positional = positional
        call_keywords = keywords
        if arguments.f2py:
            names = case.get("argument_names")
            if not isinstance(names, list):
                raise ValueError("F2PY call requires authoritative argument names")
            call_positional, call_keywords = _f2py_arguments(
                routine,
                arguments.routine,
                positional,
                keywords,
                names,
            )
        returned = routine(*call_positional, **call_keywords)
        payload = {
            "arguments": _encode(positional),
            "keywords": _encode(keywords),
            "return": _encode(returned),
            "status": "returned",
        }
    except Exception as error:
        payload = {
            "exception_type": type(error).__name__,
            "status": "raised",
        }
    _write(arguments.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
