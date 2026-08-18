"""Read-only Model Context Protocol server for VAMC."""

from __future__ import annotations

import json
import math
import sys
from typing import Any

from vamc._version import __version__
from vamc.project import Project
from vamc.report import build_report
from vamc.verify.static import verify_migration_directory

SERVER_NAME = "vamc"
DEFAULT_PROTOCOL_VERSION = "2024-11-05"
MAX_MESSAGE_BYTES = 1024 * 1024
MAX_TOOL_RESULT_BYTES = 8 * 1024 * 1024


TOOLS: list[dict[str, Any]] = [
    {
        "name": "vamc_analyze",
        "description": (
            "Analyze a Fortran source file or directory without compiling or executing it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Fortran file or directory."}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "vamc_verify_static",
        "description": (
            "Verify migration paths, hashes, manifests, and Python syntax without "
            "importing or executing generated code."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "migration_path": {
                    "type": "string",
                    "description": "VAMC migration output directory.",
                }
            },
            "required": ["migration_path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "vamc_build_report",
        "description": (
            "Build a deterministic VAMC report from existing migration and evidence "
            "artifacts without running native code."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "migration_path": {
                    "type": "string",
                    "description": "VAMC migration output directory.",
                },
                "verification_path": {
                    "type": "string",
                    "description": "Optional verification JSON artifact.",
                },
                "benchmark_path": {
                    "type": "string",
                    "description": "Optional benchmark JSON artifact.",
                },
            },
            "required": ["migration_path"],
            "additionalProperties": False,
        },
    },
]


def _required_string(arguments: dict[str, Any], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _optional_string(arguments: dict[str, Any], name: str) -> str | None:
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string when provided")
    return value


def _reject_unknown(arguments: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        raise ValueError(f"unknown arguments: {', '.join(unknown)}")


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            return "NaN"
        return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _tool_result(payload: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    safe_payload = _json_safe(payload)
    rendered = json.dumps(safe_payload, indent=2, sort_keys=True)
    if len(rendered.encode("utf-8")) > MAX_TOOL_RESULT_BYTES:
        safe_payload = {"error": "Tool result exceeds the 8 MiB MCP response limit"}
        rendered = json.dumps(safe_payload, indent=2, sort_keys=True)
        is_error = True
    return {
        "content": [
            {
                "type": "text",
                "text": rendered,
            }
        ],
        "structuredContent": safe_payload,
        "isError": is_error,
    }


def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "vamc_analyze":
        _reject_unknown(arguments, {"path"})
        source_path = _required_string(arguments, "path")
        return _tool_result(Project.from_path(source_path).analyze().to_dict())

    if name == "vamc_verify_static":
        _reject_unknown(arguments, {"migration_path"})
        migration_path = _required_string(arguments, "migration_path")
        return _tool_result(verify_migration_directory(migration_path).to_dict())

    if name == "vamc_build_report":
        _reject_unknown(arguments, {"migration_path", "verification_path", "benchmark_path"})
        migration_path = _required_string(arguments, "migration_path")
        verification_path = _optional_string(arguments, "verification_path")
        benchmark_path = _optional_string(arguments, "benchmark_path")
        report = build_report(
            migration_path,
            verification_path=verification_path,
            benchmark_path=benchmark_path,
        )
        return _tool_result(report.document)

    raise ValueError(f"Unknown tool: {name}")


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def handle_message(message: Any) -> dict[str, Any] | None:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _rpc_error(None, -32600, "Invalid Request")

    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params", {})

    if isinstance(method, str) and method.startswith("notifications/"):
        return None
    if not isinstance(method, str):
        return _rpc_error(request_id, -32600, "Invalid Request")
    if not isinstance(params, dict):
        return _rpc_error(request_id, -32602, "Invalid params")

    result: dict[str, Any]
    if method == "initialize":
        requested_version = params.get("protocolVersion", DEFAULT_PROTOCOL_VERSION)
        if not isinstance(requested_version, str):
            requested_version = DEFAULT_PROTOCOL_VERSION
        result = {
            "protocolVersion": requested_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return _rpc_error(request_id, -32602, "Invalid params")
        try:
            result = _call_tool(name, arguments)
        except Exception as exc:
            result = _tool_result({"error": f"{type(exc).__name__}: {exc}"}, is_error=True)
    else:
        return _rpc_error(request_id, -32601, "Method not found")

    if "id" not in message:
        return None
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _write_message(message: dict[str, Any]) -> None:
    encoded = json.dumps(message, separators=(",", ":"), allow_nan=False)
    sys.stdout.write(encoded + "\n")
    sys.stdout.flush()


def main() -> int:
    while True:
        raw_line = sys.stdin.buffer.readline(MAX_MESSAGE_BYTES + 1)
        if not raw_line:
            return 0
        if len(raw_line) > MAX_MESSAGE_BYTES:
            _write_message(_rpc_error(None, -32700, "Message exceeds 1 MiB limit"))
            return 2
        if not raw_line.strip():
            continue
        try:
            message = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            _write_message(_rpc_error(None, -32700, "Parse error"))
            continue
        response = handle_message(message)
        if response is not None:
            _write_message(response)


if __name__ == "__main__":
    raise SystemExit(main())
