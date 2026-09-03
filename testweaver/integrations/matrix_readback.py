"""Exact, read-only Matrix event verification for external Human decisions."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from testweaver.authority import (
    AuthorityError,
    HumanReadbackAttestation,
    digest_bytes,
    validate_hash,
    validate_ref,
)
from testweaver.contracts.validator import canonical_hash

_AUTHENTICATED_GET_TOKEN = object()


@dataclass(frozen=True, slots=True, repr=False)
class MatrixAuthenticatedEvent:
    """Raw exact-GET bytes plus the authenticated reader and homeserver binding."""

    raw_bytes: bytes = field(repr=False)
    homeserver_ref: str
    reader_identity_ref: str
    request_ref: str
    room_id: str
    event_id: str
    event_hash: str
    record_hash: str
    _seal: object = field(default=None, init=False, repr=False, compare=False)

    @classmethod
    def create(
        cls,
        *,
        raw_bytes: bytes,
        homeserver_ref: str,
        reader_identity_ref: str,
        request_ref: str,
        room_id: str,
        event_id: str,
    ) -> "MatrixAuthenticatedEvent":
        if not isinstance(raw_bytes, bytes) or not raw_bytes:
            raise AuthorityError("Matrix exact GET must return non-empty raw bytes")
        event_hash = digest_bytes(raw_bytes)
        values = {
            "homeserver_ref": homeserver_ref,
            "reader_identity_ref": reader_identity_ref,
            "request_ref": request_ref,
            "room_id": room_id,
            "event_id": event_id,
            "event_hash": event_hash,
        }
        result = cls(raw_bytes=raw_bytes, **values, record_hash=canonical_hash(values))
        object.__setattr__(result, "_seal", _AUTHENTICATED_GET_TOKEN)
        return result

    def validate(self, *, room_id: str, event_id: str) -> None:
        if self._seal is not _AUTHENTICATED_GET_TOKEN:
            raise AuthorityError("Matrix exact GET receipt was not issued from raw bytes")
        for name in (
            "homeserver_ref",
            "reader_identity_ref",
            "request_ref",
            "room_id",
            "event_id",
        ):
            validate_ref(getattr(self, name), name)
        validate_hash(self.event_hash, "matrix_event_hash")
        validate_hash(self.record_hash, "matrix_readback_hash")
        if self.room_id != room_id or self.event_id != event_id:
            raise AuthorityError("Matrix exact GET is not bound to the requested event")
        if digest_bytes(self.raw_bytes) != self.event_hash:
            raise AuthorityError("Matrix exact GET event hash mismatch")
        values = {
            "homeserver_ref": self.homeserver_ref,
            "reader_identity_ref": self.reader_identity_ref,
            "request_ref": self.request_ref,
            "room_id": self.room_id,
            "event_id": self.event_id,
            "event_hash": self.event_hash,
        }
        if self.record_hash != canonical_hash(values):
            raise AuthorityError("Matrix exact GET receipt is not sealed")


MatrixEventGET = Callable[[str, str], MatrixAuthenticatedEvent]
MatrixIdentityGET = Callable[[str], str]
PendingApprovalGET = Callable[[str], "MatrixDecisionExpectation"]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


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
    human_identities: Mapping[str, str] | None = None
    get_pending_approval: PendingApprovalGET | None = None
    trusted_homeserver_ref: str | None = None
    trusted_reader_identity_ref: str | None = None
    clock: Callable[[], str] = _utc_now

    def __post_init__(self) -> None:
        if self.human_identities is not None:
            self.human_identities = MappingProxyType(dict(self.human_identities))

    def verify(self, expected: MatrixDecisionExpectation) -> HumanReadbackAttestation:
        _validate_expectation(expected)
        self._verify_protected_bindings(expected)
        readback = self.get_event(expected.room_id, expected.event_id)
        if not isinstance(readback, MatrixAuthenticatedEvent):
            raise AuthorityError("Matrix GET must return an authenticated exact-GET receipt")
        readback.validate(room_id=expected.room_id, event_id=expected.event_id)
        if readback.homeserver_ref != self.trusted_homeserver_ref:
            raise AuthorityError("Matrix exact GET came from an untrusted homeserver")
        if readback.reader_identity_ref != self.trusted_reader_identity_ref:
            raise AuthorityError("Matrix exact GET used an untrusted reader identity")
        raw = readback.raw_bytes
        try:
            event = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuthorityError("Matrix GET returned invalid UTF-8 JSON") from exc
        if not isinstance(event, Mapping):
            raise AuthorityError("Matrix GET event must be an object")
        _equal(event.get("type"), "m.room.message", "type")
        origin_server_ts = event.get("origin_server_ts")
        if type(origin_server_ts) is not int or origin_server_ts < 1:
            raise AuthorityError("Matrix event origin_server_ts is invalid")
        unsigned = event.get("unsigned")
        if isinstance(unsigned, Mapping) and "redacted_because" in unsigned:
            raise AuthorityError("Matrix event was redacted")
        _equal(event.get("room_id"), expected.room_id, "room_id")
        _equal(event.get("event_id"), expected.event_id, "event_id")
        _equal(event.get("sender"), expected.sender, "sender")
        _equal(self.get_identity(expected.sender), expected.identity_ref, "identity_ref")
        content = event.get("content")
        if not isinstance(content, Mapping):
            raise AuthorityError("Matrix event content must be an object")
        if content.get("msgtype") not in {"m.text", "m.notice"}:
            raise AuthorityError("Matrix event msgtype is not an explicit Human message")
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
            verified_at=validate_ref(self.clock(), "verified_at"),
        )
        attestation.validate()
        return attestation

    def _verify_protected_bindings(self, expected: MatrixDecisionExpectation) -> None:
        if (
            self.human_identities is None
            or self.get_pending_approval is None
            or self.trusted_homeserver_ref is None
            or self.trusted_reader_identity_ref is None
        ):
            raise AuthorityError("authenticated Matrix trust configuration is required")
        validate_ref(self.trusted_homeserver_ref, "trusted_homeserver_ref")
        validate_ref(self.trusted_reader_identity_ref, "trusted_reader_identity_ref")
        protected_identity = self.human_identities.get(expected.sender)
        if protected_identity is None or protected_identity != expected.identity_ref:
            raise AuthorityError("Human sender is not present in the protected identity map")
        bound = self.get_pending_approval(expected.approval_id)
        if not isinstance(bound, MatrixDecisionExpectation):
            raise AuthorityError("pending approval authority record is unavailable")
        _validate_expectation(bound)
        for name in (
            "room_id",
            "event_id",
            "sender",
            "identity_ref",
            "approval_id",
            "phase",
            "decision",
            "campaign_id",
            "run_id",
            "trace_id",
            "revision",
            "action_ref",
            "action_hash",
            "action_fingerprint",
            "verification_ref",
        ):
            if getattr(bound, name) != getattr(expected, name):
                raise AuthorityError("Matrix decision differs from pending approval authority")


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
