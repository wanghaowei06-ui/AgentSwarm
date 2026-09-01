"""Focused local adapter checks; fixtures are not LIVE evidence."""

from __future__ import annotations

import copy
import unittest

from testweaver.adapters.codex_cli import (
    CODEX_EXECUTABLE,
    DEFAULT_MODEL,
    DEFAULT_REASONING,
    build_codex_cli_launch,
)
from testweaver.adapters.config import AdapterConfig, AdapterConfigError
from testweaver.adapters.result import (
    EvidenceReference,
    NativeReferences,
    NormalizedResult,
    Provenance,
    ResultContractError,
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
        self.assertEqual(launch.command, ("codex-cc", "app-server", "--listen", "stdio://"))
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


if __name__ == "__main__":
    unittest.main()
