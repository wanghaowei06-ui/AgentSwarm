"""Minimal external-Human/Matrix PAUSE and resume authority records."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from testweaver.contracts.validator import canonical_hash

from .store import (
    AuthorityConflict,
    AuthorityError,
    AuthorityStore,
    _ensure_sealed,
    _safe_value,
    validate_hash,
    validate_ref,
)


_PHASES = frozenset({"PAUSE", "APPROVE", "DENY", "RESUME", "STOP"})
_DECISIONS = frozenset({"APPROVE", "DENY"})
_ACTOR_KINDS = frozenset({"native-policy", "external-human"})
_AUTOMATIC_MARKERS = frozenset({"auto", "automatic", "system", "internal", "default"})
_ATTESTATION_SOURCE = "matrix-live-readback"


def _external(value: str, field: str) -> str:
    result = validate_ref(value, field)
    lowered = result.casefold()
    if lowered in _AUTOMATIC_MARKERS or any(
        lowered.startswith(marker + separator)
        for marker in _AUTOMATIC_MARKERS
        for separator in (":", "-", "/")
    ):
        raise AuthorityError(f"{field} must reference an external identity")
    return result


@dataclass(frozen=True, slots=True)
class HumanReadbackAttestation:
    """A sealed result returned by an external Matrix readback verifier."""

    verification_ref: str
    source: str
    event_ref: str
    event_hash: str
    sender: str
    identity_ref: str
    approval_id: str
    phase: str
    decision: str | None
    run_id: str
    campaign_id: str
    trace_id: str
    revision: int
    verified_at: str
    record_hash: str

    @classmethod
    def create(
        cls,
        *,
        verification_ref: str,
        event_ref: str,
        event_hash: str,
        sender: str,
        identity_ref: str,
        approval_id: str,
        phase: str,
        decision: str | None,
        run_id: str,
        campaign_id: str,
        trace_id: str,
        revision: int,
        verified_at: str,
    ) -> "HumanReadbackAttestation":
        values = {
            "verification_ref": verification_ref,
            "source": _ATTESTATION_SOURCE,
            "event_ref": event_ref,
            "event_hash": event_hash,
            "sender": sender,
            "identity_ref": identity_ref,
            "approval_id": approval_id,
            "phase": phase,
            "decision": decision,
            "run_id": run_id,
            "campaign_id": campaign_id,
            "trace_id": trace_id,
            "revision": revision,
            "verified_at": verified_at,
        }
        return cls(**values, record_hash=canonical_hash(_safe_value(values, "human_readback_attestation")))

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "verification_ref": self.verification_ref,
            "source": self.source,
            "event_ref": self.event_ref,
            "event_hash": self.event_hash,
            "sender": self.sender,
            "identity_ref": self.identity_ref,
            "approval_id": self.approval_id,
            "phase": self.phase,
            "decision": self.decision,
            "run_id": self.run_id,
            "campaign_id": self.campaign_id,
            "trace_id": self.trace_id,
            "revision": self.revision,
            "verified_at": self.verified_at,
        }
        if include_hash:
            value["record_hash"] = self.record_hash
        return value

    def validate(self) -> None:
        for field in (
            "verification_ref",
            "event_ref",
            "sender",
            "identity_ref",
            "approval_id",
            "run_id",
            "campaign_id",
            "trace_id",
            "verified_at",
        ):
            validate_ref(getattr(self, field), field)
        if self.source != _ATTESTATION_SOURCE:
            raise AuthorityError("human attestation source is not an external Matrix readback")
        if self.phase not in _PHASES:
            raise AuthorityError("human attestation phase is unsupported")
        if self.decision is not None and self.decision not in _DECISIONS:
            raise AuthorityError("human attestation decision is unsupported")
        if self.phase == "APPROVE" and self.decision != "APPROVE":
            raise AuthorityError("human attestation approval does not match phase")
        if self.phase == "DENY" and self.decision != "DENY":
            raise AuthorityError("human attestation denial does not match phase")
        if self.phase not in {"APPROVE", "DENY"} and self.decision is not None:
            raise AuthorityError("human attestation decision is only valid for a decision phase")
        if type(self.revision) is not int or self.revision < 1:
            raise AuthorityError("human attestation revision must be positive")
        validate_hash(self.event_hash, "event_hash")
        _ensure_sealed(self.as_dict(), "record_hash")


HumanReadbackVerifier = Callable[["HITLRecord"], HumanReadbackAttestation]


@dataclass(frozen=True, slots=True)
class HITLRecord:
    event_id: str
    approval_id: str
    phase: str
    decision: str | None
    run_id: str
    campaign_id: str
    trace_id: str
    revision: int
    previous_revision: int | None
    matrix_event_ref: str
    matrix_event_hash: str
    verification_ref: str | None
    verification_hash: str | None
    sender: str
    identity_ref: str
    actor_kind: str
    policy_ref: str
    reason_ref: str | None
    occurred_at: str
    provenance: str
    content_hash: str

    def __post_init__(self) -> None:
        self.validate()

    @classmethod
    def create(
        cls,
        *,
        event_id: str,
        approval_id: str,
        phase: str,
        decision: str | None,
        run_id: str,
        campaign_id: str,
        trace_id: str,
        revision: int,
        previous_revision: int | None,
        matrix_event_ref: str,
        matrix_event_hash: str,
        verification_ref: str | None,
        verification_hash: str | None,
        sender: str,
        identity_ref: str,
        actor_kind: str,
        policy_ref: str,
        reason_ref: str | None,
        occurred_at: str,
        provenance: str,
    ) -> "HITLRecord":
        values = {
            "event_id": event_id,
            "approval_id": approval_id,
            "phase": phase,
            "decision": decision,
            "run_id": run_id,
            "campaign_id": campaign_id,
            "trace_id": trace_id,
            "revision": revision,
            "previous_revision": previous_revision,
            "matrix_event_ref": matrix_event_ref,
            "matrix_event_hash": matrix_event_hash,
            "verification_ref": verification_ref,
            "verification_hash": verification_hash,
            "sender": sender,
            "identity_ref": identity_ref,
            "actor_kind": actor_kind,
            "policy_ref": policy_ref,
            "reason_ref": reason_ref,
            "occurred_at": occurred_at,
            "provenance": provenance,
        }
        return cls(**values, content_hash=canonical_hash(_safe_value(values, "hitl")))

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "event_id": self.event_id,
            "approval_id": self.approval_id,
            "phase": self.phase,
            "decision": self.decision,
            "run_id": self.run_id,
            "campaign_id": self.campaign_id,
            "trace_id": self.trace_id,
            "revision": self.revision,
            "previous_revision": self.previous_revision,
            "matrix_event_ref": self.matrix_event_ref,
            "matrix_event_hash": self.matrix_event_hash,
            "verification_ref": self.verification_ref,
            "verification_hash": self.verification_hash,
            "sender": self.sender,
            "identity_ref": self.identity_ref,
            "actor_kind": self.actor_kind,
            "policy_ref": self.policy_ref,
            "reason_ref": self.reason_ref,
            "occurred_at": self.occurred_at,
            "provenance": self.provenance,
        }
        if include_hash:
            value["content_hash"] = self.content_hash
        return value

    def validate(self) -> None:
        for field in (
            "event_id",
            "approval_id",
            "run_id",
            "campaign_id",
            "trace_id",
            "matrix_event_ref",
            "sender",
            "identity_ref",
            "policy_ref",
            "occurred_at",
            "provenance",
        ):
            validate_ref(getattr(self, field), field)
        if self.phase not in _PHASES:
            raise AuthorityError("unsupported HITL phase")
        if self.decision is not None and self.decision not in _DECISIONS:
            raise AuthorityError("unsupported HITL decision")
        if type(self.revision) is not int or self.revision < 1:
            raise AuthorityError("HITL revision must be positive")
        if self.previous_revision is not None and (
            type(self.previous_revision) is not int or self.previous_revision < 1
        ):
            raise AuthorityError("previous_revision must be positive")
        validate_hash(self.matrix_event_hash, "matrix_event_hash")
        if (self.verification_ref is None) != (self.verification_hash is None):
            raise AuthorityError("verification reference and hash must be provided together")
        if self.verification_ref is not None:
            validate_ref(self.verification_ref, "verification_ref")
            validate_hash(self.verification_hash, "verification_hash")
        if self.actor_kind not in _ACTOR_KINDS:
            raise AuthorityError("unsupported HITL actor kind")
        if self.phase in {"APPROVE", "DENY", "RESUME"}:
            if self.actor_kind != "external-human":
                raise AuthorityError("decision and resume require an external human")
            if self.verification_ref is None or self.verification_hash is None:
                raise AuthorityError("external decision requires a Matrix readback attestation")
            _external(self.sender, "sender")
            _external(self.identity_ref, "identity_ref")
        if self.phase == "APPROVE" and self.decision != "APPROVE":
            raise AuthorityError("APPROVE phase requires APPROVE decision")
        if self.phase == "DENY" and self.decision != "DENY":
            raise AuthorityError("DENY phase requires DENY decision")
        if self.phase not in {"APPROVE", "DENY"} and self.decision is not None:
            raise AuthorityError("decision is only valid on an approval or denial")
        if self.reason_ref is not None:
            validate_ref(self.reason_ref, "reason_ref")
        _ensure_sealed(self.as_dict(), "content_hash")


class HITLAuthority:
    def __init__(self, store: AuthorityStore, verifier: HumanReadbackVerifier | None = None):
        self.store = store
        self.verifier = verifier

    def append(self, record: HITLRecord) -> bool:
        record.validate()
        existing_event = self.store.rows(
            "SELECT content_hash FROM tw_hitl_events WHERE event_id = ?",
            (record.event_id,),
        )
        if existing_event:
            if existing_event[0][0] == record.content_hash:
                return False
            raise AuthorityConflict("HITL event_id is already bound to different content")
        history = self.store.rows(
            "SELECT phase, decision, revision, content_hash, run_id, campaign_id, trace_id "
            "FROM tw_hitl_events "
            "WHERE approval_id = ? ORDER BY revision",
            (record.approval_id,),
        )
        if record.phase == "PAUSE":
            if history:
                raise AuthorityError("an approval may have only one initial PAUSE")
            if record.revision != 1 or record.previous_revision is not None:
                raise AuthorityError("PAUSE must start at revision one")
            if record.actor_kind != "native-policy":
                raise AuthorityError("PAUSE must be emitted by native Policy")
        elif not history:
            raise AuthorityError("HITL decision requires a prior PAUSE")
        else:
            latest_revision = history[-1][2]
            if (record.run_id, record.campaign_id, record.trace_id) != history[-1][4:7]:
                raise AuthorityError("HITL events must remain in one run lineage")
            if record.previous_revision != latest_revision or record.revision <= latest_revision:
                raise AuthorityError("HITL revision does not follow the current pause/resume chain")
            if record.phase in {"APPROVE", "DENY"} and history[-1][0] != "PAUSE":
                raise AuthorityError("approval or denial must immediately follow PAUSE")
            if record.phase == "RESUME" and history[-1][0] != "APPROVE":
                raise AuthorityError("RESUME requires an external APPROVE event")
        if record.phase in {"APPROVE", "DENY", "RESUME"}:
            self._verify_external_readback(record)
        return self.store.append_record(
            table="tw_hitl_events",
            identity_column="event_id",
            identity_value=record.event_id,
            content_hash=record.content_hash,
            columns=(
                "event_id",
                "approval_id",
                "phase",
                "decision",
                "run_id",
                "campaign_id",
                "trace_id",
                "revision",
                "previous_revision",
                "matrix_event_ref",
                "matrix_event_hash",
                "verification_ref",
                "verification_hash",
                "sender",
                "identity_ref",
                "actor_kind",
                "policy_ref",
                "reason_ref",
                "occurred_at",
                "provenance",
                "content_hash",
            ),
            values=(
                record.event_id,
                record.approval_id,
                record.phase,
                record.decision,
                record.run_id,
                record.campaign_id,
                record.trace_id,
                record.revision,
                record.previous_revision,
                record.matrix_event_ref,
                record.matrix_event_hash,
                record.verification_ref,
                record.verification_hash,
                record.sender,
                record.identity_ref,
                record.actor_kind,
                record.policy_ref,
                record.reason_ref,
                record.occurred_at,
                record.provenance,
                record.content_hash,
            ),
        )

    def read(self, approval_id: str) -> tuple[HITLRecord, ...]:
        validate_ref(approval_id, "approval_id")
        rows = self.store.rows(
            "SELECT event_id, approval_id, phase, decision, run_id, campaign_id, trace_id, revision, "
            "previous_revision, matrix_event_ref, matrix_event_hash, verification_ref, verification_hash, "
            "sender, identity_ref, actor_kind, "
            "policy_ref, reason_ref, occurred_at, provenance, content_hash FROM tw_hitl_events "
            "WHERE approval_id = ? ORDER BY revision",
            (approval_id,),
        )
        return tuple(HITLRecord(*row) for row in rows)

    def _verify_external_readback(self, record: HITLRecord) -> None:
        if self.verifier is None:
            raise AuthorityError("external Matrix readback verifier is required")
        try:
            attestation = self.verifier(record)
            if not isinstance(attestation, HumanReadbackAttestation):
                raise AuthorityError("external verifier returned an invalid attestation")
            attestation.validate()
        except AuthorityError:
            raise
        except Exception as error:
            raise AuthorityError("external Matrix readback verifier failed") from error
        expected = (
            ("verification_ref", record.verification_ref, attestation.verification_ref),
            ("verification_hash", record.verification_hash, attestation.record_hash),
            ("matrix_event_ref", record.matrix_event_ref, attestation.event_ref),
            ("matrix_event_hash", record.matrix_event_hash, attestation.event_hash),
            ("sender", record.sender, attestation.sender),
            ("identity_ref", record.identity_ref, attestation.identity_ref),
            ("approval_id", record.approval_id, attestation.approval_id),
            ("phase", record.phase, attestation.phase),
            ("decision", record.decision, attestation.decision),
            ("run_id", record.run_id, attestation.run_id),
            ("campaign_id", record.campaign_id, attestation.campaign_id),
            ("trace_id", record.trace_id, attestation.trace_id),
            ("revision", record.revision, attestation.revision),
        )
        if any(left != right for _, left, right in expected):
            raise AuthorityError("external Matrix readback does not match HITL record")


__all__ = ["HITLAuthority", "HITLRecord", "HumanReadbackAttestation", "HumanReadbackVerifier"]
