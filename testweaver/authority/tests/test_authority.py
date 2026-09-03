"""Focused local tests for the thin authority projections.

The fixture values are opaque references only.  No provider, Matrix service,
AgentTeams resource, or artifact body is accessed by these tests.
"""

from __future__ import annotations

import sqlite3
import unittest
from dataclasses import replace
from pathlib import Path

from testweaver.authority import (
    AuthorityConflict,
    AuthorityError,
    AuthorityEvent,
    AuthorityStore,
    CapsuleAuthority,
    CapsuleHit,
    CapsuleRecord,
    HITLAuthority,
    HITLRecord,
    HumanReadbackAttestation,
    OracleAuthority,
    OracleResult,
    SideEffectEntry,
    SideEffectLedger,
    validate_oracle_pair,
)


HASH = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
ROOT = Path(__file__).resolve().parents[2]


def _store() -> AuthorityStore:
    connection = sqlite3.connect(":memory:")
    store = AuthorityStore(connection)
    store.initialize()
    return store


def _event(*, revision: int = 1, event_id: str = "event:one") -> AuthorityEvent:
    return AuthorityEvent.create(
        event_id=event_id,
        aggregate_id="campaign:one",
        aggregate_type="campaign",
        revision=revision,
        event_type="native.accepted_result",
        actor="native:leader",
        idempotency_key=f"idem:{event_id}",
        occurred_at="2026-09-02T00:00:00Z",
        payload={"native_event_ref": "matrix:event:one", "result_hash": HASH},
        request_hash=HASH,
        run_id="run:one",
        campaign_id="campaign:one",
        trace_id="trace:one",
        provenance="agentteams-native",
    )


def _capsule(*, revision: int = 1, capsule_id: str = "capsule:one") -> CapsuleRecord:
    return CapsuleRecord.create(
        capsule_id=capsule_id,
        capsule_type="failure",
        state="OPEN",
        fingerprint="fp:approval-timeout",
        fault_owner="native:leader",
        target_fault_domains=("worker",),
        observation_ref="artifact:observation:one",
        evidence_refs=({"ref": "artifact:evidence:one", "content_hash": HASH},),
        baseline_strategy="strategy:baseline",
        observed_strategy="strategy:observed",
        root_cause_ref="claim:root-cause",
        repair_ref="repair:one",
        regression_refs=("run:regression:one",),
        artifact_ref="artifact:capsule:one",
        artifact_hash=HASH,
        run_id="run:one",
        campaign_id="campaign:one",
        trace_id="trace:one",
        revision=revision,
        provenance="agentteams-native",
    )


def _hit(*, hit_id: str = "hit:one", recurrence: bool = False) -> CapsuleHit:
    return CapsuleHit.create(
        hit_id=hit_id,
        capsule_id="capsule:one",
        capsule_revision=1,
        capsule_content_hash=_capsule().content_hash,
        matched_fingerprint="fp:approval-timeout",
        recurrence=recurrence,
        evidence_ref="artifact:evidence:retry",
        run_id="run:two",
        campaign_id="campaign:one",
        trace_id="trace:two",
        occurred_at="2026-09-02T00:01:00Z",
        provenance="agentteams-native",
    )


def _hitl(
    *, phase: str, revision: int, previous_revision: int | None, event_id: str, decision: str | None,
    actor_kind: str = "external-human",
) -> HITLRecord:
    sender = "@human:example.invalid" if actor_kind == "external-human" else "policy:native"
    identity_ref = "human:identity" if actor_kind == "external-human" else "policy:identity"
    event_ref = f"matrix:event:{event_id}"
    verification_ref = None
    verification_hash = None
    if actor_kind == "external-human" and phase in {"APPROVE", "DENY", "RESUME"}:
        verification = HumanReadbackAttestation.create(
            verification_ref=f"matrix-readback:{event_id}",
            event_ref=event_ref,
            event_hash=HASH,
            sender=sender,
            identity_ref=identity_ref,
            approval_id="approval:one",
            phase=phase,
            decision=decision,
            run_id="run:one",
            campaign_id="campaign:one",
            trace_id="trace:one",
            revision=revision,
            verified_at=f"2026-09-02T00:0{revision}:30Z",
        )
        verification_ref = verification.verification_ref
        verification_hash = verification.record_hash
    return HITLRecord.create(
        event_id=event_id,
        approval_id="approval:one",
        phase=phase,
        decision=decision,
        run_id="run:one",
        campaign_id="campaign:one",
        trace_id="trace:one",
        revision=revision,
        previous_revision=previous_revision,
        matrix_event_ref=event_ref,
        matrix_event_hash=HASH,
        sender=sender,
        identity_ref=identity_ref,
        actor_kind=actor_kind,
        policy_ref="policy:dangerous-tool",
        reason_ref="reason:approved" if decision else None,
        occurred_at=f"2026-09-02T00:0{revision}:00Z",
        provenance="matrix-readback",
        verification_ref=verification_ref,
        verification_hash=verification_hash,
    )


def _hitl_verifier(record: HITLRecord) -> HumanReadbackAttestation:
    if record.verification_ref is None:
        raise AssertionError("test record has no verification ref")
    return HumanReadbackAttestation.create(
        verification_ref=record.verification_ref,
        event_ref=record.matrix_event_ref,
        event_hash=record.matrix_event_hash,
        sender=record.sender,
        identity_ref=record.identity_ref,
        approval_id=record.approval_id,
        phase=record.phase,
        decision=record.decision,
        run_id=record.run_id,
        campaign_id=record.campaign_id,
        trace_id=record.trace_id,
        revision=record.revision,
        verified_at=f"2026-09-02T00:0{record.revision}:30Z",
    )


def _oracle(kind: str, *, identity: str, process: str, result: str, result_hash: str, gold_ref: str | None) -> OracleResult:
    return OracleResult.create(
        result_id=f"oracle-result:{kind}",
        oracle_kind=kind,
        run_id="run:one",
        campaign_id="campaign:one",
        trace_id="trace:one",
        identity_ref=identity,
        process_ref=process,
        result_ref=result,
        result_hash=result_hash,
        evidence_root_ref="artifact:evidence-root:one",
        evidence_root_hash=HASH,
        evidence_refs=({"ref": "artifact:evidence:one", "content_hash": HASH},),
        gold_ref=gold_ref,
        source_ref=f"native:{kind}:event",
        status="PASS",
        provenance="agentteams-native",
    )


def _ledger(*, decision: str = "allow", fencing: str = "passed") -> SideEffectEntry:
    return SideEffectEntry.create(
        entry_id="ledger:one",
        call_ref="call:one",
        run_id="run:one",
        campaign_id="campaign:one",
        trace_id="trace:one",
        actor_ref="native:worker",
        tool_ref="driver:mcp:testweaver-native-worker",
        operation="invoke",
        target_ref="task:one",
        decision=decision,
        effect="read" if decision == "allow" else "none",
        fencing=fencing,
        occurred_at="2026-09-02T00:00:00Z",
        request_hash=HASH,
        result_hash=HASH_B if decision == "allow" else None,
        provenance="agentteams-native",
    )


class AuthorityStoreTests(unittest.TestCase):
    def test_event_is_sealed_and_idempotent_but_conflict_is_rejected(self) -> None:
        store = _store()
        event = _event()
        self.assertTrue(store.append_event(event))
        self.assertFalse(store.append_event(event))
        conflicting = _event(event_id="event:other")
        with self.assertRaises(AuthorityError):
            AuthorityEvent(
                **{**conflicting.as_dict(include_hash=False), "idempotency_key": event.idempotency_key,
                   "content_hash": event.content_hash}
            )
        with self.assertRaises(AuthorityConflict):
            store.append_event(
                AuthorityEvent.create(
                    event_id="event:other",
                    aggregate_id="campaign:one",
                    aggregate_type="campaign",
                    revision=2,
                    event_type="different",
                    actor="native:leader",
                    idempotency_key=event.idempotency_key,
                    occurred_at="2026-09-02T00:00:01Z",
                    payload={"native_event_ref": "matrix:event:two"},
                    request_hash=HASH_B,
                    run_id="run:one",
                    campaign_id="campaign:one",
                    trace_id="trace:one",
                    provenance="agentteams-native",
                )
            )
        self.assertEqual(len(store.read_events(run_id="run:one")), 1)

    def test_event_payload_rejects_prompt_body_and_nonfinite_values(self) -> None:
        with self.assertRaises(AuthorityError):
            AuthorityEvent.create(**{**_event().as_dict(include_hash=False), "payload": {"body": "x"}})
        with self.assertRaises(AuthorityError):
            AuthorityEvent.create(**{**_event().as_dict(include_hash=False), "payload": {"value": float("nan")}})

    def test_event_revisions_are_contiguous(self) -> None:
        store = _store()
        store.append_event(_event())
        with self.assertRaises(AuthorityError):
            store.append_event(_event(revision=3, event_id="event:three"))

    def test_read_hook_is_select_only(self) -> None:
        store = _store()
        with self.assertRaises(AuthorityError):
            store.rows("DELETE FROM tw_authority_events")
        with self.assertRaises(AuthorityError):
            store.rows("SELECT value FROM unrelated_table")

    def test_append_record_rejects_untrusted_identity_column(self) -> None:
        with self.assertRaises(AuthorityError):
            _store().append_record(
                table="tw_oracle_results",
                identity_column="result_id OR 1=1",
                identity_value="result:one",
                content_hash=HASH,
                columns=("result_id",),
                values=("result:one",),
            )
        with self.assertRaises(AuthorityError):
            _store().append_record(
                table="tw_oracle_results",
                identity_column="result_id",
                identity_value="result:one",
                content_hash=HASH,
                columns=("source_ref", "content_hash"),
                values=("source:one", HASH),
            )


class CapsuleTests(unittest.TestCase):
    def test_capsule_revision_is_append_only_and_hit_records_recurrence(self) -> None:
        store = _store()
        authority = CapsuleAuthority(store)
        first = _capsule()
        second = _capsule(revision=2)
        self.assertTrue(authority.persist(first))
        self.assertFalse(authority.persist(first))
        self.assertTrue(authority.persist(second))
        self.assertEqual([item.revision for item in authority.search(fingerprint=first.fingerprint)], [1, 2])
        self.assertTrue(authority.record_hit(_hit(recurrence=True)))
        self.assertEqual(store.rows("SELECT recurrence FROM tw_capsule_hits"), [(True,)])

    def test_hit_must_match_a_persisted_capsule_revision(self) -> None:
        authority = CapsuleAuthority(_store())
        with self.assertRaises(AuthorityError):
            authority.record_hit(_hit())

    def test_capsule_has_only_artifact_references_not_body(self) -> None:
        capsule = _capsule()
        self.assertNotIn("body", capsule.as_dict())
        with self.assertRaises(TypeError):
            CapsuleRecord.create(**{**capsule.as_dict(include_hash=False), "body": "not stored"})  # type: ignore[call-arg]

    def test_capsule_without_evidence_reference_is_not_valid_or_searchable(self) -> None:
        capsule = _capsule()
        with self.assertRaises(AuthorityError):
            CapsuleRecord.create(
                **{**capsule.as_dict(include_hash=False), "evidence_refs": ()},
            )


class HITLTests(unittest.TestCase):
    def test_pause_external_decision_and_new_revision_resume(self) -> None:
        authority = HITLAuthority(_store(), verifier=_hitl_verifier)
        pause = _hitl(phase="PAUSE", revision=1, previous_revision=None, event_id="pause", decision=None, actor_kind="native-policy")
        approve = _hitl(phase="APPROVE", revision=2, previous_revision=1, event_id="approve", decision="APPROVE")
        resume = _hitl(phase="RESUME", revision=3, previous_revision=2, event_id="resume", decision=None)
        self.assertTrue(authority.append(pause))
        self.assertTrue(authority.append(approve))
        self.assertTrue(authority.append(resume))
        self.assertEqual([item.phase for item in authority.read("approval:one")], ["PAUSE", "APPROVE", "RESUME"])

    def test_resume_without_approve_or_automatic_identity_is_rejected(self) -> None:
        authority = HITLAuthority(_store(), verifier=_hitl_verifier)
        pause = _hitl(phase="PAUSE", revision=1, previous_revision=None, event_id="pause", decision=None, actor_kind="native-policy")
        authority.append(pause)
        with self.assertRaises(AuthorityError):
            authority.append(_hitl(phase="RESUME", revision=2, previous_revision=1, event_id="resume", decision=None, actor_kind="external-human"))
        with self.assertRaises(AuthorityError):
            authority.append(_hitl(phase="APPROVE", revision=2, previous_revision=1, event_id="approve", decision="APPROVE", actor_kind="native-policy"))

    def test_external_decision_requires_matrix_readback_verifier(self) -> None:
        for phase, decision in (("APPROVE", "APPROVE"), ("DENY", "DENY")):
            authority = HITLAuthority(_store())
            authority.append(_hitl(phase="PAUSE", revision=1, previous_revision=None, event_id="pause", decision=None, actor_kind="native-policy"))
            with self.subTest(phase=phase), self.assertRaises(AuthorityError):
                authority.append(_hitl(phase=phase, revision=2, previous_revision=1, event_id=phase.lower(), decision=decision))

        store = _store()
        HITLAuthority(store, verifier=_hitl_verifier).append(
            _hitl(phase="PAUSE", revision=1, previous_revision=None, event_id="pause", decision=None, actor_kind="native-policy")
        )
        HITLAuthority(store, verifier=_hitl_verifier).append(
            _hitl(phase="APPROVE", revision=2, previous_revision=1, event_id="approve", decision="APPROVE")
        )
        with self.assertRaises(AuthorityError):
            HITLAuthority(store).append(_hitl(phase="RESUME", revision=3, previous_revision=2, event_id="resume", decision=None))

    def test_external_verifier_failure_is_fail_closed(self) -> None:
        def failed(_: HITLRecord) -> HumanReadbackAttestation:
            raise RuntimeError("matrix unavailable")

        store = _store()
        authority = HITLAuthority(store, verifier=failed)
        authority.append(_hitl(phase="PAUSE", revision=1, previous_revision=None, event_id="pause", decision=None, actor_kind="native-policy"))
        with self.assertRaises(AuthorityError):
            authority.append(_hitl(phase="APPROVE", revision=2, previous_revision=1, event_id="approve", decision="APPROVE"))
        self.assertEqual(store.rows("SELECT COUNT(*) FROM tw_hitl_events"), [(1,)])

    def test_external_attestation_mismatch_is_fail_closed(self) -> None:
        def wrong_sender(record: HITLRecord) -> HumanReadbackAttestation:
            attestation = _hitl_verifier(record)
            return HumanReadbackAttestation.create(
                **{**attestation.as_dict(include_hash=False), "sender": "@other:example.invalid"}
            )

        store = _store()
        authority = HITLAuthority(store, verifier=wrong_sender)
        authority.append(_hitl(phase="PAUSE", revision=1, previous_revision=None, event_id="pause", decision=None, actor_kind="native-policy"))
        with self.assertRaises(AuthorityError):
            authority.append(_hitl(phase="APPROVE", revision=2, previous_revision=1, event_id="approve", decision="APPROVE"))
        self.assertEqual(store.rows("SELECT COUNT(*) FROM tw_hitl_events"), [(1,)])

    def test_external_attestation_binds_every_decision_field(self) -> None:
        fields = (
            ("event_ref", "matrix:event:other"),
            ("event_hash", HASH_B),
            ("sender", "@other:example.invalid"),
            ("identity_ref", "human:other"),
            ("approval_id", "approval:other"),
            ("phase", "DENY"),
            ("decision", "DENY"),
            ("run_id", "run:other"),
            ("campaign_id", "campaign:other"),
            ("trace_id", "trace:other"),
            ("revision", 7),
        )
        for field, replacement_value in fields:
            with self.subTest(field=field):
                def mismatched(record: HITLRecord, field=field, replacement_value=replacement_value) -> HumanReadbackAttestation:
                    attestation = _hitl_verifier(record)
                    values = attestation.as_dict(include_hash=False)
                    values[field] = replacement_value
                    if field == "phase":
                        values["decision"] = "DENY"
                    if field == "decision":
                        values["phase"] = "DENY"
                    return HumanReadbackAttestation.create(**values)

                store = _store()
                authority = HITLAuthority(store, verifier=mismatched)
                authority.append(_hitl(phase="PAUSE", revision=1, previous_revision=None, event_id="pause", decision=None, actor_kind="native-policy"))
                with self.assertRaises(AuthorityError):
                    authority.append(_hitl(phase="APPROVE", revision=2, previous_revision=1, event_id="approve", decision="APPROVE"))

    def test_external_attestation_source_and_seal_are_verified(self) -> None:
        def untrusted_source(record: HITLRecord) -> HumanReadbackAttestation:
            return replace(_hitl_verifier(record), source="caller-self-report")

        store = _store()
        authority = HITLAuthority(store, verifier=untrusted_source)
        authority.append(_hitl(phase="PAUSE", revision=1, previous_revision=None, event_id="pause", decision=None, actor_kind="native-policy"))
        with self.assertRaises(AuthorityError):
            authority.append(_hitl(phase="APPROVE", revision=2, previous_revision=1, event_id="approve", decision="APPROVE"))

        def unsealed(record: HITLRecord) -> HumanReadbackAttestation:
            return replace(_hitl_verifier(record), record_hash=HASH_B)

        authority = HITLAuthority(_store(), verifier=unsealed)
        authority.append(_hitl(phase="PAUSE", revision=1, previous_revision=None, event_id="pause", decision=None, actor_kind="native-policy"))
        with self.assertRaises(AuthorityError):
            authority.append(_hitl(phase="APPROVE", revision=2, previous_revision=1, event_id="approve", decision="APPROVE"))

    def test_external_attestation_is_sealed_and_replay_is_idempotent(self) -> None:
        store = _store()
        authority = HITLAuthority(store, verifier=_hitl_verifier)
        authority.append(_hitl(phase="PAUSE", revision=1, previous_revision=None, event_id="pause", decision=None, actor_kind="native-policy"))
        approve = _hitl(phase="APPROVE", revision=2, previous_revision=1, event_id="approve", decision="APPROVE")
        self.assertTrue(authority.append(approve))
        self.assertFalse(authority.append(approve))
        persisted = authority.read("approval:one")[1]
        self.assertEqual(persisted.verification_hash, approve.verification_hash)

    def test_hitl_event_conflict_uses_authority_conflict(self) -> None:
        authority = HITLAuthority(_store(), verifier=_hitl_verifier)
        pause = _hitl(
            phase="PAUSE",
            revision=1,
            previous_revision=None,
            event_id="pause",
            decision=None,
            actor_kind="native-policy",
        )
        authority.append(pause)
        conflicting = HITLRecord.create(
            **{**pause.as_dict(include_hash=False), "matrix_event_hash": HASH_B}
        )
        with self.assertRaises(AuthorityConflict):
            authority.append(conflicting)


class OracleTests(unittest.TestCase):
    def test_pair_shares_input_but_has_independent_identity_process_and_result(self) -> None:
        outcome = _oracle("outcome", identity="oracle:outcome", process="pid:outcome", result="artifact:outcome", result_hash=HASH_B, gold_ref="gold:sealed")
        boundary = _oracle("boundary", identity="oracle:boundary", process="pid:boundary", result="artifact:boundary", result_hash=HASH_C, gold_ref=None)
        validate_oracle_pair(outcome, boundary)
        authority = OracleAuthority(_store())
        self.assertEqual(authority.persist_pair(outcome, boundary), (True, True))

    def test_pair_rolls_back_when_second_insert_fails(self) -> None:
        store = _store()
        store.connection.execute(
            "CREATE TRIGGER reject_boundary BEFORE INSERT ON tw_oracle_results "
            "WHEN NEW.oracle_kind = 'boundary' BEGIN SELECT RAISE(ABORT, 'test'); END"
        )
        outcome = _oracle("outcome", identity="oracle:outcome", process="pid:outcome", result="artifact:outcome", result_hash=HASH_B, gold_ref="gold:sealed")
        boundary = _oracle("boundary", identity="oracle:boundary", process="pid:boundary", result="artifact:boundary", result_hash=HASH_C, gold_ref=None)
        with self.assertRaises(sqlite3.IntegrityError):
            OracleAuthority(store).persist_pair(outcome, boundary)
        self.assertEqual(store.rows("SELECT COUNT(*) FROM tw_oracle_results"), [(0,)])

    def test_pair_replay_is_idempotent_and_conflict_is_atomic(self) -> None:
        store = _store()
        authority = OracleAuthority(store)
        outcome = _oracle("outcome", identity="oracle:outcome", process="pid:outcome", result="artifact:outcome", result_hash=HASH_B, gold_ref="gold:sealed")
        boundary = _oracle("boundary", identity="oracle:boundary", process="pid:boundary", result="artifact:boundary", result_hash=HASH_C, gold_ref=None)
        self.assertEqual(authority.persist_pair(outcome, boundary), (True, True))
        self.assertEqual(authority.persist_pair(outcome, boundary), (False, False))
        conflict = OracleResult.create(
            **{**boundary.as_dict(include_hash=False), "status": "FAIL"}
        )
        with self.assertRaises(AuthorityConflict):
            authority.persist_pair(outcome, conflict)
        self.assertEqual(store.rows("SELECT COUNT(*) FROM tw_oracle_results"), [(2,)])

    def test_pair_requires_a_common_public_evidence_reference(self) -> None:
        outcome = _oracle("outcome", identity="oracle:outcome", process="pid:outcome", result="artifact:outcome", result_hash=HASH_B, gold_ref="gold:sealed")
        boundary = OracleResult.create(
            **{
                **_oracle("boundary", identity="oracle:boundary", process="pid:boundary", result="artifact:boundary", result_hash=HASH_C, gold_ref=None).as_dict(include_hash=False),
                "evidence_refs": ({"ref": "artifact:evidence:other", "content_hash": HASH_B},),
            }
        )
        with self.assertRaises(AuthorityError):
            validate_oracle_pair(outcome, boundary)

    def test_oracle_pair_rejects_cross_result_refs_shared_process_or_boundary_gold(self) -> None:
        outcome = _oracle("outcome", identity="oracle:outcome", process="pid:outcome", result="artifact:outcome", result_hash=HASH_B, gold_ref="gold:sealed")
        boundary = _oracle("boundary", identity="oracle:boundary", process="pid:boundary", result="artifact:boundary", result_hash=HASH_C, gold_ref=None)
        with self.assertRaises(AuthorityError):
            validate_oracle_pair(outcome, OracleResult(**{**boundary.as_dict(include_hash=False), "read_result_refs": (outcome.result_ref,), "content_hash": boundary.content_hash}))
        with self.assertRaises(AuthorityError):
            validate_oracle_pair(outcome, _oracle("boundary", identity="oracle:outcome", process="pid:boundary", result="artifact:boundary", result_hash=HASH_C, gold_ref=None))
        with self.assertRaises(AuthorityError):
            _oracle("boundary", identity="oracle:boundary", process="pid:boundary", result="artifact:boundary", result_hash=HASH_C, gold_ref="gold:sealed").validate()


class SideEffectTests(unittest.TestCase):
    def test_only_observed_allow_or_deny_with_fencing_is_recorded(self) -> None:
        ledger = SideEffectLedger(_store())
        self.assertTrue(ledger.append(_ledger()))
        denied = SideEffectEntry.create(
            **{**_ledger(decision="deny", fencing="blocked").as_dict(include_hash=False), "entry_id": "ledger:two", "call_ref": "call:two"}
        )
        self.assertTrue(ledger.append(denied))
        self.assertEqual([entry.call_ref for entry in ledger.entries(run_id="run:one")], ["call:one", "call:two"])

    def test_unobserved_or_inconsistent_fencing_is_rejected(self) -> None:
        with self.assertRaises(AuthorityError):
            SideEffectEntry.create(**{**_ledger().as_dict(include_hash=False), "observed": False})
        with self.assertRaises(AuthorityError):
            SideEffectEntry.create(**{**_ledger(decision="deny", fencing="blocked").as_dict(include_hash=False), "fencing": "passed"})


class SchemaTests(unittest.TestCase):
    def test_schema_declares_all_append_only_projections(self) -> None:
        schema = (ROOT / "authority" / "schema.sql").read_text(encoding="utf-8")
        for table in (
            "tw_authority_events",
            "tw_capsules",
            "tw_capsule_hits",
            "tw_hitl_events",
            "tw_oracle_results",
            "tw_side_effect_ledger",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", schema)
        self.assertIn("UNIQUE (aggregate_id, revision)", schema)
        self.assertIn("UNIQUE (idempotency_key)", schema)
        self.assertIn("verification_ref TEXT", schema)
        self.assertIn("verification_hash TEXT", schema)


if __name__ == "__main__":
    unittest.main()
