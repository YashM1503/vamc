from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _exchange(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    root = Path(__file__).resolve().parents[2]
    launcher = root / "plugins" / "vamc-agent" / "scripts" / "launch-mcp"
    environment = os.environ.copy()
    environment["VAMC_PYTHON"] = sys.executable
    input_text = "".join(json.dumps(message) + "\n" for message in messages)
    result = subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        [str(launcher)],
        input=input_text,
        capture_output=True,
        check=True,
        env=environment,
        text=True,
        timeout=30,
    )
    assert result.stderr == ""
    return [json.loads(line) for line in result.stdout.splitlines()]


def test_mcp_server_lists_and_runs_read_only_analysis() -> None:
    root = Path(__file__).resolve().parents[2]
    responses = _exchange(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "vamc_analyze",
                    "arguments": {"path": str(root / "examples" / "daxpy")},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "vamc_analyze",
                    "arguments": {
                        "path": str(root / "examples" / "daxpy"),
                        "execute": True,
                    },
                },
            },
        ]
    )

    assert [response["id"] for response in responses] == [1, 2, 3, 4]
    tool_names = {tool["name"] for tool in responses[1]["result"]["tools"]}
    assert tool_names == {
        "vamc_analyze",
        "vamc_build_report",
        "vamc_verify_static",
    }
    tool_result = responses[2]["result"]
    assert tool_result["isError"] is False
    assert tool_result["structuredContent"]["summary"]["files"] == 1
    assert responses[3]["result"]["isError"] is True
    assert "unknown arguments" in responses[3]["result"]["structuredContent"]["error"]
