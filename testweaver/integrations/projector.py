"""Post-run projection of completed AgentTeams facts into TestWeaver authority.

The projector consumes a normalized *finished* event exported by the native
control plane.  It never calls AgentTeams APIs and has no Project/Task/Room or
Worker mutation method.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final

from testweaver.authority import (
    AuthorityError,
    AuthorityEvent,
    AuthorityStore,
    OracleResult,
    digest_bytes,
    safe_metadata,
    validate_hash,
    validate_ref,
)
from testweaver.contracts.validator import canonical_hash


class ProjectionError(AuthorityError):
    """The supplied native event is not a completed, safely projectable fact."""


_FINISHED: Final[frozenset[str]] = frozenset({"COMPLETED", "FINISHED"})
UNATTESTED_PARTIAL: Final[str] = "UNATTESTED_PARTIAL"
LIVE_SOURCE_ATTESTED: Final[str] = "LIVE_SOURCE_ATTESTED"
_COLLECTOR_ATTESTATION_TOKEN: Final[object] = object()
_COMMON: Final[frozenset[str]] = frozenset(
    {
        "event_type",
        "event_id",
        "aggregate_id",
        "revision",
        "actor",
        "occurred_at",
        "campaign_id",
        "run_id",
        "trace_id",
        "source_ref",
        "lifecycle_state",
        "facts",
    }
)
_EVENT_FIELDS: Final[dict[str, tuple[frozenset[str], frozenset[str]]]] = {
    "manager_choice": (
        frozenset(
            {
                "choice",
                "team_ref",
                "leader_ref",
                "evidence_refs",
                "policy_ref",
                "runtime",
                "provider",
                "model",
                "call_count",
                "input_tokens",
                "output_tokens",
                "latency_ms",
                "request_hash",
                "response_hash",
            }
        ),
        frozenset(
            {
                "choice",
                "team_ref",
                "leader_ref",
                "evidence_refs",
                "runtime",
                "provider",
                "model",
                "call_count",
                "input_tokens",
                "output_tokens",
                "latency_ms",
                "request_hash",
                "response_hash",
            }
        ),
    ),
    "accepted_result": (
        frozenset(
            {"task_ref", "worker_ref", "result_ref", "result_hash", "generation"}
        ),
        frozenset(
            {"task_ref", "worker_ref", "result_ref", "result_hash", "generation"}
        ),
    ),
    "handoff": (
        frozenset(
            {
                "handoff_ref",
                "handoff_hash",
                "source_team_ref",
                "target_team_ref",
                "evidence_refs",
            }
        ),
        frozenset(
            {"handoff_ref", "handoff_hash", "source_team_ref", "target_team_ref"}
        ),
    ),
    "skill_invocation": (
        frozenset(
            {
                "skill_name",
                "skill_version",
                "skill_hash",
                "invocation_ref",
                "worker_ref",
            }
        ),
        frozenset(
            {
                "skill_name",
                "skill_version",
                "skill_hash",
                "invocation_ref",
                "worker_ref",
            }
        ),
    ),
    "dsh_call": (
        frozenset(
            {
                "worker_ref",
                "runtime",
                "provider",
                "model",
                "input_tokens",
                "output_tokens",
                "latency_ms",
                "request_hash",
                "response_hash",
            }
        ),
        frozenset(
            {
                "worker_ref",
                "runtime",
                "provider",
                "model",
                "input_tokens",
                "output_tokens",
                "latency_ms",
                "request_hash",
                "response_hash",
            }
        ),
    ),
    "recovery_generation": (
        frozenset({"task_ref", "previous_generation", "new_generation", "cause_ref"}),
        frozenset({"task_ref", "previous_generation", "new_generation", "cause_ref"}),
    ),
    "late_result_rejection": (
        frozenset(
            {"task_ref", "result_ref", "result_hash", "generation", "reason_code"}
        ),
        frozenset(
            {"task_ref", "result_ref", "result_hash", "generation", "reason_code"}
        ),
    ),
    "oracle_ref": (
        frozenset(
            {
                "oracle_kind",
                "oracle_identity",
                "oracle_process_ref",
                "result_ref",
                "result_hash",
                "evidence_root_ref",
                "evidence_root_hash",
                "oracle_attestation_ref",
                "oracle_attestation_hash",
            }
        ),
        frozenset(
            {
                "oracle_kind",
                "oracle_identity",
                "oracle_process_ref",
                "result_ref",
                "result_hash",
                "evidence_root_ref",
                "evidence_root_hash",
                "oracle_attestation_ref",
                "oracle_attestation_hash",
            }
        ),
    ),
    "agentloop_ref": (
        frozenset({"trace_ref", "trace_hash", "evaluation_ref", "evaluation_hash"}),
        frozenset({"trace_ref", "trace_hash"}),
    ),
}
_HASH_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "result_hash",
        "handoff_hash",
        "skill_hash",
        "request_hash",
        "response_hash",
        "trace_hash",
        "evaluation_hash",
        "evidence_root_hash",
        "oracle_attestation_hash",
    }
)
_INTEGER_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "generation",
        "previous_generation",
        "new_generation",
        "input_tokens",
        "output_tokens",
        "latency_ms",
        "call_count",
    }
)

@dataclass(frozen=True, slots=True, repr=False)
class NativeCollectorAttestation:
    """Hash-bound receipt for bytes fetched by an allowlisted external collector."""

    attestation_ref: str
    collector_ref: str
    collector_identity_ref: str
    source_ref: str
    source_hash: str
    exact_get_ref: str
    exact_get_hash: str
    observed_at: str
    record_hash: str
    raw_bytes: bytes = field(repr=False)
    _seal: object = field(default=None, init=False, repr=False, compare=False)

    @classmethod
    def create(
        cls,
        *,
        attestation_ref: str,
        collector_ref: str,
        collector_identity_ref: str,
        source_ref: str,
        exact_get_ref: str,
        raw_bytes: bytes,
        observed_at: str,
    ) -> "NativeCollectorAttestation":
        if not isinstance(raw_bytes, bytes) or not raw_bytes:
            raise ProjectionError("collector exact GET bytes must be non-empty")
        source_hash = digest_bytes(raw_bytes)
        values = {
            "attestation_ref": attestation_ref,
            "collector_ref": collector_ref,
            "collector_identity_ref": collector_identity_ref,
            "source_ref": source_ref,
            "source_hash": source_hash,
            "exact_get_ref": exact_get_ref,
            "exact_get_hash": source_hash,
            "observed_at": observed_at,
        }
        result = cls(
            **values,
            record_hash=canonical_hash(values),
            raw_bytes=raw_bytes,
        )
        object.__setattr__(result, "_seal", _COLLECTOR_ATTESTATION_TOKEN)
        return result

    def validate(self) -> None:
        if self._seal is not _COLLECTOR_ATTESTATION_TOKEN:
            raise ProjectionError("collector attestation was not issued from exact-GET bytes")
        for field in (
            "attestation_ref",
            "collector_ref",
            "collector_identity_ref",
            "source_ref",
            "exact_get_ref",
            "observed_at",
        ):
            validate_ref(getattr(self, field), field)
        validate_hash(self.source_hash, "source_hash")
        validate_hash(self.exact_get_hash, "exact_get_hash")
        validate_hash(self.record_hash, "collector_attestation_hash")
        if self.source_hash != self.exact_get_hash:
            raise ProjectionError("collector source and exact GET hashes differ")
        if digest_bytes(self.raw_bytes) != self.exact_get_hash:
            raise ProjectionError("collector attestation does not bind its raw exact-GET bytes")
        values = {
            "attestation_ref": self.attestation_ref,
            "collector_ref": self.collector_ref,
            "collector_identity_ref": self.collector_identity_ref,
            "source_ref": self.source_ref,
            "source_hash": self.source_hash,
            "exact_get_ref": self.exact_get_ref,
            "exact_get_hash": self.exact_get_hash,
            "observed_at": self.observed_at,
        }
        if self.record_hash != canonical_hash(values):
            raise ProjectionError("collector attestation is not sealed")


NativeSourceGET = Callable[[str], NativeCollectorAttestation]
OracleResultGET = Callable[[str], OracleResult | None]


@dataclass(slots=True)
class NativeEventProjector:
    """Append safe projections to an already-owned authority store."""

    store: AuthorityStore
    get_source: NativeSourceGET | None = None
    collector_identities: Mapping[str, str] | None = None
    oracle_lookup: OracleResultGET | None = None

    def __post_init__(self) -> None:
        if self.collector_identities is not None:
            self.collector_identities = MappingProxyType(dict(self.collector_identities))

    def project(
        self,
        raw_bytes: bytes,
        *,
        attestation: NativeCollectorAttestation | None = None,
    ) -> tuple[AuthorityEvent, bool]:
        event = self.materialize(raw_bytes, attestation=attestation)
        return event, self.store.append_event(event)

    def project_many(self, records: Sequence[bytes]) -> tuple[AuthorityEvent, ...]:
        projected: list[AuthorityEvent] = []
        for raw in records:
            event, _inserted = self.project(raw)
            projected.append(event)
        return tuple(projected)

    def materialize(
        self,
        raw_bytes: bytes,
        *,
        attestation: NativeCollectorAttestation | None = None,
    ) -> AuthorityEvent:
        if not isinstance(raw_bytes, bytes) or not raw_bytes:
            raise ProjectionError("native raw event must be non-empty bytes")
        try:
            value = json.loads(raw_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProjectionError("native raw event is not valid UTF-8 JSON") from exc
        if not isinstance(value, dict):
            raise ProjectionError("native raw event must be an object")
        unknown = set(value) - _COMMON
        if unknown:
            raise ProjectionError(
                f"native raw event has unknown fields: {sorted(unknown)}"
            )
        missing = _COMMON - set(value)
        if missing:
            raise ProjectionError(
                f"native raw event is missing fields: {sorted(missing)}"
            )
        if str(value["lifecycle_state"]).upper() not in _FINISHED:
            raise ProjectionError("only a completed native event may be projected")

        event_type = _ref(value["event_type"], "event_type")
        if event_type not in _EVENT_FIELDS:
            raise ProjectionError("native event type is not projectable")
        facts = _facts(event_type, value["facts"])
        source_ref = _ref(value["source_ref"], "source_ref")
        source_hash = digest_bytes(raw_bytes)
        source_classification, attestation_ref, attestation_hash = self._source_trust(
            raw_bytes=raw_bytes,
            source_ref=source_ref,
            attestation=attestation,
        )
        oracle_verified = self._verify_oracle_reference(event_type, facts, value)
        if event_type == "oracle_ref" and not oracle_verified:
            source_classification = UNATTESTED_PARTIAL
        payload = safe_metadata(
            {
                "native_source_ref": source_ref,
                "native_source_hash": source_hash,
                "projection_classification": source_classification,
                "collector_attestation_ref": attestation_ref,
                "collector_attestation_hash": attestation_hash,
                "oracle_readback_verified": oracle_verified,
                **facts,
            },
            "projected_payload",
        )
        revision = value["revision"]
        if type(revision) is not int or revision < 1:
            raise ProjectionError("revision must be a positive integer")
        event_id = _ref(value["event_id"], "event_id")
        return AuthorityEvent.create(
            event_id=event_id,
            aggregate_id=_ref(value["aggregate_id"], "aggregate_id"),
            aggregate_type="native-agentteams-run",
            revision=revision,
            event_type=event_type,
            actor=_ref(value["actor"], "actor"),
            idempotency_key=f"native-projection:{source_hash}",
            occurred_at=_ref(value["occurred_at"], "occurred_at"),
            payload=payload,
            request_hash=source_hash,
            run_id=_ref(value["run_id"], "run_id"),
            campaign_id=_ref(value["campaign_id"], "campaign_id"),
            trace_id=_ref(value["trace_id"], "trace_id"),
            provenance=source_ref,
        )

    def _source_trust(
        self,
        *,
        raw_bytes: bytes,
        source_ref: str,
        attestation: NativeCollectorAttestation | None,
    ) -> tuple[str, str | None, str | None]:
        if attestation is None:
            return UNATTESTED_PARTIAL, None, None
        attestation.validate()
        if self.get_source is None or self.collector_identities is None:
            raise ProjectionError(
                "collector attestation requires protected exact-GET configuration"
            )
        protected_identity = self.collector_identities.get(attestation.collector_ref)
        if protected_identity is None or protected_identity != attestation.collector_identity_ref:
            raise ProjectionError("collector identity is not present in the protected allowlist")
        if attestation.source_ref != source_ref:
            raise ProjectionError("collector attestation source does not match the native event")
        readback = self.get_source(attestation.exact_get_ref)
        if not isinstance(readback, NativeCollectorAttestation):
            raise ProjectionError("collector exact GET did not return an authenticated receipt")
        readback.validate()
        if readback.record_hash != attestation.record_hash:
            raise ProjectionError("collector exact GET differs from the supplied attestation")
        if readback.raw_bytes != raw_bytes:
            raise ProjectionError("collector exact GET bytes differ from the projected bytes")
        if digest_bytes(readback.raw_bytes) != attestation.exact_get_hash:
            raise ProjectionError("collector exact GET hash mismatch")
        return LIVE_SOURCE_ATTESTED, attestation.attestation_ref, attestation.record_hash

    def _verify_oracle_reference(
        self, event_type: str, facts: Mapping[str, Any], envelope: Mapping[str, Any]
    ) -> bool:
        if event_type != "oracle_ref" or self.oracle_lookup is None:
            return False
        result = self.oracle_lookup(facts["oracle_attestation_ref"])
        if result is None:
            raise ProjectionError("Oracle attestation cannot be read back")
        result.validate()
        expected = {
            "oracle_kind": result.oracle_kind.upper(),
            "oracle_identity": result.identity_ref,
            "oracle_process_ref": result.process_ref,
            "result_ref": result.result_ref,
            "result_hash": result.result_hash,
            "evidence_root_ref": result.evidence_root_ref,
            "evidence_root_hash": result.evidence_root_hash,
            "oracle_attestation_ref": result.result_id,
            "oracle_attestation_hash": result.content_hash,
        }
        if any(facts.get(field) != child for field, child in expected.items()):
            raise ProjectionError("Oracle projection differs from its full readback")
        for field in ("run_id", "campaign_id", "trace_id"):
            if envelope[field] != getattr(result, field):
                raise ProjectionError("Oracle projection crosses its authority lineage")
        return True


def _ref(value: Any, field: str) -> str:
    try:
        return validate_ref(value, field)
    except AuthorityError as exc:
        raise ProjectionError(str(exc)) from exc


def _facts(event_type: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectionError("facts must be an object")
    allowed, required = _EVENT_FIELDS[event_type]
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise ProjectionError(
            f"{event_type} has unknown fact fields: {sorted(unknown)}"
        )
    if missing:
        raise ProjectionError(f"{event_type} is missing fact fields: {sorted(missing)}")
    facts = safe_metadata(value, "facts")
    for field in _HASH_FIELDS & set(facts):
        validate_hash(facts[field], field)
    for field in _INTEGER_FIELDS & set(facts):
        number = facts[field]
        if type(number) is not int or number < 0:
            raise ProjectionError(f"{field} must be a non-negative integer")
    for field, child in facts.items():
        if field.endswith("_ref") or field in {
            "choice",
            "runtime",
            "provider",
            "model",
            "skill_name",
            "skill_version",
            "oracle_kind",
            "oracle_identity",
            "reason_code",
        }:
            _ref(child, field)
        elif field.endswith("_refs"):
            if not isinstance(child, list) or not child:
                raise ProjectionError(f"{field} must be a non-empty reference list")
            for index, item in enumerate(child):
                _ref(item, f"{field}[{index}]")
    if event_type == "agentloop_ref" and (
        ("evaluation_ref" in facts) != ("evaluation_hash" in facts)
    ):
        raise ProjectionError(
            "AgentLoop evaluation ref and hash must be supplied together"
        )
    if event_type == "oracle_ref" and facts["oracle_kind"] not in {
        "OUTCOME",
        "BOUNDARY",
    }:
        raise ProjectionError("oracle kind must be OUTCOME or BOUNDARY")
    if event_type == "dsh_call" and facts["runtime"] != "deepseek-harness":
        raise ProjectionError("DSH call runtime must be deepseek-harness")
    if event_type == "manager_choice" and facts["call_count"] < 1:
        raise ProjectionError("Manager choice must bind at least one provider call")
    if event_type == "recovery_generation" and (
        facts["new_generation"] <= facts["previous_generation"]
    ):
        raise ProjectionError("recovery generation must advance")
    return facts
