"""Minimal newline JSON-RPC mapping for one QwenPaw MCP tool."""
from __future__ import annotations

import json
import sys
from typing import Any

from .config import AdapterConfig
from .executor import NATIVE_EXECUTION_TOOL, NativeExecutionError, execute_native_worker
from .native_worker import NativeWorkerAdapterError, NativeWorkerAssignment
from .result import Provenance, ResultContractError

TOOL = {
    "name": NATIVE_EXECUTION_TOOL,
    "description": "Run one fixed external Worker process after a native assignment.",
    "inputSchema": {
        "type": "object",
        "required": ["assignment", "config", "provenance", "prompt"],
        "additionalProperties": False,
        "properties": {"assignment": {"type": "object"}, "config": {"type": "object"}, "provenance": {"type": "object"}, "prompt": {"type": "string", "maxLength": 131072}},
    },
}


def _text(value: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}


def list_tools() -> list[dict[str, Any]]:
    return [TOOL]


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    if name != NATIVE_EXECUTION_TOOL:
        return _text({"ok": False, "error": "unknown_tool"})
    try:
        args = arguments or {}
        if set(args) != {"assignment", "config", "provenance", "prompt"}:
            raise NativeExecutionError("tool arguments must be assignment, config, provenance, prompt")
        result, execution = execute_native_worker(
            NativeWorkerAssignment.from_mapping(args["assignment"]),
            AdapterConfig.from_mapping(args["config"]),
            Provenance.from_mapping(args["provenance"]),
            args["prompt"],
        )
        return _text({"ok": True, "result": result.as_dict(), "execution": execution})
    except (NativeExecutionError, NativeWorkerAdapterError, ResultContractError, OSError, ValueError, TypeError) as exc:
        return _text({"ok": False, "error": str(exc)})


def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    method, request_id = request.get("method"), request.get("id")
    if request_id is None and isinstance(method, str) and method.startswith("notifications/"):
        return None
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "serverInfo": {"name": "testweaver-native-external", "version": "0.1.0"}, "capabilities": {"tools": {}}}
    elif method == "tools/list":
        result = {"tools": list_tools()}
    elif method == "tools/call":
        params = request.get("params") if isinstance(request.get("params"), dict) else {}
        result = call_tool(str(params.get("name", "")), params.get("arguments") or {})
    else:
        result = _text({"ok": False, "error": "unknown_method"})
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise TypeError
            response = handle_request(request)
        except (json.JSONDecodeError, TypeError):
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
