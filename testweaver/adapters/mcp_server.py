"""Minimal newline JSON-RPC mapping for one QwenPaw MCP tool."""
from __future__ import annotations

import json
import sys
from typing import Any

from .config import AdapterConfig
from .executor import NATIVE_EXECUTION_TOOL, NativeExecutionError, execute_native_worker
from .native_worker import NativeWorkerAdapterError, NativeWorkerAssignment
from .result import Provenance, ResultContractError


_OPAQUE = {"type": "string", "minLength": 1, "maxLength": 2000, "pattern": r"^[^\s\x00-\x1f]+$"}
_REFERENCE = {"oneOf": [{"type": "object", "required": ["source", "name"], "additionalProperties": False, "properties": {"source": {"enum": ["env"]}, "name": {"type": "string", "minLength": 1, "pattern": r"^[A-Z_][A-Z0-9_]*$"}}}, {"type": "object", "required": ["source", "path"], "additionalProperties": False, "properties": {"source": {"enum": ["file"]}, "path": {"type": "string", "minLength": 1, "pattern": r"^/(?!.*(?:^|/)\.\.(?:/|$))[^\s\x00-\x1f]+$"}}}]}
_ASSIGNMENT = {"type": "object", "required": ["project_id", "task_id", "room_id", "worker_id", "leader_id", "task_ref", "read_only"], "additionalProperties": False, "properties": {**{field: _OPAQUE for field in ("project_id", "task_id", "room_id", "worker_id", "leader_id", "task_ref")}, "read_only": {"enum": [True]}}}
_ROUTE = {"type": "object", "required": ["provider", "endpoint", "model", "credential", "wire_api"], "additionalProperties": False, "properties": {"provider": {"type": "string", "minLength": 1, "maxLength": 64, "pattern": r"^[a-z0-9][a-z0-9._-]{0,63}$"}, "endpoint": _REFERENCE, "model": _REFERENCE, "credential": _REFERENCE, "wire_api": {"enum": ["chat", "responses"]}}}
_LIMITS = {"type": "object", "required": ["timeout_seconds", "max_model_decisions", "max_tool_calls", "max_cost_units"], "additionalProperties": False, "properties": {"timeout_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 86400}, "max_model_decisions": {"type": "integer", "minimum": 0}, "max_tool_calls": {"type": "integer", "minimum": 0}, "max_cost_units": {"type": "number", "minimum": 0}}}
_CONFIG = {"type": "object", "required": ["adapter_kind", "route", "limits"], "additionalProperties": False, "properties": {"adapter_kind": {"enum": ["dsh", "codex-cli"]}, "route": _ROUTE, "limits": _LIMITS}}
_PROVENANCE = {"type": "object", "required": ["source", "source_revision", "method"], "additionalProperties": False, "properties": {"source": {"type": "string", "minLength": 1, "maxLength": 200, "pattern": r"^[^\s\x00-\x1f]+$"}, "source_revision": {"type": "string", "minLength": 1, "maxLength": 200, "pattern": r"^[^\s\x00-\x1f]+$"}, "method": {"type": "string", "minLength": 1, "maxLength": 2000, "pattern": r"^[^\x00-\x1f]*$"}}}

TOOL = {
    "name": NATIVE_EXECUTION_TOOL,
    "description": "Run one fixed external Worker process after a native assignment.",
    "inputSchema": {
        "type": "object",
        "required": ["assignment", "config", "provenance", "prompt"],
        "additionalProperties": False,
        "properties": {"assignment": _ASSIGNMENT, "config": _CONFIG, "provenance": _PROVENANCE, "prompt": {"type": "string", "minLength": 1, "maxLength": 131072, "pattern": r"^[^\x00]*$"}},
    },
}


def _text(value: Any) -> dict[str, Any]: return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}


def list_tools() -> list[dict[str, Any]]: return [TOOL]


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    if name != NATIVE_EXECUTION_TOOL: return _text({"ok": False, "error": "unknown_tool"})
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
    if request_id is None and isinstance(method, str) and method.startswith("notifications/"): return None
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
        if response is not None: print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
