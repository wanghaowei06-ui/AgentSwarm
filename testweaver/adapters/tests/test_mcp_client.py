"""Focused stdio JSON-RPC client/server checks; no provider is invoked."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from testweaver.adapters.mcp_client import StdioJsonRpcClient, StdioJsonRpcTimeout


REPO_ROOT = Path(__file__).resolve().parents[3]


_SERVER_WRAPPER = r'''
import testweaver.adapters.mcp_server as server


class _Result:
    def as_dict(self):
        return {"status": "completed", "test_only": True}


def _fake_execute(*args):
    return _Result(), {"test_only": True}


server.execute_native_worker = _fake_execute
raise SystemExit(server.main())
'''


def _call_arguments() -> dict[str, object]:
    return {
        "assignment": {
            "project_id": "project-ref",
            "task_id": "task-ref",
            "room_id": "!room-ref:example.invalid",
            "worker_id": "worker-ref",
            "leader_id": "leader-ref",
            "task_ref": "task-spec-ref",
            "read_only": True,
        },
        "config": {
            "adapter_kind": "dsh",
            "route": {
                "provider": "aliyun-bailian",
                "endpoint": {"source": "env", "name": "TESTWEAVER_BAILIAN_ENDPOINT"},
                "model": {"source": "env", "name": "TESTWEAVER_BAILIAN_MODEL"},
                "credential": {"source": "env", "name": "TESTWEAVER_BAILIAN_CREDENTIAL"},
                "wire_api": "chat",
            },
            "limits": {
                "timeout_seconds": 1,
                "max_model_decisions": 1,
                "max_tool_calls": 0,
                "max_cost_units": 1,
            },
        },
        "provenance": {
            "source": "focused-test",
            "source_revision": "test-revision",
            "method": "protocol-only test",
        },
        "prompt": "test-only prompt",
    }


class StdioJsonRpcClientTests(unittest.TestCase):
    def _client(self, command: list[str], timeout: float = 1.0) -> StdioJsonRpcClient:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(REPO_ROOT)
        return StdioJsonRpcClient(
            command,
            cwd=REPO_ROOT,
            env=environment,
            response_timeout=timeout,
        )

    def test_notification_does_not_read_and_full_server_sequence_completes(self) -> None:
        client = self._client([sys.executable, "-c", _SERVER_WRAPPER])
        try:
            initialized = client.rpc(
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
            )
            self.assertEqual(initialized["id"], 1)

            self.assertIsNone(
                client.send_notification(
                    "notifications/initialized",
                    {},
                )
            )
            tools = client.rpc(
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
            )
            self.assertEqual(tools["id"], 2)
            self.assertEqual(len(tools["result"]["tools"]), 1)

            call = client.rpc(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "native_worker_execute",
                        "arguments": _call_arguments(),
                    },
                }
            )
            self.assertEqual(call["id"], 3)
            self.assertTrue(call["result"]["content"])
        finally:
            client.close()
        self.assertIsNotNone(client.process.returncode)

    def test_rpc_without_id_uses_notification_path(self) -> None:
        client = self._client([sys.executable, "-c", _SERVER_WRAPPER])
        try:
            self.assertIsNone(
                client.rpc(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                        "params": {},
                    }
                )
            )
            tools = client.rpc(
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
            )
            self.assertEqual(tools["id"], 2)
        finally:
            client.close()

    def test_response_read_has_a_bound_and_close_terminates_server(self) -> None:
        stalled_server = "import sys, time; sys.stdin.readline(); time.sleep(5)"
        client = self._client([sys.executable, "-c", stalled_server], timeout=0.1)
        started = time.monotonic()
        try:
            with self.assertRaises(StdioJsonRpcTimeout):
                client.rpc({"jsonrpc": "2.0", "id": 1, "method": "never", "params": {}})
        finally:
            client.close()
        self.assertLess(time.monotonic() - started, 2)
        self.assertIsNotNone(client.process.returncode)


if __name__ == "__main__":
    unittest.main()
