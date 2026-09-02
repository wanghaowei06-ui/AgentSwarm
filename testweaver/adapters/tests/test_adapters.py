"""Focused local adapter checks; fixtures are not LIVE evidence."""

from __future__ import annotations

import copy
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import testweaver.adapters.config as adapter_config
from testweaver.adapters.codex_cli import (
    CODEX_EXECUTABLE,
    DEFAULT_MODEL,
    DEFAULT_REASONING,
    build_codex_cli_launch,
)
from testweaver.adapters.config import (
    AdapterConfig,
    AdapterConfigError,
    preflight_adapter_reference,
    read_protected_file,
    ProtectedReference,
    preflight_reference,
)
from testweaver.adapters.native_worker import (
    DSH_PROVIDER_PROFILES,
    DshProviderProfile,
    NativeWorkerAssignment,
    preflight_native_worker_invocation,
    prepare_native_worker_invocation,
)
from testweaver.adapters.result import (
    EvidenceReference,
    NativeReferences,
    NormalizedResult,
    Provenance,
    ResultContractError,
    WorkerResult,
    normalize_result,
)


TEST_FIXTURE_ONLY_NOT_LIVE = True
_DIGEST = "sha256:" + "a" * 64


def _limits() -> dict[str, int | float]:
    return {
        "timeout_seconds": 120.0,
        "max_model_decisions": 4,
        "max_tool_calls": 8,
        "max_cost_units": 3.0,
    }


def _route(provider: str, endpoint: dict[str, str], model: dict[str, str]) -> dict[str, object]:
    return {
        "provider": provider,
        "endpoint": endpoint,
        "model": model,
        "credential": {"source": "env", "name": "TESTWEAVER_PROVIDER_CREDENTIAL"},
        "wire_api": "chat",
    }


def _config(provider: str, endpoint: dict[str, str], model: dict[str, str]) -> AdapterConfig:
    return AdapterConfig.from_mapping(
        {
            "adapter_kind": "dsh",
            "route": _route(provider, endpoint, model),
            "limits": _limits(),
        }
    )


def _native_refs() -> NativeReferences:
    return NativeReferences(
        project_id="native-project-ref",
        task_id="native-task-ref",
        room_id="!native-room-ref:example.invalid",
    )


def _provenance() -> Provenance:
    return Provenance(
        source="external-result-receipt",
        source_revision="runtime-revision-ref",
        method="normalized from a provider result receipt and native evidence pointers",
    )


def _assignment() -> NativeWorkerAssignment:
    return NativeWorkerAssignment(
        project_id="native-project-ref",
        task_id="native-task-ref",
        room_id="!native-room-ref:example.invalid",
        worker_id="native-worker-ref",
        leader_id="native-leader-ref",
        task_ref="native-task-spec-ref",
    )


def _evidence() -> list[dict[str, str]]:
    return [
        {
            "id": "evidence-ref",
            "kind": "artifact",
            "artifact_ref": "native-artifact-ref",
            "content_hash": _DIGEST,
        }
    ]


class AdapterConfigTests(unittest.TestCase):
    def test_preflight_checks_reference_metadata_without_reading_file_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provider-reference"
            path.write_text("reference-only\n", encoding="utf-8")
            os.chmod(path, 0o600)
            reference = ProtectedReference.file(str(path))

            with patch.object(Path, "read_text", side_effect=AssertionError("must not read")):
                result = preflight_reference(reference)

            self.assertTrue(result.usable)
            self.assertEqual(result.mode, 0o600)
            self.assertNotIn("value", result.as_dict())

            os.chmod(path, 0o644)
            self.assertFalse(preflight_reference(reference).usable)

    def test_environment_preflight_applies_field_validation_without_reading_values(self) -> None:
        cases = (
            ("endpoint", ProtectedReference.env("TESTWEAVER_DSH_ENDPOINT"), ""),
            ("endpoint", ProtectedReference.env("TESTWEAVER_DSH_ENDPOINT"), "not-an-endpoint"),
            ("model", ProtectedReference.env("TESTWEAVER_DSH_MODEL"), ""),
            ("model", ProtectedReference.env("TESTWEAVER_DSH_MODEL"), "model with whitespace"),
            ("credential", ProtectedReference.env("TESTWEAVER_DSH_CREDENTIAL"), ""),
            ("credential", ProtectedReference.env("TESTWEAVER_DSH_CREDENTIAL"), "short"),
        )
        for field, reference, value in cases:
            with self.subTest(field=field), patch.dict(
                os.environ, {reference.location: value}, clear=True
            ):
                for preflight in (preflight_reference, preflight_adapter_reference):
                    result = preflight(reference, field=field)
                    self.assertTrue(result.present)
                    self.assertFalse(result.usable)
                    self.assertEqual(result.reason, "environment_value_invalid")
                    if value:
                        self.assertNotIn(value, result.as_dict()["reason"] or "")

    def test_dsh_accepts_both_existing_provider_route_shapes(self) -> None:
        self.assertTrue(TEST_FIXTURE_ONLY_NOT_LIVE)
        deepseek = _config(
            "deepseek",
            {"source": "env", "name": "TESTWEAVER_DSH_ENDPOINT"},
            {"source": "file", "path": "/etc/agentteams/deepseek-model"},
        )
        bailian = _config(
            "aliyun-bailian",
            {"source": "file", "path": "/etc/agentteams/bailian-endpoint"},
            {"source": "env", "name": "TESTWEAVER_BAILIAN_MODEL"},
        )
        self.assertEqual(deepseek.route.provider, "deepseek")
        self.assertEqual(bailian.route.provider, "aliyun-bailian")
        self.assertEqual(deepseek.route.endpoint_ref.as_dict()["source"], "env")
        self.assertEqual(bailian.route.model_ref.as_dict()["source"], "env")

    def test_inline_route_values_are_rejected(self) -> None:
        raw = {
            "adapter_kind": "dsh",
            "route": _route(
                "deepseek",
                {"source": "env", "name": "TESTWEAVER_DSH_ENDPOINT"},
                {"source": "env", "name": "TESTWEAVER_DSH_MODEL"},
            ),
            "limits": _limits(),
        }
        raw["route"]["model"] = {"source": "env", "name": "TESTWEAVER_DSH_MODEL", "value": "fixture"}
        with self.assertRaisesRegex(AdapterConfigError, "model"):
            AdapterConfig.from_mapping(raw)

    def test_file_reference_is_location_only_and_absolute(self) -> None:
        raw = {
            "source": "file",
            "path": "/etc/agentteams/providers.env",
        }
        self.assertEqual(
            AdapterConfig.from_mapping(
                {
                    "adapter_kind": "dsh",
                    "route": _route(
                        "aliyun-bailian",
                        raw,
                        {"source": "env", "name": "TESTWEAVER_BAILIAN_MODEL"},
                    ),
                    "limits": _limits(),
                }
            ).route.endpoint_ref.location,
            "/etc/agentteams/providers.env",
        )
        with self.assertRaisesRegex(AdapterConfigError, "absolute"):
            AdapterConfig.from_mapping(
                {
                    "adapter_kind": "dsh",
                    "route": _route(
                        "deepseek",
                        {"source": "file", "path": "providers.env"},
                        {"source": "env", "name": "TESTWEAVER_DSH_MODEL"},
                    ),
                    "limits": _limits(),
                }
            )

    def test_read_protected_file_requires_dedicated_directory_and_field_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "testweaver-provider"
            root.mkdir()
            root.chmod(0o700)
            values = {
                "endpoint": "https://provider.invalid/v1",
                "model": "provider-model",
                "credential": "credential-value-1234",
            }
            with patch.object(adapter_config, "PROTECTED_PROVIDER_DIRECTORY", root):
                for field, value in values.items():
                    path = root / field
                    path.write_text(value, encoding="utf-8")
                    path.chmod(0o400)
                    self.assertEqual(
                        read_protected_file(ProtectedReference.file(str(path)), field),
                        value,
                    )

                outside = root.parent / "providers.env"
                outside.write_text("AGENTTEAMS_BAILIAN_MODEL=not-a-single-ref", encoding="utf-8")
                outside.chmod(0o400)
                with self.assertRaisesRegex(AdapterConfigError, "dedicated provider directory"):
                    read_protected_file(ProtectedReference.file(str(outside)), "model")
                self.assertFalse(
                    preflight_adapter_reference(
                        ProtectedReference.file(str(outside)),
                        dedicated_provider=True,
                    ).usable
                )

    def test_read_protected_file_validates_endpoint_and_model_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "testweaver-provider"
            root.mkdir()
            root.chmod(0o700)
            cases = {
                "endpoint": "provider.invalid/v1",
                "model": "model with whitespace",
            }
            with patch.object(adapter_config, "PROTECTED_PROVIDER_DIRECTORY", root):
                for field, value in cases.items():
                    path = root / field
                    path.write_text(value, encoding="utf-8")
                    path.chmod(0o400)
                    with self.subTest(field=field):
                        with self.assertRaisesRegex(AdapterConfigError, "invalid format"):
                            read_protected_file(ProtectedReference.file(str(path)), field)

    def test_read_protected_file_rejects_unsafe_directory_content_without_blocking_fifo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "testweaver-provider"
            root.mkdir()
            root.chmod(0o700)
            path = root / "credential"
            path.write_text("short", encoding="utf-8")
            path.chmod(0o400)
            with patch.object(adapter_config, "PROTECTED_PROVIDER_DIRECTORY", root):
                with self.assertRaisesRegex(AdapterConfigError, "too short"):
                    read_protected_file(ProtectedReference.file(str(path)), "credential")
                path.write_text("credential\nvalue", encoding="utf-8")
                with self.assertRaisesRegex(AdapterConfigError, "invalid format"):
                    read_protected_file(ProtectedReference.file(str(path)), "credential")

                root.chmod(0o755)
                path.write_text("credential-value-1234", encoding="utf-8")
                with self.assertRaisesRegex(AdapterConfigError, "directory"):
                    read_protected_file(ProtectedReference.file(str(path)), "credential")
                root.chmod(0o700)

                fifo = root / "fifo"
                os.mkfifo(fifo)
                fifo.chmod(0o400)
                started = time.monotonic()
                with self.assertRaises(AdapterConfigError):
                    read_protected_file(ProtectedReference.file(str(fifo)), "credential")
                self.assertLess(time.monotonic() - started, 1.0)


class ResultContractTests(unittest.TestCase):
    def test_provider_neutral_result_normalizes_usage_and_evidence(self) -> None:
        config = _config(
            "aliyun-bailian",
            {"source": "file", "path": "/etc/agentteams/providers.env"},
            {"source": "env", "name": "TESTWEAVER_BAILIAN_MODEL"},
        )
        result = normalize_result(
            {
                "status": "COMPLETED",
                "result_ref": "native-result-artifact-ref",
                "evidence_refs": _evidence(),
                "usage": {
                    "modelDecisions": 2,
                    "tool_calls": 1,
                    "inputTokens": 10,
                    "output_tokens": 12,
                    "cost_units": 0.5,
                },
                "elapsed_seconds": 8.25,
            },
            config=config,
            native_refs=_native_refs(),
            provenance=_provenance(),
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.termination, "none")
        self.assertEqual(result.usage.model_decisions, 2)
        self.assertTrue(result.usage.observed)
        self.assertEqual(result.route.provider, "aliyun-bailian")
        self.assertTrue(result.as_dict()["content_hash"].startswith("sha256:"))
        NormalizedResult.from_mapping(result.as_dict())

    def test_unavailable_usage_is_not_coerced_to_zero(self) -> None:
        result = normalize_result(
            {
                "status": "completed",
                "result_ref": "native-result-artifact-ref",
                "evidence_refs": _evidence(),
                "usage": {},
            },
            config=_config(
                "deepseek",
                {"source": "env", "name": "TESTWEAVER_DSH_ENDPOINT"},
                {"source": "env", "name": "TESTWEAVER_DSH_MODEL"},
            ),
            native_refs=_native_refs(),
            provenance=_provenance(),
        )
        self.assertFalse(result.usage.observed)
        self.assertIsNone(result.usage.cost_units)

    def test_timeout_and_budget_are_normalized_without_execution(self) -> None:
        timeout = normalize_result(
            {
                "status": "TIMEOUT",
                "termination": "TIMEOUT",
                "result_ref": "native-timeout-artifact-ref",
                "evidence_refs": _evidence(),
                "usage": {"model_decisions": 1},
            },
            config=_config(
                "deepseek",
                {"source": "env", "name": "TESTWEAVER_DSH_ENDPOINT"},
                {"source": "env", "name": "TESTWEAVER_DSH_MODEL"},
            ),
            native_refs=_native_refs(),
            provenance=_provenance(),
        )
        self.assertEqual((timeout.status, timeout.termination), ("timed_out", "timeout"))

        over_budget = normalize_result(
            {
                "status": "completed",
                "result_ref": "native-budget-artifact-ref",
                "evidence_refs": _evidence(),
                "usage": {"model_decisions": 5},
            },
            config=_config(
                "deepseek",
                {"source": "env", "name": "TESTWEAVER_DSH_ENDPOINT"},
                {"source": "env", "name": "TESTWEAVER_DSH_MODEL"},
            ),
            native_refs=_native_refs(),
            provenance=_provenance(),
        )
        self.assertEqual((over_budget.status, over_budget.termination), ("terminated", "budget_exceeded"))

    def test_invalid_result_shape_and_hash_are_rejected(self) -> None:
        config = _config(
            "deepseek",
            {"source": "env", "name": "TESTWEAVER_DSH_ENDPOINT"},
            {"source": "env", "name": "TESTWEAVER_DSH_MODEL"},
        )
        with self.assertRaisesRegex(ResultContractError, "evidence"):
            normalize_result(
                {
                    "status": "completed",
                    "result_ref": "native-result-artifact-ref",
                    "evidence_refs": [],
                    "usage": {},
                },
                config=config,
                native_refs=_native_refs(),
                provenance=_provenance(),
            )
        result = normalize_result(
            {
                "status": "completed",
                "result_ref": "native-result-artifact-ref",
                "evidence_refs": _evidence(),
                "usage": {},
            },
            config=config,
            native_refs=_native_refs(),
            provenance=_provenance(),
        )
        invalid = copy.deepcopy(result.as_dict())
        invalid["result_ref"] = "changed-result-ref"
        with self.assertRaisesRegex(ResultContractError, "content_hash"):
            NormalizedResult.from_mapping(invalid)


class CodexCliContractTests(unittest.TestCase):
    def test_fixed_command_defaults_and_protected_environment_names(self) -> None:
        launch = build_codex_cli_launch()
        self.assertEqual(launch.command[0], CODEX_EXECUTABLE)
        self.assertEqual(
            launch.command,
            (
                "codex-cc",
                "-m",
                "gpt-5.6-luna",
                "-c",
                "model_reasoning_effort=max",
                "-s",
                "read-only",
                "--json",
                "exec",
            ),
        )
        self.assertEqual(launch.model, DEFAULT_MODEL)
        self.assertEqual(launch.reasoning, DEFAULT_REASONING)
        self.assertEqual(
            tuple(ref.location for ref in launch.protected_environment),
            ("HOME", "CODEX_HOME"),
        )
        self.assertNotIn("value", launch.as_dict())

    def test_fixed_defaults_cannot_be_overridden(self) -> None:
        with self.assertRaises(ValueError):
            from testweaver.adapters.codex_cli import CodexCliLaunch

            CodexCliLaunch(model="another-model")


class NativeWorkerAdapterTests(unittest.TestCase):
    def test_preflight_is_names_only_and_supports_dsh_and_codex(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider_directory = Path(directory) / "testweaver-provider"
            provider_directory.mkdir()
            provider_directory.chmod(0o700)
            endpoint_path = provider_directory / "endpoint"
            model_path = provider_directory / "model"
            credential_path = provider_directory / "credential"
            endpoint_path.write_text("https://gateway.invalid/v1", encoding="utf-8")
            model_path.write_text("provider-model", encoding="utf-8")
            credential_path.write_text("credential-value-1234", encoding="utf-8")
            for path in (endpoint_path, model_path, credential_path):
                os.chmod(path, 0o600)

            dsh_profile = DshProviderProfile.aliyun_bailian(
                endpoint_ref={"source": "file", "path": str(endpoint_path)},
                model_ref={"source": "file", "path": str(model_path)},
                credential_ref={"source": "file", "path": str(credential_path)},
            )
            dsh_invocation = prepare_native_worker_invocation(
                assignment=_assignment(),
                config=dsh_profile.as_config(_limits()),
                provenance=_provenance(),
            )

            codex_invocation = prepare_native_worker_invocation(
                assignment=_assignment(),
                config=AdapterConfig.from_mapping(
                    {
                        "adapter_kind": "codex-cli",
                        "route": {
                            **_route(
                                "codex-cc",
                                {"source": "file", "path": str(endpoint_path)},
                                {"source": "env", "name": "CODEX_WORKER_MODEL"},
                            ),
                            "credential": {
                                "source": "env",
                                "name": "TESTWEAVER_CODEX_CREDENTIAL",
                            },
                        },
                        "limits": _limits(),
                    }
                ),
                provenance=_provenance(),
            )

            with patch.dict(
                os.environ,
                {
                    "HOME": "bound",
                    "CODEX_HOME": "bound",
                    "CODEX_WORKER_MODEL": "bound",
                    "TESTWEAVER_CODEX_CREDENTIAL": "bound",
                },
                clear=False,
            ), patch.object(
                adapter_config, "PROTECTED_PROVIDER_DIRECTORY", provider_directory
            ), patch.object(
                adapter_config, "_ADAPTER_FILE_ROOTS", (provider_directory,)
            ):
                dsh_preflight = preflight_native_worker_invocation(dsh_invocation)
                codex_preflight = preflight_native_worker_invocation(codex_invocation)

            self.assertEqual(dsh_preflight.status, "READY")
            self.assertEqual(codex_preflight.status, "READY")
            self.assertEqual(codex_preflight.command[0], "codex-cc")
            self.assertEqual(codex_preflight.command[2], "gpt-5.6-luna")
            self.assertIn("model_reasoning_effort=max", codex_preflight.command)
            self.assertNotIn("value", dsh_preflight.as_dict())
            self.assertNotIn("value", codex_preflight.as_dict())

    def test_preflight_blocks_unallowlisted_dsh_provider_and_environment(self) -> None:
        cases = (
            (
                "provider",
                "unapproved-provider",
                (
                    "TESTWEAVER_DSH_ENDPOINT",
                    "TESTWEAVER_DSH_MODEL",
                    "TESTWEAVER_DSH_CREDENTIAL",
                ),
            ),
            (
                "environment",
                "deepseek",
                ("UNSAFE_DSH_ENDPOINT", "UNSAFE_DSH_MODEL", "UNSAFE_DSH_CREDENTIAL"),
            ),
        )
        for kind, provider, names in cases:
            with self.subTest(kind=kind):
                profile = DshProviderProfile.from_provider(
                    provider,
                    endpoint_ref={"source": "env", "name": names[0]},
                    model_ref={"source": "env", "name": names[1]},
                    credential_ref={"source": "env", "name": names[2]},
                )
                invocation = prepare_native_worker_invocation(
                    assignment=_assignment(),
                    config=profile.as_config(_limits()),
                    provenance=_provenance(),
                )
                with patch.dict(
                    os.environ,
                    {
                        names[0]: "https://deepseek.invalid/v1",
                        names[1]: "deepseek-model",
                        names[2]: "credential-value-1234",
                    },
                    clear=True,
                ):
                    preflight = preflight_native_worker_invocation(invocation)
                self.assertEqual(preflight.status, "BLOCKED")
                self.assertTrue(any("allowlist" in reason for reason in preflight.reasons))

    def test_dsh_preflight_validates_file_values_like_executor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider_directory = Path(directory) / "testweaver-provider"
            provider_directory.mkdir()
            provider_directory.chmod(0o700)
            endpoint = provider_directory / "endpoint"
            model = provider_directory / "model"
            credential = provider_directory / "credential"
            endpoint.write_text("not-an-endpoint", encoding="utf-8")
            model.write_text("deepseek-model", encoding="utf-8")
            credential.write_text("credential-value-1234", encoding="utf-8")
            for path in (endpoint, model, credential):
                path.chmod(0o400)
            profile = DshProviderProfile.deepseek(
                endpoint_ref={"source": "file", "path": str(endpoint)},
                model_ref={"source": "file", "path": str(model)},
                credential_ref={"source": "file", "path": str(credential)},
            )
            invocation = prepare_native_worker_invocation(
                assignment=_assignment(),
                config=profile.as_config(_limits()),
                provenance=_provenance(),
            )
            with patch.object(
                adapter_config, "PROTECTED_PROVIDER_DIRECTORY", provider_directory
            ):
                preflight = preflight_native_worker_invocation(invocation)
        self.assertEqual(preflight.status, "BLOCKED")
        self.assertTrue(any("value" in reason for reason in preflight.reasons))

    def test_codex_preflight_uses_executor_file_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory) / "codex-endpoint"
            outside.write_text("codex-endpoint", encoding="utf-8")
            outside.chmod(0o600)
            invocation = prepare_native_worker_invocation(
                assignment=_assignment(),
                config=AdapterConfig.from_mapping(
                    {
                        "adapter_kind": "codex-cli",
                        "route": {
                            **_route(
                                "codex-cc",
                                {"source": "file", "path": str(outside)},
                                {"source": "env", "name": "CODEX_WORKER_MODEL"},
                            ),
                            "credential": {
                                "source": "env",
                                "name": "TESTWEAVER_CODEX_CREDENTIAL",
                            },
                        },
                        "limits": _limits(),
                    }
                ),
                provenance=_provenance(),
            )
            with patch.dict(
                os.environ,
                {
                    "HOME": "bound",
                    "CODEX_HOME": "bound",
                    "CODEX_WORKER_MODEL": "gpt-5.6-luna",
                    "TESTWEAVER_CODEX_CREDENTIAL": "credential-value-1234",
                },
                clear=True,
            ):
                preflight = preflight_native_worker_invocation(invocation)
        self.assertEqual(preflight.status, "BLOCKED")
        self.assertTrue(any("outside_protected_roots" in reason for reason in preflight.reasons))

    def test_dsh_preflight_blocks_aggregate_provider_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider_directory = Path(directory) / "testweaver-provider"
            provider_directory.mkdir()
            provider_directory.chmod(0o700)
            aggregate = Path(directory) / "providers.env"
            aggregate.write_text("AGENTTEAMS_BAILIAN_MODEL=not-a-single-ref", encoding="utf-8")
            aggregate.chmod(0o600)
            profile = DshProviderProfile.aliyun_bailian(
                endpoint_ref={"source": "file", "path": str(aggregate)},
                model_ref={"source": "file", "path": str(aggregate)},
                credential_ref={"source": "file", "path": str(aggregate)},
            )
            invocation = prepare_native_worker_invocation(
                assignment=_assignment(),
                config=profile.as_config(_limits()),
                provenance=_provenance(),
            )
            with patch.object(adapter_config, "PROTECTED_PROVIDER_DIRECTORY", provider_directory):
                preflight = preflight_native_worker_invocation(invocation)
            self.assertEqual(preflight.status, "BLOCKED")
            self.assertTrue(any("dedicated" in reason for reason in preflight.reasons))

    def test_dsh_has_explicit_deepseek_and_bailian_profiles_without_values(self) -> None:
        self.assertEqual(DSH_PROVIDER_PROFILES, frozenset({"deepseek", "aliyun-bailian"}))
        deepseek = DshProviderProfile.deepseek(
            endpoint_ref={"source": "env", "name": "TESTWEAVER_DSH_ENDPOINT"},
            model_ref={"source": "file", "path": "/etc/agentteams/deepseek-model"},
            credential_ref={"source": "env", "name": "TESTWEAVER_DSH_CREDENTIAL"},
        )
        bailian = DshProviderProfile.aliyun_bailian(
            endpoint_ref={"source": "file", "path": "/etc/agentteams/bailian-endpoint"},
            model_ref={"source": "env", "name": "TESTWEAVER_BAILIAN_MODEL"},
            credential_ref={"source": "env", "name": "TESTWEAVER_BAILIAN_CREDENTIAL"},
        )
        self.assertEqual(deepseek.provider, "deepseek")
        self.assertEqual(bailian.provider, "aliyun-bailian")
        self.assertNotIn("value", deepseek.as_dict())
        self.assertNotIn("value", bailian.as_dict())
        self.assertEqual(deepseek.as_config(_limits()).adapter_kind, "dsh")
        self.assertEqual(bailian.as_config(_limits()).adapter_kind, "dsh")
        generic = DshProviderProfile.from_provider(
            "vendor-openai-compatible",
            endpoint_ref={"source": "env", "name": "TESTWEAVER_GENERIC_ENDPOINT"},
            model_ref={"source": "env", "name": "TESTWEAVER_GENERIC_MODEL"},
            credential_ref={"source": "env", "name": "TESTWEAVER_GENERIC_CREDENTIAL"},
        )
        self.assertEqual(generic.provider, "vendor-openai-compatible")
        self.assertEqual(generic.as_config(_limits()).route.provider, "vendor-openai-compatible")

    def test_native_binding_preserves_leader_assignment_and_normalizes_result(self) -> None:
        assignment = NativeWorkerAssignment(
            project_id="native-project-ref",
            task_id="native-task-ref",
            room_id="!native-room-ref:example.invalid",
            worker_id="native-worker-ref",
            leader_id="native-leader-ref",
            task_ref="native-task-spec-ref",
        )
        profile = DshProviderProfile.deepseek(
            endpoint_ref={"source": "env", "name": "TESTWEAVER_DSH_ENDPOINT"},
            model_ref={"source": "env", "name": "TESTWEAVER_DSH_MODEL"},
            credential_ref={"source": "env", "name": "TESTWEAVER_DSH_CREDENTIAL"},
        )
        invocation = prepare_native_worker_invocation(
            assignment=assignment,
            config=profile.as_config(_limits()),
            provenance=_provenance(),
        )
        metadata = invocation.as_dict()
        self.assertEqual(metadata["native_assignment"]["leader_id"], "native-leader-ref")
        self.assertTrue(metadata["native_assignment"]["read_only"])
        self.assertEqual(metadata["lifecycle_owner"], "agentteams-native-worker")
        self.assertEqual(metadata["dispatch_owner"], "native-leader")

        result = invocation.normalize_result(
            {
                "status": "completed",
                "result_ref": "native-result-artifact-ref",
                "evidence_refs": _evidence(),
                "usage": {"model_decisions": 1, "tool_calls": 2},
            },
            latency_seconds=1.75,
        )
        payload = result.as_dict()
        self.assertIsInstance(result, WorkerResult)
        self.assertEqual(result.provider, "deepseek")
        self.assertEqual(result.model_ref.location, "TESTWEAVER_DSH_MODEL")
        self.assertEqual(result.latency_seconds, 1.75)
        self.assertEqual(payload["route"]["provider"], "deepseek")
        self.assertEqual(payload["route"]["model"]["name"], "TESTWEAVER_DSH_MODEL")
        self.assertEqual(payload["elapsed_seconds"], 1.75)
        self.assertEqual(payload["provenance"]["source"], "external-result-receipt")

    def test_codex_binding_is_metadata_only_and_uses_approved_launch(self) -> None:
        assignment = NativeWorkerAssignment(
            project_id="native-project-ref",
            task_id="native-task-ref",
            room_id="!native-room-ref:example.invalid",
            worker_id="native-worker-ref",
            leader_id="native-leader-ref",
            task_ref="native-task-spec-ref",
        )
        invocation = prepare_native_worker_invocation(
            assignment=assignment,
            config=AdapterConfig.from_mapping(
                {
                    "adapter_kind": "codex-cli",
                    "route": _route(
                        "codex-cc",
                        {"source": "file", "path": "/etc/agentteams/codex-endpoint"},
                        {"source": "env", "name": "CODEX_WORKER_MODEL"},
                    ),
                    "limits": _limits(),
                }
            ),
            provenance=_provenance(),
        )
        self.assertEqual(
            invocation.as_dict()["launch"]["command"][0:5],
            ["codex-cc", "-m", "gpt-5.6-luna", "-c", "model_reasoning_effort=max"],
        )
        self.assertNotIn("process", invocation.as_dict())

    def test_binding_source_has_no_scheduler_or_process_surface(self) -> None:
        from pathlib import Path

        source = Path(__import__("testweaver.adapters.native_worker", fromlist=["__file__"]).__file__).read_text(
            encoding="utf-8"
        )
        for forbidden in ("subprocess", "create_project", "delegate_task", "room_send", "scheduler"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
