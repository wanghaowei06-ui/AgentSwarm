"""Exact, read-only Matrix event verification for external Human decisions."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from testweaver.authority import (
    AuthorityError,
    HumanReadbackAttestation,
    digest_bytes,
    validate_hash,
    validate_ref,
)
from testweaver.contracts.validator import canonical_hash

MatrixEventGET = Callable[[str, str], bytes]
MatrixIdentityGET = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class MatrixDecisionExpectation:
    room_id: str
    event_id: str
    sender: str
    identity_ref: str
    approval_id: str
    phase: str
    decision: str | None
    campaign_id: str
    run_id: str
    trace_id: str
    revision: int
    action_ref: str
    action_hash: str
    action_fingerprint: str
    verification_ref: str
    verified_at: str

    @classmethod
    def create(cls, **values: Any) -> MatrixDecisionExpectation:
        action_hash = validate_hash(values["action_hash"], "action_hash")
        fingerprint = canonical_hash(
            {
                "approval_id": values["approval_id"],
                "phase": values["phase"],
                "decision": values.get("decision"),
                "action_ref": values["action_ref"],
                "action_hash": action_hash,
                "campaign_id": values["campaign_id"],
                "run_id": values["run_id"],
                "revision": values["revision"],
            }
        )
        supplied = values.pop("action_fingerprint", fingerprint)
        if supplied != fingerprint:
            raise AuthorityError("expected action fingerprint is not sealed")
        return cls(**values, action_fingerprint=fingerprint)


@dataclass(slots=True)
class MatrixHumanReadbackVerifier:
    """Fetch one exact event; never sends a Matrix event and never resumes work."""

    get_event: MatrixEventGET
    get_identity: MatrixIdentityGET

    def verify(self, expected: MatrixDecisionExpectation) -> HumanReadbackAttestation:
        _validate_expectation(expected)
        raw = self.get_event(expected.room_id, expected.event_id)
        if not isinstance(raw, bytes) or not raw:
            raise AuthorityError("Matrix GET transport must return raw JSON bytes")
        try:
            event = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuthorityError("Matrix GET returned invalid UTF-8 JSON") from exc
        if not isinstance(event, Mapping):
            raise AuthorityError("Matrix GET event must be an object")
        _equal(event.get("room_id"), expected.room_id, "room_id")
        _equal(event.get("event_id"), expected.event_id, "event_id")
        _equal(event.get("sender"), expected.sender, "sender")
        _equal(
            self.get_identity(expected.sender), expected.identity_ref, "identity_ref"
        )
        content = event.get("content")
        if not isinstance(content, Mapping):
            raise AuthorityError("Matrix event content must be an object")
        fact = content.get("testweaver")
        if not isinstance(fact, Mapping):
            raise AuthorityError("Matrix event lacks a structured TestWeaver decision")
        exact = {
            "identity_ref": expected.identity_ref,
            "approval_id": expected.approval_id,
            "phase": expected.phase,
            "decision": expected.decision,
            "campaign_id": expected.campaign_id,
            "run_id": expected.run_id,
            "trace_id": expected.trace_id,
            "revision": expected.revision,
            "action_ref": expected.action_ref,
            "action_hash": expected.action_hash,
            "action_fingerprint": expected.action_fingerprint,
        }
        for field, value in exact.items():
            _equal(fact.get(field), value, field)
        recalculated = canonical_hash(
            {
                "approval_id": fact["approval_id"],
                "phase": fact["phase"],
                "decision": fact["decision"],
                "action_ref": fact["action_ref"],
                "action_hash": fact["action_hash"],
                "campaign_id": fact["campaign_id"],
                "run_id": fact["run_id"],
                "revision": fact["revision"],
            }
        )
        _equal(recalculated, expected.action_fingerprint, "action_fingerprint")
        attestation = HumanReadbackAttestation.create(
            verification_ref=expected.verification_ref,
            event_ref=f"matrix:{expected.room_id}:{expected.event_id}",
            event_hash=digest_bytes(raw),
            sender=expected.sender,
            identity_ref=expected.identity_ref,
            approval_id=expected.approval_id,
            phase=expected.phase,
            decision=expected.decision,
            run_id=expected.run_id,
            campaign_id=expected.campaign_id,
            trace_id=expected.trace_id,
            revision=expected.revision,
            verified_at=expected.verified_at,
        )
        attestation.validate()
        return attestation


def _validate_expectation(value: MatrixDecisionExpectation) -> None:
    for field in (
        "room_id",
        "event_id",
        "sender",
        "identity_ref",
        "approval_id",
        "campaign_id",
        "run_id",
        "trace_id",
        "action_ref",
        "verification_ref",
        "verified_at",
    ):
        validate_ref(getattr(value, field), field)
    validate_hash(value.action_hash, "action_hash")
    validate_hash(value.action_fingerprint, "action_fingerprint")
    if value.phase not in {"APPROVE", "DENY", "RESUME"}:
        raise AuthorityError("readback phase must be an explicit Human action")
    if value.phase in {"APPROVE", "DENY"} and value.decision != value.phase:
        raise AuthorityError("decision does not match decision phase")
    if value.phase == "RESUME" and value.decision is not None:
        raise AuthorityError("resume must not carry a decision")
    if type(value.revision) is not int or value.revision < 1:
        raise AuthorityError("revision must be a positive integer")


def _equal(actual: Any, expected: Any, field: str) -> None:
    if actual != expected:
        raise AuthorityError(f"Matrix event {field} does not match expected authority")
