"""Focused tests for the in-memory Skill evolution contract.

All values here are contract-only and are never classified as LIVE evidence.
The tests do not read Golden data or invoke AgentTeams.
"""

from __future__ import annotations

import json
import hashlib
import unittest
from pathlib import Path

from testweaver.authority import SideEffectEntry

from testweaver.skillops import (
    ArtifactRef,
    Attribution,
    Baseline,
    CanaryObservation,
    ExternalReadback,
    HumanDecision,
    HumanDecisionVerification,
    ReevaluationObservation,
    SkillEvolution,
    SkillOpsError,
    SkillOpsStateError,
    SkillProposal,
    SkillReceipt,
    verify_skill_operation_receipt,
)
from testweaver.skillops.state import _external_readback


HASH = "sha256:" + "0" * 64
ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "testweaver" / "skillops" / "schema.json"


def _trusted_raw(
    *, source: str, ref: str, raw: bytes, claims: dict[str, str] | None = None
) -> ExternalReadback:
    return _external_readback(
        source=source,
        ref=ref,
        raw=raw,
        classification="AUTHORITY_RECEIPT",
        claims=tuple(sorted((claims or {}).items())),
        verified=True,
    )


def _ref(kind: str, name: str, *, run_id: str | None = "run:test") -> ArtifactRef:
    source = "frozen-dataset" if kind == "dataset" else "evaluation-export"
    if kind in {"trace", "evidence", "result"}:
        source = "agentteams-native"
    observation = kind in {"trace", "evidence", "result"}
    raw = f"{kind}:{name}".encode("utf-8")
    content_hash = HASH
    verified_readback = None
    if observation:
        verified_readback = _trusted_raw(
            source="agentteams",
            ref=f"test:readback:{name}",
            raw=raw,
        )
        content_hash = verified_readback.raw_hash
    return ArtifactRef(
        kind=kind,  # type: ignore[arg-type]
        ref=f"test:{name}",
        content_hash=content_hash,
        source_kind=source,
        provenance="LIVE" if observation else "FROZEN",
        classification="LIVE_ATTESTED" if observation else "NON_LIVE",
        attestation_ref=f"test:attestation:{name}",
        attested=observation,
        run_id=run_id,
        verified_readback=verified_readback,
    )


def _records(skill_name: str = "reconcile-before-retry") -> tuple[
    Baseline,
    Attribution,
    SkillProposal,
    HumanDecision,
    CanaryObservation,
    ReevaluationObservation,
]:
    dataset = _ref("dataset", "dataset", run_id=None)
    evaluation = _ref("evaluation", "evaluation", run_id=None)
    trace = _ref("trace", "baseline-trace")
    evidence = _ref("evidence", "baseline-evidence")
    baseline = Baseline.freeze(
        baseline_id="test:baseline",
        dataset_ref=dataset,
        evaluation_ref=evaluation,
        run_id="run:test",
        trace_refs=(trace,),
        evidence_refs=(evidence,),
    )
    attribution = Attribution.create(
        attribution_id="test:attribution",
        skill_name=skill_name,
        base_version="1.0.0",
        baseline=baseline,
        trace_refs=(trace,),
        evidence_refs=(evidence,),
    )
    proposal = SkillProposal.create(
        proposal_id="test:proposal",
        skill_name=skill_name,
        base_version="1.0.0",
        candidate_version="1.1.0",
        content_hash=HASH,
        rollback_ref=f"test:package:{skill_name}@1.0.0",
        baseline=baseline,
        attribution=attribution,
    )
    decision = HumanDecision.create(
        decision_id="test:decision",
        decision_revision=1,
        proposal=proposal,
        actor_ref="@test-human:example.invalid",
        identity_ref="test:identity:human",
        attestation_ref="test:decision-attestation",
        actor_kind="external-human",
        decision="APPROVE",
        decided_at="2026-09-02T00:00:00Z",
    )
    canary_result = _ref("result", "canary-result")
    reevaluation_result = _ref("result", "reevaluation-result")
    canary = CanaryObservation.create(
        observation_id="test:canary",
        proposal_ref=proposal.proposal_id,
        proposal_hash=proposal.record_hash,
        candidate_version=proposal.candidate_version,
        dataset_ref=dataset,
        evaluation_ref=evaluation,
        result_ref=canary_result,
        trace_refs=(_ref("trace", "canary-trace"),),
        evidence_refs=(_ref("evidence", "canary-evidence"),),
        status="PASS",
    )
    reevaluation = ReevaluationObservation.create(
        observation_id="test:reevaluation",
        proposal_ref=proposal.proposal_id,
        proposal_hash=proposal.record_hash,
        candidate_version=proposal.candidate_version,
        dataset_ref=dataset,
        evaluation_ref=evaluation,
        result_ref=reevaluation_result,
        trace_refs=(_ref("trace", "reevaluation-trace"),),
        evidence_refs=(_ref("evidence", "reevaluation-evidence"),),
        status="PASS",
    )
    return baseline, attribution, proposal, decision, canary, reevaluation


def _verification(
    decision: HumanDecision,
    proposal: SkillProposal,
    baseline: Baseline,
    **overrides: object,
) -> HumanDecisionVerification:
    values: dict[str, object] = {
        "verification_ref": "test:decision-verification",
        "source": "matrix-live-readback",
        "event_ref": decision.attestation_ref,
        "event_hash": ExternalReadback.from_raw(
            source="matrix",
            ref=decision.attestation_ref,
            raw=f"matrix-event:{decision.decision_id}".encode("utf-8"),
        ).raw_hash,
        "sender": decision.actor_ref,
        "identity_ref": decision.identity_ref,
        "decision_ref": decision.decision_id,
        "decision_hash": decision.record_hash,
        "proposal_ref": proposal.proposal_id,
        "proposal_hash": proposal.record_hash,
        "decision_revision": decision.decision_revision,
        "decision": decision.decision,
        "baseline_ref": baseline.baseline_id,
        "baseline_hash": baseline.record_hash,
        "run_id": baseline.run_id,
        "verified_at": "2026-09-02T00:00:01Z",
    }
    values.update(overrides)
    if "verified_readback" not in values:
        values["verified_readback"] = _trusted_raw(
            source="matrix",
            ref=decision.attestation_ref,
            raw=f"matrix-event:{decision.decision_id}".encode("utf-8"),
            claims={
                "sender": decision.actor_ref,
                "identity_ref": decision.identity_ref,
                "run_id": baseline.run_id,
                "approval_id": decision.decision_id,
                "decision": decision.decision,
                "decision_revision": str(decision.decision_revision),
            },
        )
    if "event_hash" not in overrides:
        values["event_hash"] = values["verified_readback"].raw_hash  # type: ignore[union-attr]
    return HumanDecisionVerification.create(**values)


def _verifier(**overrides: object):
    def verify(
        decision: HumanDecision,
        proposal: SkillProposal,
        baseline: Baseline,
    ) -> HumanDecisionVerification:
        return _verification(decision, proposal, baseline, **overrides)

    return verify


def _proposed(skill_name: str = "reconcile-before-retry") -> tuple[
    SkillEvolution,
    tuple[Baseline, Attribution, SkillProposal, HumanDecision, CanaryObservation, ReevaluationObservation],
]:
    records = _records(skill_name)
    evolution = SkillEvolution(skill_name)
    evolution.freeze_baseline(records[0])
    evolution.attribute(records[1])
    evolution.propose(records[2])
    return evolution, records


def _prepared(skill_name: str = "reconcile-before-retry") -> tuple[
    SkillEvolution,
    tuple[Baseline, Attribution, SkillProposal, HumanDecision, CanaryObservation, ReevaluationObservation],
]:
    records = _records(skill_name)
    evolution = SkillEvolution(skill_name)
    evolution.freeze_baseline(records[0])
    evolution.attribute(records[1])
    evolution.propose(records[2])
    evolution.record_human_decision(records[3], verifier=_verifier())
    evolution.record_canary(records[4])
    evolution.record_reevaluation(records[5])
    return evolution, records


class SkillOpsTests(unittest.TestCase):
    def test_schema_is_strict_and_has_all_lifecycle_records(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        expected = {
            "Baseline",
            "Attribution",
            "Proposal",
            "HumanDecision",
            "HumanDecisionVerification",
            "Canary",
            "Reevaluation",
            "Receipt",
            "OperationVerification",
            "State",
        }
        self.assertEqual(set(schema["$defs"]).intersection(expected), expected)
        for name in expected:
            definition = schema["$defs"][name]
            if name in {"Canary", "Reevaluation"}:
                definition = schema["$defs"]["EvaluationStage"]
            self.assertEqual(definition["type"], "object")
            self.assertIs(definition["additionalProperties"], False)
        self.assertIs(schema["$defs"]["ArtifactRef"]["additionalProperties"], False)
        self.assertEqual(
            set(schema["$defs"]["HumanDecision"]["required"]),
            {
                "artifact_type",
                "decision_id",
                "decision_revision",
                "proposal_ref",
                "proposal_hash",
                "actor_ref",
                "identity_ref",
                "attestation_ref",
                "actor_kind",
                "decision",
                "decided_at",
                "record_hash",
            },
        )
        self.assertEqual(
            set(schema["$defs"]["HumanDecisionVerification"]["required"]),
            {
                "artifact_type",
                "verification_ref",
                "source",
                "event_ref",
                "event_hash",
                "sender",
                "identity_ref",
                "decision_ref",
                "decision_hash",
                "proposal_ref",
                "proposal_hash",
                "decision_revision",
                "decision",
                "baseline_ref",
                "baseline_hash",
                "run_id",
                "verified_at",
                "record_hash",
            },
        )
        self.assertIn("baseline_run_id", schema["$defs"]["Attribution"]["required"])
        self.assertIn("provenance", schema["$defs"]["ArtifactRef"]["required"])
        self.assertIn("classification", schema["$defs"]["ArtifactRef"]["required"])

    def test_schema_validator_accepts_only_the_contract_shapes(self) -> None:
        try:
            from jsonschema import Draft202012Validator
        except ImportError:  # pragma: no cover - depends on the test environment
            self.skipTest("jsonschema is not installed")
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        baseline, attribution, proposal, decision, canary, reevaluation = _records()
        verification = _verification(decision, proposal, baseline)
        for record in (baseline, attribution, proposal, decision, verification, canary, reevaluation):
            self.assertEqual(list(validator.iter_errors(record.as_dict())), [])
        self.assertEqual(list(validator.iter_errors(_prepared()[0].snapshot())), [])

    def test_contract_has_no_runtime_or_orchestration_dependency(self) -> None:
        source = (ROOT / "testweaver" / "skillops" / "state.py").read_text(encoding="utf-8").lower()
        for forbidden in (
            "subprocess",
            "socket",
            "requests",
            "docker",
            "nacos",
            "scheduler",
            "runner",
            "observer",
            "taskrun",
        ):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("matrix_client", source)

    def test_full_flow_stays_pending_until_exact_operation_readback(self) -> None:
        evolution, records = _prepared()
        baseline, _, proposal, decision, canary, reevaluation = records
        receipt = SkillReceipt.create(
            receipt_id="test:promote-receipt",
            proposal_ref=proposal.proposal_id,
            proposal_hash=proposal.record_hash,
            action="PROMOTE",
            base_version=proposal.base_version,
            candidate_version=proposal.candidate_version,
            active_version=proposal.candidate_version,
            rollback_ref=proposal.rollback_ref,
            baseline_hash=baseline.record_hash,
            canary_ref=canary.observation_id,
            canary_hash=canary.record_hash,
            reevaluation_ref=reevaluation.observation_id,
            reevaluation_hash=reevaluation.record_hash,
            human_decision_ref=decision.decision_id,
            human_decision_hash=decision.record_hash,
            human_verification_ref=evolution.human_verification.verification_ref,
            human_verification_hash=evolution.human_verification.record_hash,
        )
        evolution.close(receipt)
        self.assertEqual(evolution.state, "PROMOTION_PENDING")
        self.assertEqual(evolution.snapshot()["receipt_ref"], receipt.receipt_id)
        self.assertEqual(
            evolution.snapshot()["human_verification_hash"],
            evolution.human_verification.record_hash,
        )

        result = {
            "schema_version": "testweaver.skill-operation-result/v1",
            "status": "APPLIED",
            "operation_ref": "call:promote",
            "action": "PROMOTE",
            "active_version": proposal.candidate_version,
            "proposal_ref": proposal.proposal_id,
            "proposal_hash": proposal.record_hash,
            "receipt_ref": receipt.receipt_id,
            "receipt_hash": receipt.record_hash,
            "content_hash": proposal.content_hash,
            "verified_at": "2026-09-03T00:00:00Z",
            "authority_scope": {
                "campaign_id": "campaign:test",
                "run_id": baseline.run_id,
                "trace_id": "trace:test",
                "pg_revision": "pg:1",
                "content_hash": HASH,
            },
        }
        raw = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
        entry = SideEffectEntry.create(
            entry_id="entry:promote",
            call_ref="call:promote",
            run_id=baseline.run_id,
            campaign_id="campaign:test",
            trace_id="trace:test",
            actor_ref="operator:skillops",
            tool_ref="official-agentspec-agt",
            operation="skill.promote",
            target_ref=proposal.proposal_id,
            decision="allow",
            effect="write",
            fencing="passed",
            occurred_at="2026-09-03T00:00:00Z",
            request_hash=HASH,
            result_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
            provenance="agentteams-native",
        )
        verification = verify_skill_operation_receipt(
            entry, raw=raw, receipt=receipt, proposal=proposal
        )
        evolution.verify_close(verification)
        self.assertEqual(evolution.state, "PROMOTED")
        self.assertEqual(
            evolution.snapshot()["operation_verification_hash"],
            verification.record_hash,
        )

        with self.assertRaises(AttributeError):
            evolution.state = "PROMOTED"  # type: ignore[misc]

    def test_candidate_is_reference_only_and_self_report_cannot_advance(self) -> None:
        records = _records()
        proposal = records[2]
        self.assertEqual(set(proposal.as_dict()), {
            "artifact_type",
            "proposal_id",
            "skill_name",
            "base_version",
            "candidate_version",
            "content_hash",
            "rollback_ref",
            "baseline_ref",
            "baseline_hash",
            "attribution_ref",
            "attribution_hash",
            "record_hash",
        })
        neutral = HumanDecision.create(
            decision_id="test:neutral-decision",
            decision_revision=1,
            proposal=proposal,
            actor_ref="default",
            identity_ref="system",
            attestation_ref="neutral-attestation",
            actor_kind="external-human",
            decision="APPROVE",
            decided_at="2026-09-02T00:00:00Z",
        )
        evolution, _ = _proposed()
        with self.assertRaises(TypeError):
            evolution.record_human_decision(neutral)
        with self.assertRaisesRegex(SkillOpsStateError, "verifier is required"):
            evolution.record_human_decision(neutral, verifier=None)

        with self.assertRaises(SkillOpsError):
            HumanDecision.create(
                decision_id="test:bad-decision",
                decision_revision=1,
                proposal=proposal,
                actor_ref="test:automation",
                identity_ref="test:identity:automation",
                attestation_ref="test:decision-attestation",
                actor_kind="manager",  # type: ignore[arg-type]
                decision="APPROVE",
                decided_at="2026-09-02T00:00:00Z",
            )

    def test_artifact_classification_is_explicit_and_names_are_not_heuristics(self) -> None:
        with self.assertRaisesRegex(SkillOpsError, "verified external readback"):
            ArtifactRef(
                kind="trace",
                ref="test:fixture-name-is-a-legal-live-reference",
                content_hash=HASH,
                source_kind="agentteams-native",
                provenance="LIVE",
                classification="LIVE_ATTESTED",
                attestation_ref="test:attestation:live",
                attested=True,
                run_id="run:test",
            )
        token = _trusted_raw(
            source="agentteams",
            ref="test:readback:fixture-name",
            raw=b"external event bytes",
        )
        named_like_fixture = ArtifactRef(
            kind="trace",
            ref="test:fixture-name-is-a-legal-live-reference",
            content_hash=token.raw_hash,
            source_kind="agentteams-native",
            provenance="LIVE",
            classification="LIVE_ATTESTED",
            attestation_ref="test:attestation:live",
            attested=True,
            run_id="run:test",
            verified_readback=token,
        )
        self.assertEqual(named_like_fixture.classification, "LIVE_ATTESTED")
        for provenance in ("FIXTURE", "SYNTHETIC", "REPLAY"):
            with self.assertRaises(SkillOpsError):
                ArtifactRef(
                    kind="trace",
                    ref="test:renamed-observation",
                    content_hash=HASH,
                    source_kind="agentteams-native",
                    provenance=provenance,  # type: ignore[arg-type]
                    classification="NON_LIVE",
                    attestation_ref="test:attestation",
                    attested=True,
                    run_id="run:test",
                )
        with self.assertRaises(SkillOpsError):
            ArtifactRef(
                kind="trace",
                ref="test:trace",
                content_hash=HASH,
                source_kind="agentteams-native",
                provenance="LIVE",
                classification="NON_LIVE",
                attestation_ref="test:attestation",
                attested=True,
                run_id="run:test",
            )
        with self.assertRaises(SkillOpsError):
            ArtifactRef(
                kind="evidence",
                ref="test:evidence",
                content_hash=HASH,
                source_kind="agentteams-native",
                provenance="LIVE",
                classification="LIVE_ATTESTED",
                attestation_ref="test:attestation",
                run_id="run:test",
            )

    def test_attribution_observations_are_bound_to_baseline_run(self) -> None:
        baseline, _, _, _, _, _ = _records()
        with self.assertRaisesRegex(SkillOpsError, "frozen run boundary"):
            Attribution.create(
                attribution_id="test:wrong-run-attribution",
                skill_name="reconcile-before-retry",
                base_version="1.0.0",
                baseline=baseline,
                trace_refs=(_ref("trace", "wrong-run-trace", run_id="run:other"),),
                evidence_refs=(_ref("evidence", "wrong-run-evidence", run_id="run:other"),),
            )

    def test_human_decision_revision_and_attestation_are_immutable_and_external(self) -> None:
        records = _records()
        decision = records[3]
        self.assertEqual(
            set(decision.as_dict()),
            {
                "artifact_type",
                "decision_id",
                "decision_revision",
                "proposal_ref",
                "proposal_hash",
                "actor_ref",
                "identity_ref",
                "attestation_ref",
                "actor_kind",
                "decision",
                "decided_at",
                "record_hash",
            },
        )
        with self.assertRaises(AttributeError):
            decision.decision_revision = 2  # type: ignore[misc]
        object.__setattr__(decision, "decision_revision", 2)
        with self.assertRaises(SkillOpsError):
            decision._check_hash()

    def test_human_verifier_is_required_and_fail_closed(self) -> None:
        for returned in (None, False, True, object()):
            evolution, records = _proposed()
            with self.subTest(returned_type=type(returned).__name__), self.assertRaisesRegex(
                SkillOpsStateError, "verification"
            ):
                evolution.record_human_decision(
                    records[3],
                    verifier=lambda _decision, _proposal, _baseline, result=returned: result,
                )
            self.assertEqual(evolution.state, "PROPOSED")

        evolution, records = _proposed()

        def raising_verifier(_decision, _proposal, _baseline):
            raise RuntimeError("external readback unavailable")

        with self.assertRaisesRegex(SkillOpsStateError, "verification"):
            evolution.record_human_decision(records[3], verifier=raising_verifier)
        self.assertIsNone(evolution.human_verification)

    def test_caller_mapping_or_attested_flag_cannot_create_live_readback(self) -> None:
        records = _records()
        with self.assertRaisesRegex(SkillOpsError, "readback token"):
            HumanDecisionVerification.create(
                verification_ref="test:unsealed",
                source="matrix-live-readback",
                event_ref=records[3].attestation_ref,
                event_hash=HASH,
                sender=records[3].actor_ref,
                identity_ref=records[3].identity_ref,
                decision_ref=records[3].decision_id,
                decision_hash=records[3].record_hash,
                proposal_ref=records[2].proposal_id,
                proposal_hash=records[2].record_hash,
                decision_revision=records[3].decision_revision,
                decision=records[3].decision,
                baseline_ref=records[0].baseline_id,
                baseline_hash=records[0].record_hash,
                run_id=records[0].run_id,
                verified_at="2026-09-02T00:00:01Z",
            )
        with self.assertRaisesRegex(SkillOpsError, "verified external readback"):
            ArtifactRef(
                kind="result",
                ref="test:caller-mapped-result",
                content_hash=HASH,
                source_kind="agentteams-native",
                provenance="LIVE",
                classification="LIVE_ATTESTED",
                attestation_ref="test:caller-map",
                attested=True,
                run_id="run:test",
            )

    def test_unobserved_evaluation_is_explicitly_blocked_without_live_readback(self) -> None:
        baseline, _, proposal, _, _, _ = _records()
        blocked_result = ArtifactRef(
            kind="result",
            ref="test:blocked-result",
            content_hash=HASH,
            source_kind="agentteams-native",
            provenance="FIXTURE",
            classification="NON_LIVE",
            attestation_ref="test:blocked-attestation",
            attested=False,
            run_id=baseline.run_id,
        )
        blocked = CanaryObservation.create(
            observation_id="test:blocked-canary",
            proposal_ref=proposal.proposal_id,
            proposal_hash=proposal.record_hash,
            candidate_version=proposal.candidate_version,
            dataset_ref=baseline.dataset_ref,
            evaluation_ref=baseline.evaluation_ref,
            result_ref=blocked_result,
            trace_refs=(blocked_result,),
            evidence_refs=(blocked_result,),
            status="BLOCKED",
        )
        self.assertEqual(blocked.status, "BLOCKED")

    def test_human_verification_must_match_decision_proposal_and_baseline(self) -> None:
        mismatch_cases = {
            "sender": "@other-human:example.invalid",
            "identity_ref": "test:other-identity",
            "event_ref": "test:other-event",
            "proposal_ref": "test:other-proposal",
            "proposal_hash": "sha256:" + "1" * 64,
            "decision_hash": "sha256:" + "2" * 64,
            "decision_revision": 2,
            "run_id": "run:other",
            "baseline_ref": "test:other-baseline",
            "baseline_hash": "sha256:" + "3" * 64,
        }
        for field, value in mismatch_cases.items():
            evolution, records = _proposed()
            with self.subTest(field=field), self.assertRaisesRegex(
                SkillOpsStateError, "verification"
            ):
                evolution.record_human_decision(
                    records[3], verifier=_verifier(**{field: value})
                )
            self.assertEqual(evolution.state, "PROPOSED")

        evolution, records = _proposed()
        with self.assertRaisesRegex(SkillOpsStateError, "verification"):
            evolution.record_human_decision(
                records[3], verifier=_verifier(source="self-reported")
            )

    def test_valid_human_verification_is_sealed_and_associated(self) -> None:
        evolution, records = _proposed()
        verification = evolution.record_human_decision(records[3], verifier=_verifier())
        self.assertIsInstance(verification, HumanDecisionVerification)
        self.assertEqual(verification.source, "matrix-live-readback")
        self.assertEqual(evolution.human_verification, verification)
        snapshot = evolution.snapshot()
        self.assertEqual(snapshot["human_verification_ref"], verification.verification_ref)
        self.assertEqual(snapshot["human_verification_hash"], verification.record_hash)

    def test_same_dataset_is_required_and_failed_canary_cannot_promote(self) -> None:
        records = _records()
        baseline, _, proposal, decision, canary, reevaluation = records
        evolution = SkillEvolution(proposal.skill_name)
        evolution.freeze_baseline(baseline)
        evolution.attribute(records[1])
        evolution.propose(proposal)
        evolution.record_human_decision(decision, verifier=_verifier())
        evolution.record_canary(canary)
        with self.assertRaisesRegex(SkillOpsStateError, "distinct result reference and hash"):
            evolution.record_reevaluation(
                ReevaluationObservation.create(
                    observation_id="test:duplicate-result-reevaluation",
                    proposal_ref=proposal.proposal_id,
                    proposal_hash=proposal.record_hash,
                    candidate_version=proposal.candidate_version,
                    dataset_ref=baseline.dataset_ref,
                    evaluation_ref=baseline.evaluation_ref,
                    result_ref=canary.result_ref,
                    trace_refs=reevaluation.trace_refs,
                    evidence_refs=reevaluation.evidence_refs,
                    status="PASS",
                )
            )
        other_dataset = _ref("dataset", "other-dataset", run_id=None)
        with self.assertRaisesRegex(SkillOpsStateError, "frozen dataset/evaluation"):
            evolution.record_reevaluation(
                ReevaluationObservation.create(
                    observation_id="test:bad-reevaluation",
                    proposal_ref=proposal.proposal_id,
                    proposal_hash=proposal.record_hash,
                    candidate_version=proposal.candidate_version,
                    dataset_ref=other_dataset,
                    evaluation_ref=baseline.evaluation_ref,
                    result_ref=reevaluation.result_ref,
                    trace_refs=reevaluation.trace_refs,
                    evidence_refs=reevaluation.evidence_refs,
                    status="PASS",
                )
            )

        evolution2 = SkillEvolution(proposal.skill_name)
        evolution2.freeze_baseline(baseline)
        evolution2.attribute(records[1])
        evolution2.propose(proposal)
        evolution2.record_human_decision(decision, verifier=_verifier())
        failed_canary = CanaryObservation.create(
            observation_id="test:failed-canary",
            proposal_ref=proposal.proposal_id,
            proposal_hash=proposal.record_hash,
            candidate_version=proposal.candidate_version,
            dataset_ref=baseline.dataset_ref,
            evaluation_ref=baseline.evaluation_ref,
            result_ref=canary.result_ref,
            trace_refs=canary.trace_refs,
            evidence_refs=canary.evidence_refs,
            status="FAIL",
        )
        evolution2.record_canary(failed_canary)
        evolution2.record_reevaluation(reevaluation)
        with self.assertRaisesRegex(SkillOpsStateError, "explicit rollback"):
            evolution2.close(SkillReceipt.create(
                receipt_id="test:blocked-promote",
                proposal_ref=proposal.proposal_id,
                proposal_hash=proposal.record_hash,
                action="PROMOTE",
                base_version=proposal.base_version,
                candidate_version=proposal.candidate_version,
                active_version=proposal.candidate_version,
                rollback_ref=proposal.rollback_ref,
                baseline_hash=baseline.record_hash,
                canary_ref=failed_canary.observation_id,
                canary_hash=failed_canary.record_hash,
                reevaluation_ref=reevaluation.observation_id,
                reevaluation_hash=reevaluation.record_hash,
                human_decision_ref=decision.decision_id,
                human_decision_hash=decision.record_hash,
                human_verification_ref=evolution2.human_verification.verification_ref,
                human_verification_hash=evolution2.human_verification.record_hash,
            ))

        rollback = SkillReceipt.create(
            receipt_id="test:rollback-receipt",
            proposal_ref=proposal.proposal_id,
            proposal_hash=proposal.record_hash,
            action="ROLLBACK",
            base_version=proposal.base_version,
            candidate_version=proposal.candidate_version,
            active_version=proposal.base_version,
            rollback_ref=proposal.rollback_ref,
            baseline_hash=baseline.record_hash,
            canary_ref=failed_canary.observation_id,
            canary_hash=failed_canary.record_hash,
            reevaluation_ref=reevaluation.observation_id,
            reevaluation_hash=reevaluation.record_hash,
            human_decision_ref=decision.decision_id,
            human_decision_hash=decision.record_hash,
            human_verification_ref=evolution2.human_verification.verification_ref,
            human_verification_hash=evolution2.human_verification.record_hash,
        )
        evolution2.close(rollback)
        self.assertEqual(evolution2.state, "ROLLBACK_PENDING")

    def test_state_is_ordered_and_rejected_decision_cannot_enter_canary(self) -> None:
        baseline, attribution, proposal, _, _, _ = _records()
        evolution = SkillEvolution(proposal.skill_name)
        evolution.freeze_baseline(baseline)
        evolution.attribute(attribution)
        evolution.propose(proposal)
        rejected = HumanDecision.create(
            decision_id="test:reject",
            decision_revision=2,
            proposal=proposal,
            actor_ref="@test-human:example.invalid",
            identity_ref="test:identity:human",
            attestation_ref="test:decision-attestation:reject",
            actor_kind="external-human",
            decision="REJECT",
            decided_at="2026-09-02T00:00:00Z",
        )
        evolution.record_human_decision(rejected, verifier=_verifier())
        self.assertEqual(evolution.state, "REJECTED")
        with self.assertRaisesRegex(SkillOpsStateError, "expected HUMAN_APPROVED"):
            evolution.record_canary(_records()[4])

    def test_all_manifest_skills_use_the_same_generic_state_contract(self) -> None:
        manifest = json.loads(
            (ROOT / "testweaver" / "skills" / "bundle-manifest.json").read_text(encoding="utf-8")
        )
        names = [item["name"] for item in manifest["skills"]]
        self.assertEqual(len(names), 5)
        for name in names:
            evolution, _ = _prepared(name)
            self.assertEqual(evolution.skill_name, name)
            self.assertEqual(evolution.state, "REEVALUATED")


if __name__ == "__main__":
    unittest.main()
