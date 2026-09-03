from __future__ import annotations

import hashlib
import json
import unittest

from testweaver.authority import HumanReadbackAttestation
from testweaver.observability import Correlation, QueryReceipt
from testweaver.skillops import (
    ExternalReadback,
    SkillOpsError,
    agentloop_readback_from_observability,
    matrix_readback_from_authority,
)


def _hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class ReadbackProvenanceTests(unittest.TestCase):
    def test_caller_supplied_bytes_are_always_unattested_partial(self) -> None:
        token = ExternalReadback.from_raw(
            source="matrix", ref="matrix:event", raw=b"caller transcript"
        )
        self.assertEqual(token.classification, "UNATTESTED_PARTIAL")
        self.assertFalse(token.verified)

    def test_matrix_authority_receipt_must_bind_exact_event(self) -> None:
        raw = b'{"event_id":"$event"}'
        attestation = HumanReadbackAttestation.create(
            verification_ref="matrix:verification",
            event_ref="matrix:event",
            event_hash=_hash(raw),
            sender="@human:example.invalid",
            identity_ref="identity:human",
            approval_id="approval:skill",
            phase="APPROVE",
            decision="APPROVE",
            run_id="run:test",
            campaign_id="campaign:test",
            trace_id="trace:test",
            revision=1,
            verified_at="2026-09-03T00:00:00Z",
        )
        token = matrix_readback_from_authority(attestation, raw=raw)
        self.assertTrue(token.verified)
        self.assertEqual(token.classification, "AUTHORITY_RECEIPT")
        with self.assertRaisesRegex(SkillOpsError, "exact event"):
            matrix_readback_from_authority(attestation, raw=b"other")

    def test_agentloop_requires_verified_get_and_all_correlation_anchors(self) -> None:
        correlation = Correlation(
            campaign_id="campaign:test",
            run_id="run:test",
            pg_revision="pg:1",
            content_hash="sha256:" + "a" * 64,
        )
        verdict = {
            "schema_version": "testweaver.agentloop-verdict/v1",
            "verdict": "PASS",
            "dataset_ref": "dataset:frozen",
            "dataset_hash": "sha256:" + "b" * 64,
            "evaluation_ref": "evaluation:frozen",
            "evaluation_hash": "sha256:" + "c" * 64,
            "authority_scope": correlation.as_dict(),
        }
        raw = json.dumps(verdict, sort_keys=True, separators=(",", ":")).encode()
        receipt = QueryReceipt(
            schema_version="testweaver.observability-query/v1",
            status="VERIFIED",
            backend="agentloop",
            operation="evaluation_verdict",
            endpoint="https://agentloop.example.invalid",
            path="/api/evaluations/runs",
            http_method="GET",
            read_only=True,
            correlation=correlation,
            response_status=200,
            response_hash=_hash(raw),
            matched_fields=tuple(correlation.as_dict()),
        )
        token = agentloop_readback_from_observability(
            receipt,
            raw=raw,
            dataset_ref="dataset:frozen",
            dataset_hash="sha256:" + "b" * 64,
            evaluation_ref="evaluation:frozen",
            evaluation_hash="sha256:" + "c" * 64,
        )
        self.assertTrue(token.verified)
        self.assertEqual(token.claim("pg_revision"), "pg:1")
        incomplete = QueryReceipt(
            **{**receipt.__dict__, "matched_fields": ("campaign_id", "run_id")}
        )
        with self.assertRaisesRegex(SkillOpsError, "provenance"):
            agentloop_readback_from_observability(
                incomplete,
                raw=raw,
                dataset_ref="dataset:frozen",
                dataset_hash="sha256:" + "b" * 64,
                evaluation_ref="evaluation:frozen",
                evaluation_hash="sha256:" + "c" * 64,
            )


if __name__ == "__main__":
    unittest.main()
