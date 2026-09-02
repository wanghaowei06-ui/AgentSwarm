"""Focused fake-process checks; no test here is LIVE provider evidence."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import testweaver.adapters.config as adapter_config
import testweaver.adapters.executor as executor
from testweaver.adapters.config import AdapterConfig, _runtime_route_fields
from testweaver.adapters.mcp_server import call_tool, handle_request, list_tools
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


def _gateway_dsh_config(timeout: float = 2.0) -> AdapterConfig:
    return AdapterConfig.from_mapping(
        {
            "adapter_kind": "dsh",
            "route": {
                "provider": "aliyun-bailian",
                "endpoint": {"source": "env", "name": "AGENTTEAMS_AI_GATEWAY_URL"},
                "model": {"source": "env", "name": "TESTWEAVER_BAILIAN_MODEL"},
                "credential": {
                    "source": "env",
                    "name": "AGENTTEAMS_WORKER_GATEWAY_KEY",
                },
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
    def _run(
        self,
        script: Path,
        config: AdapterConfig,
        workspace: Path,
        *,
        codex: bool = False,
        env_overrides: dict[str, str] | None = None,
        env_remove: tuple[str, ...] = (),
    ):
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
            "AGENTTEAMS_AI_GATEWAY_URL": "https://gateway.invalid/testweaver-bailian/v1",
            "AGENTTEAMS_WORKER_GATEWAY_KEY": "fixture-worker-gateway-key-1234",
            "HOME": str(workspace),
            "CODEX_HOME": str(workspace / "codex-home"),
        }
        if env_overrides:
            env.update(env_overrides)
        for name in env_remove:
            env.pop(name, None)
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
                    "import os\n"
                    "secret = os.environ.get('TESTWEAVER_DSH_CREDENTIAL') or os.environ.get('TESTWEAVER_BAILIAN_CREDENTIAL', '')\n"
                    "print('api_key=' + secret)\n",
                )
                result, metadata = self._run(script, _config(provider), workspace)
                artifact = workspace / result.result_ref
                content = artifact.read_text(encoding="utf-8")
                self.assertEqual(result.status, "completed")
                self.assertFalse(result.usage.observed)
                self.assertIn("[REDACTED]", content)
                self.assertNotIn("fixture-redaction-value-1234", content)
                self.assertNotIn("read the assigned source", content)
                self.assertNotIn("read the assigned source", repr(result))
                self.assertTrue(metadata["external_process_started"])
                self.assertFalse(metadata["native_state_mutation"])
                self.assertFalse(metadata["native_result_submission"])
                self.assertEqual(metadata["argv"][1:4], ["--profile", "headless", "--"])
                self.assertEqual(metadata["argv"][4], "[PROMPT_REDACTED]")
                self.assertNotIn("read the assigned source", repr(metadata))
                self.assertEqual(metadata["prompt_bytes"], len("read the assigned source".encode()))
                self.assertEqual(
                    metadata["prompt_sha256"],
                    hashlib.sha256(b"read the assigned source").hexdigest(),
                )
                self.assertEqual(result.evidence_refs[0].artifact_ref, result.result_ref)

    def test_dsh_leading_dash_prompt_is_positional(self) -> None:
        self.assertEqual(
            executor._argv(_config("deepseek"), "-do not parse as an option")[1:],
            ["--profile", "headless", "--", "-do not parse as an option"],
        )

    def test_dsh_nonzero_exit_is_provider_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            script = _script(workspace, "import sys\nsys.exit(7)\n")
            result, metadata = self._run(script, _config("deepseek"), workspace)
            self.assertEqual(result.status, "failed")
            self.assertEqual(result.termination, "provider_error")
            self.assertEqual(metadata["exit_code"], 7)

    def test_dsh_empty_output_is_protocol_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            script = _script(workspace, "pass\n")
            result, metadata = self._run(script, _config("deepseek"), workspace)
            self.assertEqual(result.termination, "protocol_error")
            self.assertNotIn("read the assigned source", repr(metadata))

    def test_dsh_aliases_route_refs_only_in_child_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            script = _script(
                workspace,
                "import os\n"
                "print(os.environ['DEEPSEEK_BASE_URL'])\n"
                "print(os.environ['DEEPSEEK_API_KEY'])\n",
            )
            result, _ = self._run(script, _gateway_dsh_config(), workspace)
            content = (workspace / result.result_ref).read_text(encoding="utf-8")
            self.assertNotIn("https://gateway.invalid", content)
            self.assertNotIn("fixture-worker-gateway-key-1234", content)
            self.assertNotIn("DEEPSEEK_BASE_URL", os.environ)
            self.assertNotIn("DEEPSEEK_API_KEY", os.environ)

    def test_codex_child_environment_excludes_route_references(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            script = _script(
                workspace,
                "import os\n"
                "for name in ('HOME', 'CODEX_HOME', 'TESTWEAVER_CODEX_ENDPOINT',\n"
                "             'TESTWEAVER_CODEX_MODEL', 'TESTWEAVER_CODEX_CREDENTIAL'):\n"
                "    print(name + '=' + str(name in os.environ))\n",
            )
            result, _ = self._run(
                script,
                _codex_config(),
                workspace,
                codex=True,
            )
            content = (workspace / result.result_ref).read_text(encoding="utf-8")
        self.assertIn("HOME=True", content)
        self.assertIn("CODEX_HOME=True", content)
        self.assertIn("TESTWEAVER_CODEX_ENDPOINT=False", content)
        self.assertIn("TESTWEAVER_CODEX_MODEL=False", content)
        self.assertIn("TESTWEAVER_CODEX_CREDENTIAL=False", content)

    def test_dsh_environment_credential_uses_file_validation_rules(self) -> None:
        config = _config("deepseek")
        cases = (
            ("TESTWEAVER_DSH_ENDPOINT", "", "empty"),
            ("TESTWEAVER_DSH_ENDPOINT", "not-an-endpoint", "invalid format"),
            ("TESTWEAVER_DSH_MODEL", "", "empty"),
            ("TESTWEAVER_DSH_MODEL", "model with whitespace", "invalid format"),
            ("TESTWEAVER_DSH_CREDENTIAL", "", "too short"),
            ("TESTWEAVER_DSH_CREDENTIAL", "short", "too short"),
            ("TESTWEAVER_DSH_CREDENTIAL", "credential\nvalue", "invalid format"),
        )
        for name, value, message in cases:
            with self.subTest(name=name, message=message), patch.dict(
                os.environ,
                {
                    "TESTWEAVER_DSH_ENDPOINT": "https://deepseek.invalid/v1",
                    "TESTWEAVER_DSH_MODEL": "deepseek-model",
                    "TESTWEAVER_DSH_CREDENTIAL": "credential-value-1234",
                    name: value,
                },
                clear=True,
            ):
                with self.assertRaisesRegex(executor.NativeExecutionError, message):
                    executor._environment(config)

    def test_dsh_file_refs_resolve_endpoint_and_credential_only_in_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "protected"
            root.mkdir()
            root.chmod(0o700)
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            values = {
                "endpoint": "https://file-gateway.invalid/v1",
                "model": "file-model",
                "credential": "file-credential-value-1234",
            }
            paths = {}
            for field, value in values.items():
                path = root / field
                path.write_text(value, encoding="utf-8")
                path.chmod(0o400)
                paths[field] = {"source": "file", "path": str(path)}
            config = AdapterConfig.from_mapping(
                {
                    "adapter_kind": "dsh",
                    "route": {
                        "provider": "deepseek",
                        "endpoint": paths["endpoint"],
                        "model": paths["model"],
                        "credential": paths["credential"],
                        "wire_api": "chat",
                    },
                    "limits": _limits(),
                }
            )
            script = _script(
                workspace,
                "import os\n"
                "print(os.environ['DEEPSEEK_BASE_URL'])\n"
                "print(os.environ['DEEPSEEK_API_KEY'])\n"
                "print('model_alias=' + str(bool(os.environ.get('DEEPSEEK_MODEL'))))\n",
            )
            with patch.dict(os.environ, {}, clear=True), patch.object(
                adapter_config, "PROTECTED_PROVIDER_DIRECTORY", root
            ):
                result, metadata = self._run(script, config, workspace)
            content = (workspace / result.result_ref).read_text(encoding="utf-8")
            self.assertNotIn(values["endpoint"], content)
            self.assertNotIn(values["credential"], content)
            self.assertIn("model_alias=False", content)
            self.assertNotIn(values["endpoint"], repr(metadata))
            self.assertNotIn(values["credential"], repr(metadata))
            self.assertNotIn("DEEPSEEK_BASE_URL", os.environ)
            self.assertNotIn("DEEPSEEK_API_KEY", os.environ)

    def test_dsh_file_refs_fail_closed_for_invalid_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "protected"
            root.mkdir()
            root.chmod(0o700)
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            valid = root / "valid"
            valid.write_text("valid-reference", encoding="utf-8")
            valid.chmod(0o400)
            max_file_bytes = 64 * 1024
            bad_cases = {
                "empty": b"",
                "nul": b"valid\x00reference",
                "oversize": b"x" * (max_file_bytes + 1),
            }
            for name, content in bad_cases.items():
                with self.subTest(name=name):
                    bad = root / name
                    bad.write_bytes(content)
                    bad.chmod(0o400)
                    config = AdapterConfig.from_mapping(
                        {
                            "adapter_kind": "dsh",
                            "route": {
                                "provider": "deepseek",
                                "endpoint": {"source": "file", "path": str(bad)},
                                "model": {"source": "file", "path": str(valid)},
                                "credential": {"source": "file", "path": str(valid)},
                                "wire_api": "chat",
                            },
                            "limits": _limits(),
                        }
                    )
                    with patch.object(adapter_config, "PROTECTED_PROVIDER_DIRECTORY", root):
                        with self.assertRaisesRegex(executor.NativeExecutionError, "protected file"):
                            executor._environment(config)

    def test_dsh_file_refs_fail_closed_for_symlink_nonregular_and_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "protected"
            root.mkdir()
            root.chmod(0o700)
            valid = root / "valid"
            valid.write_text("valid-reference", encoding="utf-8")
            valid.chmod(0o400)
            model = {"source": "file", "path": str(valid)}
            credential = {"source": "file", "path": str(valid)}
            cases = {
                "symlink": root / "symlink",
                "directory": root / "directory",
                "world_readable": root / "world-readable",
            }
            cases["symlink"].symlink_to(valid)
            cases["directory"].mkdir()
            cases["world_readable"].write_text("not-owner-only", encoding="utf-8")
            cases["world_readable"].chmod(0o644)
            for name, path in cases.items():
                with self.subTest(name=name):
                    config = AdapterConfig.from_mapping(
                        {
                            "adapter_kind": "dsh",
                            "route": {
                                "provider": "deepseek",
                                "endpoint": {"source": "file", "path": str(path)},
                                "model": model,
                                "credential": credential,
                                "wire_api": "chat",
                            },
                            "limits": _limits(),
                        }
                    )
                    with patch.object(adapter_config, "PROTECTED_PROVIDER_DIRECTORY", root):
                        with self.assertRaises(executor.NativeExecutionError):
                            executor._environment(config)

    def test_bailian_legacy_refs_bind_from_agentteams_runtime_without_persisting_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            runtime = workspace / "runtime.yaml"
            runtime.write_text(
                "desired:\n"
                "  model:\n"
                "    gatewayUrl: https://gateway.invalid/v1/testweaver-bailian\n"
                "    model: runtime-bailian-model\n"
                "    providerId: agentteams-gateway\n",
                encoding="utf-8",
            )
            self.assertEqual(
                _runtime_route_fields(str(runtime), (workspace,)),
                (True, "https://gateway.invalid/v1/testweaver-bailian", "runtime-bailian-model"),
            )
            script = _script(
                workspace,
                "import os\n"
                "print('endpoint=' + str(bool(os.environ.get('TESTWEAVER_BAILIAN_ENDPOINT'))))\n"
                "print('model=' + str(bool(os.environ.get('TESTWEAVER_BAILIAN_MODEL'))))\n"
                "print('credential=' + str(bool(os.environ.get('TESTWEAVER_BAILIAN_CREDENTIAL'))))\n"
                "print('deepseek_base=' + str(bool(os.environ.get('DEEPSEEK_BASE_URL'))))\n"
                "print('deepseek_key=' + str(bool(os.environ.get('DEEPSEEK_API_KEY'))))\n",
            )
            with patch.dict(os.environ, {}, clear=True):
                result, metadata = self._run(
                    script,
                    _config("aliyun-bailian"),
                    workspace,
                    env_overrides={
                        "TEAMHARNESS_RUNTIME_CONFIG": str(runtime),
                        "TESTWEAVER_BAILIAN_ENDPOINT": "",
                        "TESTWEAVER_BAILIAN_MODEL": "",
                        "TESTWEAVER_BAILIAN_CREDENTIAL": "",
                    },
                )
                content = (workspace / result.result_ref).read_text(encoding="utf-8")
                self.assertIn("endpoint=True", content)
                self.assertIn("model=True", content)
                self.assertIn("credential=True", content)
                self.assertIn("deepseek_base=True", content)
                self.assertIn("deepseek_key=True", content)
                self.assertNotIn("runtime-bailian-model", content)
                self.assertNotIn("fixture-worker-gateway-key-1234", content)
                self.assertNotIn("TESTWEAVER_BAILIAN_ENDPOINT", repr(metadata))
                self.assertNotIn("TESTWEAVER_BAILIAN_MODEL", repr(metadata))
                self.assertNotIn("TESTWEAVER_BAILIAN_CREDENTIAL", repr(metadata))
                self.assertEqual(os.environ, {})

    def test_bailian_legacy_refs_prefer_home_runtime_over_workspace_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            workspace = Path(directory) / "workspace"
            home.mkdir()
            workspace.mkdir()
            home_runtime = home / "runtime" / "runtime.yaml"
            workspace_runtime = workspace / "runtime" / "runtime.yaml"
            home_runtime.parent.mkdir()
            workspace_runtime.parent.mkdir()
            home_runtime.write_text(
                "desired:\n"
                "  model:\n"
                "    gatewayUrl: https://home.invalid/v1/testweaver-bailian\n"
                "    model: home-bailian-model\n",
                encoding="utf-8",
            )
            workspace_runtime.write_text(
                "desired:\n"
                "  model:\n"
                "    gatewayUrl: https://workspace.invalid/v1/testweaver-bailian\n"
                "    model: workspace-bailian-model\n",
                encoding="utf-8",
            )
            environment = {
                "HOME": str(home),
                "AGENT_WORKSPACE": str(workspace),
                "TEAMHARNESS_RUNTIME_CONFIG": "",
                "AGENTTEAMS_AI_GATEWAY_URL": "https://gateway.invalid/v1",
                "AGENTTEAMS_WORKER_MODEL": "worker-default-model",
                "AGENTTEAMS_WORKER_GATEWAY_KEY": "fixture-worker-gateway-key-1234",
                "TESTWEAVER_BAILIAN_ENDPOINT": "",
                "TESTWEAVER_BAILIAN_MODEL": "",
                "TESTWEAVER_BAILIAN_CREDENTIAL": "",
            }
            config = _config("aliyun-bailian")
            with patch.dict(os.environ, environment, clear=True):
                with adapter_config.bind_bailian_route(config, (home, workspace)):
                    self.assertEqual(
                        os.environ["TESTWEAVER_BAILIAN_ENDPOINT"],
                        "https://home.invalid/v1/testweaver-bailian",
                    )
                    self.assertEqual(os.environ["TESTWEAVER_BAILIAN_MODEL"], "home-bailian-model")
                    self.assertEqual(
                        os.environ["TESTWEAVER_BAILIAN_CREDENTIAL"],
                        "fixture-worker-gateway-key-1234",
                    )
                self.assertEqual(os.environ, environment)

    def test_bailian_legacy_refs_use_workspace_runtime_when_home_runtime_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            workspace = Path(directory) / "workspace"
            home.mkdir()
            runtime = workspace / "runtime" / "runtime.yaml"
            runtime.parent.mkdir(parents=True)
            runtime.write_text(
                "desired:\n"
                "  model:\n"
                "    gatewayUrl: https://workspace.invalid/v1/testweaver-bailian\n"
                "    model: workspace-bailian-model\n",
                encoding="utf-8",
            )
            environment = {
                "HOME": str(home),
                "AGENT_WORKSPACE": str(workspace),
                "TEAMHARNESS_RUNTIME_CONFIG": "",
                "AGENTTEAMS_AI_GATEWAY_URL": "https://gateway.invalid/v1",
                "AGENTTEAMS_WORKER_MODEL": "worker-default-model",
                "AGENTTEAMS_WORKER_GATEWAY_KEY": "fixture-worker-gateway-key-1234",
                "TESTWEAVER_BAILIAN_ENDPOINT": "",
                "TESTWEAVER_BAILIAN_MODEL": "",
                "TESTWEAVER_BAILIAN_CREDENTIAL": "",
            }
            with patch.dict(os.environ, environment, clear=True):
                with adapter_config.bind_bailian_route(_config("aliyun-bailian"), (home, workspace)):
                    self.assertEqual(
                        os.environ["TESTWEAVER_BAILIAN_ENDPOINT"],
                        "https://workspace.invalid/v1/testweaver-bailian",
                    )
                    self.assertEqual(os.environ["TESTWEAVER_BAILIAN_MODEL"], "workspace-bailian-model")
                self.assertEqual(os.environ, environment)

    def test_bailian_binding_does_not_fallback_to_default_route_when_runtime_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(executor.NativeExecutionError, "endpoint protected reference is unavailable"):
                    self._run(
                        _script(workspace, "print('must not start')\n"),
                        _config("aliyun-bailian"),
                        workspace,
                        env_overrides={
                            "TEAMHARNESS_RUNTIME_CONFIG": str(workspace / "missing-runtime.yaml"),
                            "AGENTTEAMS_AI_GATEWAY_URL": "https://gateway.invalid/v1",
                            "AGENTTEAMS_WORKER_MODEL": "worker-default-model",
                            "TESTWEAVER_BAILIAN_CREDENTIAL": "fixture-bailian-credential-1234",
                        },
                        env_remove=(
                            "TESTWEAVER_BAILIAN_ENDPOINT",
                            "TESTWEAVER_BAILIAN_MODEL",
                        ),
                    )

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

    def test_schema_rejects_legacy_shape_and_tools_call_accepts_contract_fixture(self) -> None:
        listed = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        schema = listed["result"]["tools"][0]["inputSchema"]
        assignment = schema["properties"]["assignment"]
        config = schema["properties"]["config"]
        route = config["properties"]["route"]
        provenance = schema["properties"]["provenance"]
        self.assertEqual(
            set(assignment["required"]),
            {"project_id", "task_id", "room_id", "worker_id", "leader_id", "task_ref", "read_only"},
        )
        self.assertEqual(set(config["required"]), {"adapter_kind", "route", "limits"})
        self.assertEqual(set(route["required"]), {"provider", "endpoint", "model", "credential", "wire_api"})
        self.assertEqual(set(provenance["required"]), {"source", "source_revision", "method"})
        legacy = {
            "assignment": {
                "leader": "native-leader-ref",
                "worker": "native-worker-ref",
                "source_room_id": "!native-room-ref:example.invalid",
                "input_root": "current-task-input",
                "spec_path": "current-task-spec",
                "task_title": "fixed task",
            },
            "config": {"provider": "deepseek", "model": "fixture", "route": "default", "limits": {"max_tokens": 4}},
            "provenance": {"source": "fixture", "method": "fixture"},
            "prompt": "read the assigned source",
        }
        self.assertTrue(set(legacy["assignment"]) - set(assignment["properties"]))
        rejected = call_tool("native_worker_execute", legacy)
        self.assertFalse(json.loads(rejected["content"][0]["text"])["ok"])
        valid = {
            "assignment": {
                "project_id": "native-project-ref",
                "task_id": "native-task-ref",
                "room_id": "!native-room-ref:example.invalid",
                "worker_id": "native-worker-ref",
                "leader_id": "native-leader-ref",
                "task_ref": "native-task-spec-ref",
                "read_only": True,
            },
            "config": {
                "adapter_kind": "dsh",
                "route": {
                    "provider": "deepseek",
                    "endpoint": {"source": "env", "name": "TESTWEAVER_DSH_ENDPOINT"},
                    "model": {"source": "env", "name": "TESTWEAVER_DSH_MODEL"},
                    "credential": {"source": "env", "name": "TESTWEAVER_DSH_CREDENTIAL"},
                    "wire_api": "chat",
                },
                "limits": _limits(),
            },
            "provenance": {"source": "fixture", "source_revision": "fixture-revision", "method": "fixture"},
            "prompt": "read the assigned source",
        }

        class FixtureResult:
            def as_dict(self):
                return {"status": "completed", "fixture": True}

        with patch("testweaver.adapters.mcp_server.execute_native_worker", return_value=(FixtureResult(), {"fixture": True})):
            accepted = handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "native_worker_execute", "arguments": valid},
                }
            )
        self.assertTrue(json.loads(accepted["result"]["content"][0]["text"])["ok"])

    def test_adapter_source_has_no_native_task_operation_surface(self) -> None:
        source = Path(executor.__file__).read_text(encoding="utf-8") + Path(
            __import__("testweaver.adapters.mcp_server", fromlist=["__file__"]).__file__
        ).read_text(encoding="utf-8")
        for forbidden in ("create_project", "delegate_task", "submit_task", "scheduler", "lease", "Matrix"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
