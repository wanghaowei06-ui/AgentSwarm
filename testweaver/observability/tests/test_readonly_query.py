"""Focused contract tests for the read-only AgentLoop/OTel query adapter."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from testweaver.observability.readonly_query import (
    Correlation,
    EndpointReference,
    HttpResponse,
    ProtectedConfigRef,
    ReadOnlyQueryClient,
    verify_hero_correlation,
)


_CONTENT_HASH = "sha256:" + "a" * 64


def _hero_export(source: str, **overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "source": source,
        "campaign_id": "campaign-ref",
        "run_id": "run-ref",
        "pg_revision": "pg-revision-ref",
        "content_hash": _CONTENT_HASH,
        "trace_id": "b" * 32,
        "provider": "provider-ref",
        "model": "model-ref",
        "usage": {"total_tokens": 10},
        "latency_ms": 12.5,
        "synthetic": False,
    }
    value.update(overrides)
    return value


def _correlation() -> Correlation:
    return Correlation(
        campaign_id="campaign-ref",
        run_id="run-ref",
        pg_revision="pg-revision-ref",
        content_hash=_CONTENT_HASH,
    )


def _test_credential_ref() -> ProtectedConfigRef:
    """Use only this test file as a location reference; never load it."""

    return ProtectedConfigRef(path=Path(__file__).resolve(), owner_only=False)


class ReadOnlyQueryContractTests(unittest.TestCase):
    def test_same_real_hero_tuple_verifies_otel_and_agentloop_exports(self) -> None:
        result = verify_hero_correlation(
            _hero_export("otel_export"), _hero_export("agentloop_query")
        )

        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(
            result["authority_tuple"],
            {
                "campaign_id": "campaign-ref",
                "run_id": "run-ref",
                "pg_revision": "pg-revision-ref",
                "content_hash": _CONTENT_HASH,
                "trace_id": "b" * 32,
            },
        )
        self.assertEqual(result["sources"], ["otel_export", "agentloop_query"])

    def test_hero_verifier_rejects_mismatched_or_synthetic_observations(self) -> None:
        mismatch = verify_hero_correlation(
            _hero_export("otel_export"),
            _hero_export("agentloop_query", run_id="other-run"),
        )
        self.assertEqual(mismatch["status"], "BLOCKED")

        synthetic = verify_hero_correlation(
            _hero_export("otel_export", synthetic=True), _hero_export("agentloop_query")
        )
        self.assertEqual(synthetic["status"], "BLOCKED")

    def test_hero_verifier_keeps_missing_observations_unavailable(self) -> None:
        missing = _hero_export("agentloop_query")
        del missing["usage"]
        result = verify_hero_correlation(_hero_export("otel_export"), missing)

        self.assertEqual(result["status"], "NOT_AVAILABLE")

    def test_hero_verifier_keeps_missing_source_unavailable(self) -> None:
        missing_source = _hero_export("agentloop_query")
        del missing_source["source"]
        result = verify_hero_correlation(_hero_export("otel_export"), missing_source)

        self.assertEqual(result["status"], "NOT_AVAILABLE")

    def test_hero_verifier_rejects_nonfinite_latency_and_blank_identity(self) -> None:
        nonfinite = verify_hero_correlation(
            _hero_export("otel_export", latency_ms=float("nan")),
            _hero_export("agentloop_query"),
        )
        blank_provider = verify_hero_correlation(
            _hero_export("otel_export", provider="   "),
            _hero_export("agentloop_query"),
        )
        self.assertEqual(nonfinite["status"], "BLOCKED")
        self.assertEqual(blank_provider["status"], "BLOCKED")
    def test_protected_reference_inspects_metadata_without_loading_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "protected.env"
            path.write_text("REFERENCE_ONLY=present\n", encoding="utf-8")
            os.chmod(path, 0o600)
            reference = ProtectedConfigRef(
                path=path,
                variable_names=("REFERENCE_ONLY",),
            )

            status = reference.inspect()

            self.assertTrue(status.exists)
            self.assertTrue(status.usable)
            self.assertEqual(status.variable_names, ("REFERENCE_ONLY",))
            self.assertEqual(status.mode, 0o600)

    def test_missing_protected_reference_is_blocked_before_transport(self) -> None:
        calls: list[tuple[str, str]] = []

        def transport(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
            del headers, timeout
            calls.append(("called", url))
            return HttpResponse(status_code=200, body=b"{}")

        client = ReadOnlyQueryClient(
            endpoint=EndpointReference("agentloop", "https://agentloop.example.invalid"),
            credential_ref=ProtectedConfigRef(
                path=Path("/definitely/missing/protected-config"),
                variable_names=("AGENTLOOP_QUERY_CREDENTIAL",),
            ),
            transport=transport,
        )

        receipt = client.query_json(
            operation="evaluation_task",
            path="/api/v1/evaluation-task/space/task",
            correlation=_correlation(),
        )

        self.assertEqual(receipt.status, "BLOCKED")
        self.assertEqual(calls, [])
        self.assertTrue(receipt.read_only)

    def test_get_response_is_verified_only_when_all_correlation_anchors_match(self) -> None:
        requests: list[tuple[str, str]] = []

        def transport(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
            del headers, timeout
            requests.append(("GET", url))
            body = {
                "campaignId": "campaign-ref",
                "runId": "run-ref",
                "pgRevision": "pg-revision-ref",
                "contentHash": _CONTENT_HASH,
            }
            return HttpResponse(status_code=200, body=json.dumps(body).encode("utf-8"))

        client = ReadOnlyQueryClient(
            endpoint=EndpointReference(
                "local-query",
                "http://127.0.0.1:18080",
                auth_required=False,
            ),
            transport=transport,
        )

        receipt = client.query_json(
            operation="evaluation_task",
            path="/api/v1/evaluation-task/space/task",
            correlation=_correlation(),
        )

        self.assertEqual(receipt.status, "VERIFIED")
        self.assertEqual(receipt.http_method, "GET")
        self.assertEqual(
            receipt.matched_fields,
            ("campaign_id", "run_id", "pg_revision", "content_hash"),
        )
        self.assertEqual(requests[0][0], "GET")
        self.assertNotIn("Authorization", receipt.as_dict())

    def test_missing_correlation_anchor_is_not_verified(self) -> None:
        def transport(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
            del url, headers, timeout
            body: dict[str, Any] = {
                "campaignId": "campaign-ref",
                "runId": "run-ref",
                "pgRevision": "pg-revision-ref",
            }
            return HttpResponse(status_code=200, body=json.dumps(body).encode("utf-8"))

        client = ReadOnlyQueryClient(
            endpoint=EndpointReference(
                "local-query",
                "http://127.0.0.1:18080",
                auth_required=False,
            ),
            transport=transport,
        )

        receipt = client.query_json(
            operation="otel_trace",
            path="/query",
            correlation=_correlation(),
        )

        self.assertEqual(receipt.status, "NOT_VERIFIED")
        self.assertNotIn("content_hash", receipt.matched_fields)

    def test_agentloop_helpers_use_only_read_methods_and_expected_paths(self) -> None:
        requests: list[str] = []

        def transport(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
            del headers, timeout
            requests.append(url)
            return HttpResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "campaign_id": "campaign-ref",
                        "run_id": "run-ref",
                        "pg_revision": "pg-revision-ref",
                        "content_hash": _CONTENT_HASH,
                    }
                ).encode("utf-8"),
            )

        client = ReadOnlyQueryClient(
            endpoint=EndpointReference("agentloop", "https://agentloop.example.invalid"),
            credential_ref=_test_credential_ref(),
            header_provider=lambda: {},
            transport=transport,
        )

        task_receipt = client.query_agentloop_evaluation_task(
            agent_space="space",
            task_id="task",
            correlation=_correlation(),
        )
        runs_receipt = client.query_agentloop_evaluation_runs(
            agent_space="space",
            task_id="task",
            correlation=_correlation(),
        )
        dataset_receipt = client.query_agentloop_dataset(
            agent_space="space",
            dataset_id="gold",
            correlation=_correlation(),
        )

        self.assertEqual(
            [task_receipt.status, runs_receipt.status, dataset_receipt.status],
            ["VERIFIED", "VERIFIED", "VERIFIED"],
        )
        self.assertEqual(
            requests,
            [
                "https://agentloop.example.invalid/api/v1/evaluation-task/space/task",
                "https://agentloop.example.invalid/api/v1/evaluation-task/space/task/runs",
                "https://agentloop.example.invalid/agentspace/space/dataset/gold",
            ],
        )

    def test_otel_export_path_cannot_be_used_as_a_query_path(self) -> None:
        client = ReadOnlyQueryClient(
            endpoint=EndpointReference("otel", "https://collector.example.invalid/apm/trace/opentelemetry"),
            credential_ref=_test_credential_ref(),
            header_provider=lambda: {},
            transport=lambda url, headers, timeout: HttpResponse(200, b"{}"),
        )

        receipt = client.query_otel_trace(
            trace_id="a" * 32,
            correlation=_correlation(),
            query_path="/v1/traces",
        )

        self.assertEqual(receipt.status, "BLOCKED")

    def test_otel_query_requires_and_correlates_trace_id(self) -> None:
        requests: list[str] = []

        def transport(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
            del headers, timeout
            requests.append(url)
            return HttpResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "traceId": "b" * 32,
                        "campaign_id": "campaign-ref",
                        "run_id": "run-ref",
                        "pg_revision": "pg-revision-ref",
                        "content_hash": _CONTENT_HASH,
                    }
                ).encode("utf-8"),
            )

        client = ReadOnlyQueryClient(
            endpoint=EndpointReference(
                "otel",
                "https://collector.example.invalid",
                query_path="/trace-query",
            ),
            credential_ref=_test_credential_ref(),
            header_provider=lambda: {},
            transport=transport,
        )

        receipt = client.query_otel_trace(
            trace_id="b" * 32,
            correlation=_correlation(),
        )

        self.assertEqual(receipt.status, "VERIFIED")
        self.assertIn("trace_id", receipt.matched_fields)
        self.assertEqual(requests, ["https://collector.example.invalid/trace-query?traceId=" + "b" * 32])


if __name__ == "__main__":
    unittest.main()
