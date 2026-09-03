from __future__ import annotations

import base64
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from typing import Any

from testweaver.authority import HumanReadbackAttestation, digest_bytes
from testweaver.contracts.validator import canonical_hash
from testweaver.skillops import (
    ArtifactRef,
    Attribution,
    Baseline,
    ExternalReadback,
    HumanDecision,
    HumanDecisionVerification,
    SkillEvolution,
    SkillProposal,
    matrix_readback_from_authority,
)


SCRIPT = Path(__file__).resolve().parents[1] / "testweaver-skill-evolve.py"
SPEC = importlib.util.spec_from_file_location("testweaver_skill_evolve", SCRIPT)
assert SPEC and SPEC.loader
evolve = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = evolve
SPEC.loader.exec_module(evolve)


AUTHORITY = {
    "campaign_id": "campaign:hero",
    "run_id": "run:hero",
    "trace_id": "0123456789abcdef0123456789abcdef",
    "pg_revision": 7,
    "content_hash": "sha256:" + "a" * 64,
}


def _json_bytes(value: dict[str, Any], *, seal: str = "record_hash") -> bytes:
    value = dict(value)
    value[seal] = canonical_hash(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _authority_raw(schema: str, **values: Any) -> bytes:
    return _json_bytes({"schema_version": schema, **AUTHORITY, **values})


def _readback(source: str, ref: str, raw: bytes) -> dict[str, Any]:
    return {
        "source": source,
        "ref": ref,
        "raw_base64": base64.b64encode(raw).decode(),
        "raw_hash": digest_bytes(raw),
    }


def _artifact(kind: str, name: str, raw: bytes) -> dict[str, Any]:
    source_kind = {
        "dataset": "frozen-dataset",
        "evaluation": "evaluation-export",
        "trace": "agentteams-native",
        "evidence": "agentteams-native",
    }[kind]
    source = "evaluation" if kind in {"dataset", "evaluation"} else "agentteams"
    return {
        "ref": f"artifact:{name}",
        "source_kind": source_kind,
        "attestation_ref": f"attestation:{name}",
        "readback": _readback(source, f"exact-get:{name}", raw),
    }


def _allowlist_raw() -> bytes:
    return _json_bytes(
        {
            "schema_version": "testweaver.human-allowlist/v1",
            "homeserver_ref": "matrix-homeserver:trusted",
            "reader_identity_ref": "matrix-reader:trusted",
            "identities": {"@human:hs": "identity:alice"},
        }
    )


def _request(stage: str, payload: dict[str, Any], previous: dict[str, Any] | None) -> bytes:
    value = {
        "schema_version": "testweaver.skill-evolve-request/v1",
        "stage": stage,
        "authority": AUTHORITY,
        "previous_receipt": previous,
        "payload": payload,
    }
    value["record_hash"] = canonical_hash(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _prepare() -> dict[str, Any]:
    package = b"exact candidate package bytes"
    allowlist = _allowlist_raw()
    payload = {
        "skill_name": "reconcile-before-retry",
        "baseline_id": "baseline:hero",
        "attribution_id": "attribution:hero",
        "proposal_id": "proposal:hero",
        "base_version": "1.0.0",
        "candidate_version": "1.1.0",
        "package_uri": "nacos://registry/testweaver/reconcile-before-retry",
        "rollback_ref": "nacos://registry/testweaver/reconcile-before-retry@1.0.0",
        "hero_readback": _readback(
            "agentteams",
            "hero:exact",
            _authority_raw(
                "testweaver.hero-result/v1",
                status="PASS",
                human_allowlist_hash=digest_bytes(allowlist),
            ),
        ),
        "human_allowlist_readback": _readback("authority", "allowlist:humans", allowlist),
        "candidate_package_readback": _readback(
            "nacos", "nacos://registry/testweaver/reconcile-before-retry", package
        ),
        "dataset": _artifact("dataset", "dataset", b"frozen dataset"),
        "evaluation": _artifact("evaluation", "evaluation", b"frozen evaluation"),
        "traces": [_artifact("trace", "baseline-trace", b"native baseline trace")],
        "evidence": [_artifact("evidence", "baseline-evidence", b"native baseline evidence")],
    }
    return evolve.prepare(_request("prepare", payload, None))


def _approval(previous: dict[str, Any], *, sender: str = "@human:hs") -> dict[str, Any]:
    proposal = previous["records"]["proposal"]
    approval_id = "approval:hero"
    fingerprint = canonical_hash(
        {
            "approval_id": approval_id,
            "phase": "APPROVE",
            "decision": "APPROVE",
            "action_ref": proposal["proposal_id"],
            "action_hash": proposal["record_hash"],
            "campaign_id": AUTHORITY["campaign_id"],
            "run_id": AUTHORITY["run_id"],
            "revision": 1,
        }
    )
    raw_event = json.dumps(
        {
            "type": "m.room.message",
            "room_id": "!approval:hs",
            "event_id": "$approval",
            "sender": sender,
            "origin_server_ts": 1788393600000,
            "content": {
                "msgtype": "m.text",
                "body": "Approve candidate 1.1.0",
                "testweaver": {
                    "identity_ref": "identity:alice",
                    "approval_id": approval_id,
                    "phase": "APPROVE",
                    "decision": "APPROVE",
                    "campaign_id": AUTHORITY["campaign_id"],
                    "run_id": AUTHORITY["run_id"],
                    "trace_id": AUTHORITY["trace_id"],
                    "revision": 1,
                    "action_ref": proposal["proposal_id"],
                    "action_hash": proposal["record_hash"],
                    "action_fingerprint": fingerprint,
                },
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    payload = {
        "approval_id": approval_id,
        "decision": "APPROVE",
        "revision": 1,
        "verification_ref": "verification:approval",
        "verified_at": "2026-09-03T08:00:00Z",
        "allowlist_ref": "allowlist:humans",
        "matrix_event": {
            "homeserver_ref": "matrix-homeserver:trusted",
            "reader_identity_ref": "matrix-reader:trusted",
            "request_ref": "matrix-get:approval",
            "room_id": "!approval:hs",
            "event_id": "$approval",
            "readback": _readback("matrix", "matrix:!approval:hs:$approval", raw_event),
        },
    }
    return evolve.verify_approval(_request("verify-approval", payload, previous))


def _nacos_response(raw: bytes, ref: str, *, content_type: str = "application/json") -> dict[str, Any]:
    return {
        "status_code": 200,
        "headers": {"content-type": content_type},
        "readback": _readback("nacos", ref, raw),
    }


def _publish(previous: dict[str, Any], *, download: bytes | None = None) -> dict[str, Any]:
    package = base64.b64decode(
        next(item for item in previous["readbacks"] if item["source"] == "nacos")["raw_base64"]
    )
    ok = b'{"code":0,"data":true}'
    admin = b'{"code":0,"data":{"scope":"private","versions":[{"version":"1.1.0","status":"online"}]}}'
    payload = {
        "nacos_readbacks": {
            "upload": _nacos_response(ok, "nacos:upload"),
            "submit": _nacos_response(ok, "nacos:submit"),
            "publish": _nacos_response(ok, "nacos:publish"),
            "download": _nacos_response(
                download if download is not None else package,
                "nacos:download",
                content_type="application/zip",
            ),
            "admin": _nacos_response(admin, "nacos:admin"),
        }
    }
    return evolve.publish_candidate(_request("publish-candidate", payload, previous))


def _canary(previous: dict[str, Any], status: str = "PASS") -> dict[str, Any]:
    proposal = previous["records"]["proposal"]
    activation = _authority_raw(
        "agentteams.official-skill-activation/v1",
        operator="official-agentspec-agt",
        package_uri=previous["observations"]["candidate"]["package_uri"],
        skill_name=proposal["skill_name"],
        version=proposal["candidate_version"],
        package_hash=proposal["content_hash"],
        status="ACTIVATED",
    )
    result = _authority_raw(
        "agentteams.native-canary-result/v1",
        skill_name=proposal["skill_name"],
        candidate_version=proposal["candidate_version"],
        package_hash=proposal["content_hash"],
        activation_receipt_hash=digest_bytes(activation),
        status=status,
        result_ref="native-canary:result",
        trace_refs=["native-canary:trace"],
        evidence_refs=["native-canary:evidence"],
    )
    payload = {
        "activation_readback": _readback("agentteams", "agt:activation", activation),
        "canary_readback": _readback("agentteams", "agt:canary-result", result),
    }
    return evolve.record_canary(_request("record-canary", payload, previous))


def _oracle_record(kind: str, result_raw: bytes) -> bytes:
    result_ref = f"oracle:{kind}:result"
    values = {
        "result_id": f"oracle-record:{kind}",
        "oracle_kind": kind,
        "run_id": AUTHORITY["run_id"],
        "campaign_id": AUTHORITY["campaign_id"],
        "trace_id": AUTHORITY["trace_id"],
        "identity_ref": f"oracle-identity:{kind}",
        "process_ref": f"oracle-process:{kind}",
        "result_ref": result_ref,
        "result_hash": digest_bytes(result_raw),
        "evidence_root_ref": "evidence-root:hero",
        "evidence_root_hash": "sha256:" + "b" * 64,
        "evidence_refs": [{"ref": "evidence:shared", "content_hash": "sha256:" + "c" * 64}],
        "gold_ref": "gold:sealed" if kind == "outcome" else None,
        "source_ref": f"oracle-source:{kind}",
        "status": "PASS",
        "provenance": "agentteams-native",
        "read_result_refs": [],
    }
    values["content_hash"] = canonical_hash(values)
    return json.dumps(values, sort_keys=True, separators=(",", ":")).encode()


def _reevaluate_oracle(previous: dict[str, Any], *, tamper_result: bool = False) -> dict[str, Any]:
    outcome_result = b'exact outcome result {"status":"PASS"}'
    boundary_result = b'exact boundary result {"status":"PASS"}'
    payload = {
        "mode": "oracle",
        "outcome_record": _readback("evaluation", "oracle:outcome:record", _oracle_record("outcome", outcome_result)),
        "outcome_result": _readback(
            "evaluation",
            "oracle:outcome:result",
            b"different exact result" if tamper_result else outcome_result,
        ),
        "boundary_record": _readback(
            "evaluation",
            "oracle:boundary:record",
            _oracle_record("boundary", boundary_result),
        ),
        "boundary_result": _readback("evaluation", "oracle:boundary:result", boundary_result),
    }
    return evolve.reevaluate(_request("reevaluate", payload, previous))


class SkillEvolveOperatorTests(unittest.TestCase):
    def test_synthetic_full_flow_is_unattested_partial_and_blocked(self) -> None:
        token = ExternalReadback.from_raw(
            source="agentteams", ref="hero:exact", raw=b"caller transcript"
        )
        self.assertEqual(token.classification, "UNATTESTED_PARTIAL")
        self.assertFalse(token.verified)
        with self.assertRaisesRegex(Exception, "verified external readback"):
            _prepare()

    def test_synthetic_failed_canary_cannot_reach_close(self) -> None:
        with self.assertRaisesRegex(Exception, "verified external readback"):
            _canary(_publish(_approval(_prepare())), "FAIL")

    def test_cross_run_and_unsealed_self_reports_fail_closed(self) -> None:
        prepared = evolve._receipt(
            stage="prepare",
            authority=AUTHORITY,
            status="PARTIAL",
            records=evolve._empty_records(),
            readbacks=[],
            intents=[],
            observations={},
        )
        crossed = json.loads(_request("verify-approval", {}, prepared))
        crossed["authority"]["run_id"] = "run:other"
        crossed["record_hash"] = canonical_hash({key: value for key, value in crossed.items() if key != "record_hash"})
        with self.assertRaisesRegex(evolve.EvolutionInputError, "authority"):
            evolve.verify_approval(json.dumps(crossed).encode())

        tampered = json.loads(_request("prepare", {}, None))
        tampered["payload"] = json.loads(json.dumps({
            "skill_name": "x"
        }))
        tampered["record_hash"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(evolve.EvolutionInputError, "sealed"):
            evolve.prepare(json.dumps(tampered).encode())

    def test_nacos_and_oracle_transcripts_remain_unattested_partial(self) -> None:
        for source, raw in (
            ("nacos", b'{"code":0,"data":true}'),
            ("evaluation", b'{"status":"PASS"}'),
        ):
            token = ExternalReadback.from_raw(source=source, ref=f"{source}:raw", raw=raw)
            self.assertEqual(token.classification, "UNATTESTED_PARTIAL")
            self.assertFalse(token.verified)
        with self.assertRaisesRegex(Exception, "verified external readback"):
            _prepare()

    def test_source_has_no_native_scheduling_or_signing_path(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in (
            "create_project",
            "create_task",
            "schedule_agent",
            "send_matrix",
            "approve_on_behalf",
            "subprocess",
            "urllib.request",
        ):
            self.assertNotIn(forbidden, source)

    def test_agentloop_success_counts_are_not_a_quality_verdict(self) -> None:
        task = {
            "taskId": "evaluation-task:hero",
            "agentSpace": "space:hero",
            "status": "Completed",
            "evaluators": [{"evaluatorRef": "evaluator:hero"}],
            "tags": {"campaignId": AUTHORITY["campaign_id"], "runId": AUTHORITY["run_id"], "revision": "7"},
        }
        runs = {
            "evaluationRuns": [{
                "taskId": "evaluation-task:hero",
                "runId": "evaluation-run:hero",
                "status": "Completed",
                "totalCount": 1,
                "successCount": 1,
                "failedCount": 0,
            }]
        }
        for ref, raw in (
            ("agentloop:task", json.dumps(task).encode()),
            ("agentloop:runs", json.dumps(runs).encode()),
        ):
            token = ExternalReadback.from_raw(source="agentloop", ref=ref, raw=raw)
            self.assertEqual(token.classification, "UNATTESTED_PARTIAL")
            self.assertFalse(token.verified)
        with self.assertRaisesRegex(Exception, "verified external readback"):
            _prepare()

    def test_authority_attested_matrix_readback_can_advance_human_gate(self) -> None:
        dataset = ArtifactRef(
            kind="dataset",
            ref="dataset:frozen",
            content_hash="sha256:" + "b" * 64,
            source_kind="frozen-dataset",
            provenance="FROZEN",
            classification="NON_LIVE",
            attestation_ref="manifest:dataset",
        )
        evaluation = ArtifactRef(
            kind="evaluation",
            ref="evaluation:frozen",
            content_hash="sha256:" + "c" * 64,
            source_kind="evaluation-export",
            provenance="FROZEN",
            classification="NON_LIVE",
            attestation_ref="manifest:evaluation",
        )
        trace = ArtifactRef(
            kind="trace",
            ref="trace:partial",
            content_hash="sha256:" + "d" * 64,
            source_kind="evaluation-export",
            provenance="REPLAY",
            classification="NON_LIVE",
            attestation_ref="manifest:trace",
            run_id=AUTHORITY["run_id"],
        )
        evidence = ArtifactRef(
            kind="evidence",
            ref="evidence:partial",
            content_hash="sha256:" + "f" * 64,
            source_kind="evaluation-export",
            provenance="REPLAY",
            classification="NON_LIVE",
            attestation_ref="manifest:evidence",
            run_id=AUTHORITY["run_id"],
        )
        baseline = Baseline.freeze(
            baseline_id="baseline:hero",
            dataset_ref=dataset,
            evaluation_ref=evaluation,
            run_id=AUTHORITY["run_id"],
            trace_refs=(trace,),
            evidence_refs=(evidence,),
        )
        attribution = Attribution.create(
            attribution_id="attribution:hero",
            skill_name="reconcile-before-retry",
            base_version="1.0.0",
            baseline=baseline,
            trace_refs=(trace,),
            evidence_refs=(evidence,),
        )
        proposal = SkillProposal.create(
            proposal_id="proposal:hero",
            skill_name="reconcile-before-retry",
            base_version="1.0.0",
            candidate_version="1.1.0",
            content_hash="sha256:" + "e" * 64,
            rollback_ref="nacos://registry/testweaver/reconcile-before-retry@1.0.0",
            baseline=baseline,
            attribution=attribution,
        )
        decision = HumanDecision.create(
            decision_id="approval:hero",
            decision_revision=1,
            proposal=proposal,
            actor_ref="@human:hs",
            identity_ref="identity:alice",
            attestation_ref="matrix:event:approval",
            actor_kind="external-human",
            decision="APPROVE",
            decided_at="2026-09-03T08:00:00Z",
        )
        raw_event = b'{"event_id":"$approval","sender":"@human:hs"}'
        authority_receipt = HumanReadbackAttestation.create(
            verification_ref="matrix:verification:approval",
            event_ref=decision.attestation_ref,
            event_hash=digest_bytes(raw_event),
            sender=decision.actor_ref,
            identity_ref=decision.identity_ref,
            approval_id=decision.decision_id,
            phase="APPROVE",
            decision="APPROVE",
            run_id=baseline.run_id,
            campaign_id=AUTHORITY["campaign_id"],
            trace_id=AUTHORITY["trace_id"],
            revision=decision.decision_revision,
            verified_at="2026-09-03T08:00:01Z",
        )
        token = matrix_readback_from_authority(authority_receipt, raw=raw_event)
        verification = HumanDecisionVerification.create(
            verification_ref=authority_receipt.verification_ref,
            source="matrix-live-readback",
            event_ref=decision.attestation_ref,
            event_hash=digest_bytes(raw_event),
            sender=decision.actor_ref,
            identity_ref=decision.identity_ref,
            decision_ref=decision.decision_id,
            decision_hash=decision.record_hash,
            proposal_ref=proposal.proposal_id,
            proposal_hash=proposal.record_hash,
            decision_revision=decision.decision_revision,
            decision=decision.decision,
            baseline_ref=baseline.baseline_id,
            baseline_hash=baseline.record_hash,
            run_id=baseline.run_id,
            verified_at=authority_receipt.verified_at,
            verified_readback=token,
        )
        lifecycle = SkillEvolution(proposal.skill_name)
        lifecycle.freeze_baseline(baseline)
        lifecycle.attribute(attribution)
        lifecycle.propose(proposal)
        lifecycle.record_human_decision(
            decision, verifier=lambda *_args: verification
        )
        self.assertEqual(lifecycle.state, "HUMAN_APPROVED")


if __name__ == "__main__":
    unittest.main()
