from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

from testweaver.authority import digest_bytes
from testweaver.contracts.validator import canonical_hash
from testweaver.observability.otlp_genai import OtlpReceipt, OtlpResponse


SCRIPT = __import__("pathlib").Path(__file__).resolve().parents[1] / "testweaver-agentloop-bridge.py"
SPEC = importlib.util.spec_from_file_location("testweaver_agentloop_bridge", SCRIPT)
assert SPEC and SPEC.loader
bridge = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bridge
SPEC.loader.exec_module(bridge)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def _turn(**changes: Any) -> bytes:
    value: dict[str, Any] = {
        "schema_version": "testweaver.provider-turn/v1",
        "campaign_id": "campaign-ref",
        "run_id": "run-ref",
        "trace_id": "0123456789abcdef0123456789abcdef",
        "pg_revision": 7,
        "content_hash": HASH_A,
        "agent": {"id": "agent-ref"},
        "task": {"id": "task-ref"},
        "skill": {
            "name": "skill-ref",
            "version": "v1",
            "hash": HASH_B,
            "invoke_ref": "skill-invoke-ref",
        },
        "provider": "deepseek",
        "model": "model-ref",
        "usage": {"input_tokens": 3, "output_tokens": 5, "total_tokens": 8},
        "latency_ms": 12.5,
        "source_ref": "collector-turn-ref",
        "source_hash": HASH_A,
        "attestation_ref": "collector-attestation-ref",
        "attestation_hash": HASH_B,
        "synthetic": False,
    }
    value.update(changes)
    value["record_hash"] = canonical_hash(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


class XTraceFixture:
    def __init__(self, status: str = "API_QUERY_VERIFIED") -> None:
        self.status = status
        self.calls: list[dict[str, Any]] = []

    def get_trace(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(
            status=self.status,
            attempt_count=kwargs.get("max_attempts", 0),
            response_status=200,
            response_hash=HASH_B,
            request_id_hash=HASH_A,
            trace_id_hash=digest_bytes(kwargs["trace_id"].encode()),
            span_count=1,
            trace_id_matched=self.status == "API_QUERY_VERIFIED",
            authority_anchor_matches={
                "campaign_id": self.status == "API_QUERY_VERIFIED",
                "run_id": self.status == "API_QUERY_VERIFIED",
                "pg_revision": self.status == "API_QUERY_VERIFIED",
                "content_hash": self.status == "API_QUERY_VERIFIED",
            },
            observed_at="2026-09-03T00:00:00Z",
            reason=None if self.status == "API_QUERY_VERIFIED" else "TRACE_NOT_FOUND",
            content_hash=HASH_B,
        )


def _otlp_transport(calls: list[tuple[str, dict[str, str], bytes]]) -> Any:
    def send(url: str, headers: dict[str, str], body: bytes, timeout: float) -> OtlpResponse:
        del timeout
        calls.append((url, headers, body))
        return OtlpResponse(200, b"ok")

    return send


def _fake_emit(
    *,
    endpoint: str,
    context: Any,
    trace_id: str | None = None,
    span_id: str | None = None,
    header_provider: Any = None,
    transport: Any = None,
    timeout_seconds: float = 10.0,
) -> OtlpReceipt:
    del context
    headers = {"Content-Type": "application/x-protobuf"}
    if header_provider is not None:
        headers.update(header_provider())
    body = b"protobuf-fixture"
    response = transport(endpoint, headers, body, timeout_seconds) if transport else OtlpResponse(200, b"ok")
    accepted = 200 <= response.status_code < 300
    return OtlpReceipt(
        "testweaver.otlp-receipt/v1",
        "EXPORT_ACCEPTED" if accepted else "BLOCKED",
        endpoint,
        "POST",
        True,
        False,
        trace_id or "0" * 32,
        span_id or "1" * 16,
        digest_bytes(body),
        response.status_code,
        digest_bytes(response.body),
        len(response.body),
        None if accepted else "otlp_export_non_success",
    )


class AgentLoopBridgeTests(unittest.TestCase):
    def test_input_requires_attested_sealed_turn_and_rejects_live_claim(self) -> None:
        with self.assertRaisesRegex(bridge.BridgeInputError, "CALLER_LIVE_CLAIM_REJECTED"):
            bridge.parse_provider_turn(_turn(live_claim=True))
        with self.assertRaisesRegex(bridge.BridgeInputError, "ATTESTATION_INVALID"):
            bridge.parse_provider_turn(_turn(attestation_hash=None))

    def test_missing_anchor_is_rejected_without_exposing_input(self) -> None:
        raw = json.loads(_turn())
        raw.pop("trace_id")
        raw["record_hash"] = canonical_hash(raw)
        with self.assertRaisesRegex(bridge.BridgeInputError, "MISSING_ANCHOR"):
            bridge.parse_provider_turn(json.dumps(raw).encode())

    def test_projection_preserves_trace_and_returns_hash_only_receipt(self) -> None:
        calls: list[tuple[str, dict[str, str], bytes]] = []
        xtrace = XTraceFixture()
        with mock.patch.object(bridge, "emit_genai_span", side_effect=_fake_emit):
            receipt = bridge.project_provider_turn(
                _turn(),
                otlp_endpoint="https://collector.example.invalid/v1/traces",
                otlp_header_provider=lambda: {"x-test-auth": "protected-secret-sentinel"},
                otlp_transport=_otlp_transport(calls),
                xtrace_client=xtrace,
                clock=lambda: "2026-09-03T00:00:00Z",
            )

        self.assertEqual(receipt["classification"], "LOCAL_PROJECTED")
        self.assertEqual(receipt["agentloop"]["status"], "NOT_QUERIED")
        self.assertFalse(receipt["live_claim"])
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][0].endswith("/v1/traces"))
        self.assertEqual(calls[0][1]["x-test-auth"], "protected-secret-sentinel")
        self.assertTrue(receipt["otlp"]["trace_id_hash"].startswith("sha256:"))
        serialized = json.dumps(receipt, sort_keys=True)
        for marker in (
            "protected-secret-sentinel",
            "collector-turn-ref",
            "model-ref",
            "prompt",
            "response-body-sentinel",
        ):
            self.assertNotIn(marker, serialized)
        self.assertEqual(xtrace.calls[0]["trace_id"], "0123456789abcdef0123456789abcdef")
        self.assertEqual(xtrace.calls[0]["max_attempts"], 3)
        self.assertEqual(xtrace.calls[0]["max_elapsed_seconds"], 90.0)
        self.assertNotIn("NATIVE_LIVE_TRACE", serialized)

    def test_otlp_failure_is_blocked_and_xtrace_is_not_called(self) -> None:
        xtrace = XTraceFixture()
        with mock.patch.object(bridge, "emit_genai_span", side_effect=_fake_emit):
            receipt = bridge.project_provider_turn(
                _turn(),
                otlp_endpoint="https://collector.example.invalid/v1/traces",
                otlp_transport=lambda *_: OtlpResponse(503, b"provider-body-sentinel"),
                xtrace_client=xtrace,
            )

        self.assertEqual(receipt["classification"], "BLOCKED")
        self.assertEqual(receipt["reason"], "OTLP_EXPORT_FAILED")
        self.assertEqual(xtrace.calls, [])
        self.assertNotIn("provider-body-sentinel", json.dumps(receipt))

    def test_xtrace_partial_match_is_not_verified(self) -> None:
        with mock.patch.object(bridge, "emit_genai_span", side_effect=_fake_emit):
            receipt = bridge.project_provider_turn(
                _turn(),
                otlp_endpoint="https://collector.example.invalid/v1/traces",
                otlp_transport=_otlp_transport([]),
                xtrace_client=XTraceFixture("NOT_VERIFIED"),
            )
        self.assertEqual(receipt["classification"], "NOT_VERIFIED")

    def test_optional_agentloop_query_must_be_terminal_owned_and_nonempty(self) -> None:
        with mock.patch.object(bridge, "emit_genai_span", side_effect=_fake_emit):
            receipt = bridge.project_provider_turn(
                _turn(),
                otlp_endpoint="https://collector.example.invalid/v1/traces",
                otlp_transport=_otlp_transport([]),
                xtrace_client=XTraceFixture(),
                agentloop_query=lambda _turn: bridge.AgentLoopQueryVerification(
                    status="NOT_VERIFIED",
                    task_receipt_hash=HASH_A,
                    runs_receipt_hash=HASH_B,
                    ownership_verified=False,
                    scope_verified=False,
                    evidence_verified=False,
                    terminal=False,
                    result_count=0,
                    successful_result_count=0,
                    observed_at="2026-09-03T00:00:00Z",
                    content_hash=canonical_hash(
                        {
                            "status": "NOT_VERIFIED",
                            "task_receipt_hash": HASH_A,
                            "runs_receipt_hash": HASH_B,
                            "ownership_verified": False,
                            "scope_verified": False,
                            "evidence_verified": False,
                            "terminal": False,
                            "result_count": 0,
                            "successful_result_count": 0,
                            "observed_at": "2026-09-03T00:00:00Z",
                        }
                    ),
                ),
            )
        self.assertEqual(receipt["classification"], "NOT_VERIFIED")
        self.assertEqual(receipt["agentloop"]["status"], "NOT_VERIFIED")

    def test_optional_agentloop_query_verifies_only_a_completed_nonempty_result(self) -> None:
        values = {
            "status": "API_QUERY_VERIFIED",
            "task_receipt_hash": HASH_A,
            "runs_receipt_hash": HASH_B,
            "ownership_verified": True,
            "scope_verified": True,
            "evidence_verified": True,
            "terminal": True,
            "result_count": 1,
            "successful_result_count": 1,
            "observed_at": "2026-09-03T00:00:00Z",
        }
        verification = bridge.AgentLoopQueryVerification(
            **values,
            content_hash=canonical_hash(values),
        )
        with mock.patch.object(bridge, "emit_genai_span", side_effect=_fake_emit):
            receipt = bridge.project_provider_turn(
                _turn(),
                otlp_endpoint="https://collector.example.invalid/v1/traces",
                otlp_transport=_otlp_transport([]),
                xtrace_client=XTraceFixture(),
                agentloop_query=lambda _turn: verification,
            )
        self.assertEqual(receipt["classification"], "PROJECTED_LIVE_TRACE")
        self.assertEqual(receipt["agentloop"]["successful_result_count"], 1)

    def test_agentloop_verification_requires_full_provider_turn_binding(self) -> None:
        values = {
            "status": "API_QUERY_VERIFIED",
            "task_receipt_hash": HASH_A,
            "runs_receipt_hash": HASH_B,
            "ownership_verified": True,
            "scope_verified": True,
            "evidence_verified": False,
            "terminal": True,
            "result_count": 1,
            "successful_result_count": 1,
            "observed_at": "2026-09-03T00:00:00Z",
        }
        verification = bridge.AgentLoopQueryVerification(
            **values, content_hash=canonical_hash(values)
        )
        with mock.patch.object(bridge, "emit_genai_span", side_effect=_fake_emit):
            receipt = bridge.project_provider_turn(
                _turn(),
                otlp_endpoint="https://collector.example.invalid/v1/traces",
                otlp_transport=_otlp_transport([]),
                xtrace_client=XTraceFixture(),
                agentloop_query=lambda _turn: verification,
            )
        self.assertEqual(receipt["classification"], "NOT_VERIFIED")
        self.assertEqual(receipt["reason"], "AGENTLOOP_NOT_VERIFIED")

    def test_agentloop_cli_requires_sts_role_and_caches_temporary_credential(self) -> None:
        missing_role = SimpleNamespace(
            agentloop_endpoint="https://agentloop.cn-beijing.aliyuncs.com",
            agentloop_agent_space="space-ref",
            agentloop_region="cn-beijing",
            agentloop_task_id="evaluation-task-ref",
            agentloop_role_arn=None,
            agentloop_role_session_name=None,
            credential_ref=__import__("pathlib").Path("/protected/AccessKey.csv"),
        )
        unavailable = bridge._agentloop_query_callback(missing_role)
        self.assertIsNotNone(unavailable)
        with self.assertRaisesRegex(bridge.BridgeInputError, "AGENTLOOP_CONFIG_UNAVAILABLE"):
            unavailable(bridge.parse_provider_turn(_turn()))  # type: ignore[misc]

        args = SimpleNamespace(
            agentloop_endpoint="https://agentloop.cn-beijing.aliyuncs.com",
            agentloop_agent_space="space-ref",
            agentloop_region="cn-beijing",
            agentloop_task_id="evaluation-task-ref",
            agentloop_role_arn="acs:ram::1234567890123456:role/testweaver-readonly",
            agentloop_role_session_name="testweaver-readback",
            credential_ref=__import__("pathlib").Path("/protected/AccessKey.csv"),
        )
        temporary = object()
        with (
            mock.patch.object(bridge, "load_protected_csv_credential", return_value=object()),
            mock.patch.object(bridge, "assume_role_credential", return_value=temporary) as assume,
            mock.patch.object(bridge, "AgentLoopClient") as client_type,
        ):
            callback = bridge._agentloop_query_callback(args)
            credential_callback = client_type.call_args.args[2]
            first = credential_callback()
            second = credential_callback()

        self.assertIsNotNone(callback)
        self.assertIs(first.material, temporary)
        self.assertIs(second.material, temporary)
        self.assertEqual(first.protected_ref, second.protected_ref)
        self.assertNotIn(args.agentloop_role_arn, first.protected_ref)
        self.assertNotIn("AccessKey", first.protected_ref)
        assume.assert_called_once()

    def test_record_hash_and_unknown_content_are_fail_closed(self) -> None:
        raw = json.loads(_turn())
        raw["record_hash"] = HASH_B
        with self.assertRaisesRegex(bridge.BridgeInputError, "RECORD_NOT_SEALED"):
            bridge.parse_provider_turn(json.dumps(raw).encode())

        raw = json.loads(_turn())
        raw["prompt"] = "do-not-store"
        raw["record_hash"] = canonical_hash(
            {key: value for key, value in raw.items() if key != "record_hash"}
        )
        with self.assertRaisesRegex(bridge.BridgeInputError, "UNSUPPORTED_FIELD"):
            bridge.parse_provider_turn(json.dumps(raw).encode())


if __name__ == "__main__":
    unittest.main()
