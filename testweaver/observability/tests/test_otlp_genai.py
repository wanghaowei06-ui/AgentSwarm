from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from testweaver.observability.otlp_genai import (
    EvidenceRef,
    GenAIContext,
    LoongSuiteOtlpBinding,
    OtlpResponse,
    build_otlp_payload,
    emit_genai_span,
    load_loongsuite_otlp_binding,
)
from testweaver.observability.readonly_query import Correlation


_HASH = "sha256:" + "a" * 64


def _context() -> GenAIContext:
    return GenAIContext(
        correlation=Correlation("campaign-ref", "run-ref", "pg-ref", _HASH),
        agent_id="worker-ref",
        task_id="task-ref",
        skill="skill-ref",
        skill_version="commit-ref",
        provider="provider-ref",
        model="model-ref",
        evidence_refs=(EvidenceRef("evidence/ref", _HASH),),
        usage={"input_tokens": 3, "output_tokens": 5, "total_tokens": 8},
        latency_ms=12.5,
    )


class OtlpGenAIContractTests(unittest.TestCase):
    def test_payload_contains_correlation_and_no_content(self) -> None:
        payload, trace_id, span_id = build_otlp_payload(
            _context(), trace_id="b" * 32, span_id="c" * 16, started_ns=10, ended_ns=20
        )

        attributes = {
            item["key"]: next(iter(item["value"].values()))
            for item in payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]
        }
        evidence_hashes = attributes["testweaver.evidence.hashes"]["values"]
        self.assertEqual((trace_id, span_id), ("b" * 32, "c" * 16))
        self.assertEqual(attributes["testweaver.run_id"], "run-ref")
        self.assertEqual(evidence_hashes[0]["stringValue"], _HASH)
        self.assertEqual(attributes["gen_ai.usage.total_tokens"], "8")
        self.assertNotIn("prompt", json.dumps(payload))
        self.assertNotIn("response", json.dumps(payload))

    def test_success_is_export_metadata_not_a_live_claim(self) -> None:
        requests: list[tuple[str, dict[str, str], bytes]] = []

        def transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> OtlpResponse:
            del timeout
            requests.append((url, headers, body))
            return OtlpResponse(200, b"{}")

        receipt = emit_genai_span(
            endpoint="http://127.0.0.1:4318/v1/traces",
            context=_context(),
            transport=transport,
        )

        self.assertEqual(receipt.status, "EXPORT_ACCEPTED")
        self.assertFalse(receipt.live_claim)
        self.assertEqual(receipt.response_status, 200)
        self.assertEqual(requests[0][0], "http://127.0.0.1:4318/v1/traces")
        self.assertEqual(requests[0][1]["Content-Type"], "application/json")
        self.assertNotIn("body", receipt.as_dict())
        self.assertNotIn("Authorization", receipt.as_dict())

    def test_export_failure_is_hash_only_and_fail_closed(self) -> None:
        receipt = emit_genai_span(
            endpoint="http://127.0.0.1:4318/v1/traces",
            context=_context(),
            transport=lambda url, headers, body, timeout: OtlpResponse(403, b"credential rejected"),
        )

        self.assertEqual(receipt.status, "BLOCKED")
        self.assertEqual(receipt.reason, "otlp_export_non_success")
        self.assertEqual(receipt.response_bytes, len(b"credential rejected"))
        serialized = json.dumps(receipt.as_dict(), sort_keys=True)
        self.assertNotIn("credential rejected", serialized)
        self.assertNotIn("body", serialized)

    def test_header_provider_failure_never_calls_transport(self) -> None:
        calls: list[bool] = []

        def transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> OtlpResponse:
            del url, headers, body, timeout
            calls.append(True)
            return OtlpResponse(200, b"{}")

        receipt = emit_genai_span(
            endpoint="http://127.0.0.1:4318/v1/traces",
            context=_context(),
            header_provider=lambda: (_ for _ in ()).throw(RuntimeError("secret-free fixture error")),
            transport=transport,
        )

        self.assertEqual(receipt.reason, "auth_header_provider_failed")
        self.assertEqual(calls, [])

    def test_loongsuite_binding_keeps_license_only_in_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "cms": {
                            "endpoint": "https://project.cn-beijing.log.aliyuncs.com/apm/trace/opentelemetry",
                            "licenseKey": "license-fixture",
                            "workspace": "workspace-ref",
                        }
                    }
                ),
                encoding="utf-8",
            )
            os.chmod(path, 0o600)

            binding = load_loongsuite_otlp_binding(path)

            self.assertIsInstance(binding, LoongSuiteOtlpBinding)
            self.assertEqual(
                binding.endpoint,
                "https://project.cn-beijing.log.aliyuncs.com/apm/trace/opentelemetry/v1/traces",
            )
            self.assertNotIn("license-fixture", repr(binding))
            self.assertNotIn("license-fixture", json.dumps(binding.names_only()))
            self.assertEqual(binding.headers()["x-arms-license-key"], "license-fixture")

    def test_non_owner_loongsuite_config_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("{}", encoding="utf-8")
            os.chmod(path, 0o644)
            with self.assertRaisesRegex(ValueError, "owner-only"):
                load_loongsuite_otlp_binding(path)


if __name__ == "__main__":
    unittest.main()
