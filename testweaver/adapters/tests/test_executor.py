"""Focused fake-process checks; no test here is LIVE provider evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import testweaver.adapters.executor as executor
from testweaver.adapters.config import AdapterConfig
from testweaver.adapters.mcp_server import list_tools
from testweaver.adapters.native_worker import NativeWorkerAssignment
from testweaver.adapters.result import Provenance


def _limits(timeout: float = 2.0) -> dict[str, int | float]:
    return {
        "timeout_seconds": timeout,
        "max_model_decisions": 4,
        "max_tool_calls": 8,
        "max_cost_units": 3.0,
    }


def _assignment() -> NativeWorkerAssignment:
    return NativeWorkerAssignment(
        project_id="native-project-ref",
        task_id="native-task-ref",
        room_id="!native-room-ref:example.invalid",
        worker_id="native-worker-ref",
        leader_id="native-leader-ref",
        task_ref="native-task-spec-ref",
    )


def _provenance() -> Provenance:
    return Provenance("fake-external-worker", "fixture-revision", "focused fake process")


def _config(provider: str = "deepseek", timeout: float = 2.0) -> AdapterConfig:
    if provider == "deepseek":
        names = ("TESTWEAVER_DSH_ENDPOINT", "TESTWEAVER_DSH_MODEL", "TESTWEAVER_DSH_CREDENTIAL")
    else:
        names = ("TESTWEAVER_BAILIAN_ENDPOINT", "TESTWEAVER_BAILIAN_MODEL", "TESTWEAVER_BAILIAN_CREDENTIAL")
    return AdapterConfig.from_mapping(
        {
            "adapter_kind": "dsh",
            "route": {
                "provider": provider,
                "endpoint": {"source": "env", "name": names[0]},
                "model": {"source": "env", "name": names[1]},
                "credential": {"source": "env", "name": names[2]},
                "wire_api": "chat",
            },
            "limits": _limits(timeout),
        }
    )


def _codex_config(timeout: float = 2.0) -> AdapterConfig:
    return AdapterConfig.from_mapping(
        {
            "adapter_kind": "codex-cli",
            "route": {
                "provider": "codex-cc",
                "endpoint": {"source": "env", "name": "TESTWEAVER_CODEX_ENDPOINT"},
                "model": {"source": "env", "name": "TESTWEAVER_CODEX_MODEL"},
                "credential": {"source": "env", "name": "TESTWEAVER_CODEX_CREDENTIAL"},
                "wire_api": "chat",
            },
            "limits": _limits(timeout),
        }
    )


def _script(directory: Path, body: str) -> Path:
    path = directory / "fake-external"
    path.write_text("#!/usr/bin/python3\n" + body, encoding="utf-8")
    path.chmod(0o700)
    return path


class OneShotExecutorTests(unittest.TestCase):
    def _run(self, script: Path, config: AdapterConfig, workspace: Path, *, codex: bool = False):
        env = {
            "AGENT_WORKSPACE": str(workspace),
            "TESTWEAVER_DSH_ENDPOINT": "https://deepseek.invalid",
            "TESTWEAVER_DSH_MODEL": "fixture-deepseek-model",
            "TESTWEAVER_DSH_CREDENTIAL": "fixture-redaction-value-1234",
            "TESTWEAVER_BAILIAN_ENDPOINT": "https://bailian.invalid",
            "TESTWEAVER_BAILIAN_MODEL": "fixture-bailian-model",
            "TESTWEAVER_BAILIAN_CREDENTIAL": "fixture-bailian-credential-1234",
            "TESTWEAVER_CODEX_ENDPOINT": "https://codex.invalid",
            "TESTWEAVER_CODEX_MODEL": "fixture-codex-model",
            "TESTWEAVER_CODEX_CREDENTIAL": "fixture-codex-credential-1234",
            "HOME": str(workspace),
            "CODEX_HOME": str(workspace / "codex-home"),
        }
        (workspace / "codex-home").mkdir()
        executable_name = "PRODUCTION_CODEX_EXECUTABLE" if codex else "PRODUCTION_DSH_EXECUTABLE"
        with patch.dict(os.environ, env, clear=False), patch.object(executor, "_WORKSPACE_ROOTS", (workspace,)), patch.object(
            executor, executable_name, script
        ):
            return executor.execute_native_worker(_assignment(), config, _provenance(), "read the assigned source")

    def test_dsh_profiles_execute_once_and_redact_output_without_faking_usage(self) -> None:
        for provider in ("deepseek", "aliyun-bailian"):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory) / "workspace"
                workspace.mkdir()
                script = _script(
                    workspace,
                    "import json, os, sys\n"
                    "request = json.load(sys.stdin)\n"
                    "assert request['native_assignment']['task_id'] == 'native-task-ref'\n"
                    "secret = os.environ.get('TESTWEAVER_DSH_CREDENTIAL') or os.environ.get('TESTWEAVER_BAILIAN_CREDENTIAL', '')\n"
                    "print(json.dumps({'status': 'COMPLETED', 'output': 'api_key=' + secret, 'usage': {}}))\n",
                )
                result, metadata = self._run(script, _config(provider), workspace)
                artifact = workspace / result.result_ref
                content = artifact.read_text(encoding="utf-8")
                self.assertEqual(result.status, "completed")
                self.assertFalse(result.usage.observed)
                self.assertIn("[REDACTED]", content)
                self.assertNotIn("fixture-redaction-value-1234", content)
                self.assertTrue(metadata["external_process_started"])
                self.assertFalse(metadata["native_state_mutation"])
                self.assertFalse(metadata["native_result_submission"])
                self.assertEqual(metadata["argv"][1:], ["--protocol", executor.NATIVE_EXECUTION_PROTOCOL])
                self.assertEqual(result.evidence_refs[0].artifact_ref, result.result_ref)

    def test_codex_uses_fixed_noninteractive_exec_and_stdin_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            script = _script(
                workspace,
                "import sys\n"
                "assert sys.stdin.read()\n"
                "print('codex fixture result')\n",
            )
            result, metadata = self._run(script, _codex_config(), workspace, codex=True)
            self.assertEqual(result.status, "completed")
            self.assertFalse(result.usage.observed)
            self.assertIn("exec", metadata["argv"])
            self.assertIn("--json", metadata["argv"])
            self.assertNotIn("app-server", metadata["argv"])
            self.assertIn("gpt-5.6-luna", metadata["argv"])
            self.assertIn("model_reasoning_effort=max", metadata["argv"])

    def test_timeout_kills_bounded_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            script = _script(workspace, "import time\ntime.sleep(5)\n")
            started = time.monotonic()
            result, metadata = self._run(script, _config(timeout=0.1), workspace)
            self.assertEqual(result.termination, "timeout")
            self.assertTrue(metadata["timed_out"])
            self.assertLess(time.monotonic() - started, 3)

    def test_output_limit_is_terminal_and_diagnostic_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            script = _script(workspace, "print('x' * 4096)\n")
            with patch.object(executor, "DEFAULT_MAX_OUTPUT_BYTES", 128):
                result, metadata = self._run(script, _config(), workspace)
            self.assertEqual(result.termination, "protocol_error")
            self.assertTrue(metadata["output_limit_exceeded"])
            self.assertLessEqual(sum(item.stat().st_size for item in workspace.rglob("*" ) if item.is_file()), 4096)

    def test_profile_executable_and_environment_are_not_request_controls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            script = _script(workspace, "print('{}')\n")
            unsafe = AdapterConfig.from_mapping(
                {
                    "adapter_kind": "dsh",
                    "route": {
                        "provider": "deepseek",
                        "endpoint": {"source": "env", "name": "UNSAFE_ENDPOINT"},
                        "model": {"source": "env", "name": "TESTWEAVER_DSH_MODEL"},
                        "credential": {"source": "env", "name": "TESTWEAVER_DSH_CREDENTIAL"},
                        "wire_api": "chat",
                    },
                    "limits": _limits(),
                }
            )
            with self.assertRaisesRegex(executor.NativeExecutionError, "not allowlisted"):
                self._run(script, unsafe, workspace)


class McpSurfaceTests(unittest.TestCase):
    def test_one_tool_has_only_native_contract_arguments(self) -> None:
        tools = list_tools()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "native_worker_execute")
        self.assertEqual(
            set(tools[0]["inputSchema"]["required"]),
            {"assignment", "config", "provenance", "prompt"},
        )

    def test_adapter_source_has_no_native_task_operation_surface(self) -> None:
        source = Path(executor.__file__).read_text(encoding="utf-8") + Path(
            __import__("testweaver.adapters.mcp_server", fromlist=["__file__"]).__file__
        ).read_text(encoding="utf-8")
        for forbidden in ("create_project", "delegate_task", "submit_task", "scheduler", "lease", "Matrix"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
