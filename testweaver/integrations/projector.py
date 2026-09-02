"""Post-run projection of completed AgentTeams facts into TestWeaver authority.

The projector consumes a normalized *finished* event exported by the native
control plane.  It never calls AgentTeams APIs and has no Project/Task/Room or
Worker mutation method.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from testweaver.authority import (
    AuthorityError,
    AuthorityEvent,
    AuthorityStore,
    digest_bytes,
    safe_metadata,
    validate_hash,
    validate_ref,
)


class ProjectionError(AuthorityError):
    """The supplied native event is not a completed, safely projectable fact."""


_FINISHED: Final[frozenset[str]] = frozenset({"COMPLETED", "FINISHED"})
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
        frozenset({"choice", "team_ref", "leader_ref", "evidence_refs", "policy_ref"}),
        frozenset({"choice", "team_ref", "leader_ref", "evidence_refs"}),
    ),
    "accepted_result": (
        frozenset(
            {"task_ref", "worker_ref", "result_ref", "result_hash", "generation"}
        ),
        frozenset({"task_ref", "worker_ref", "result_ref", "result_hash"}),
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
        frozenset({"oracle_kind", "oracle_identity", "result_ref", "result_hash"}),
        frozenset({"oracle_kind", "oracle_identity", "result_ref", "result_hash"}),
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
    }
)


@dataclass(slots=True)
class NativeEventProjector:
    """Append safe projections to an already-owned authority store."""

    store: AuthorityStore

    def project(self, raw_bytes: bytes) -> tuple[AuthorityEvent, bool]:
        event = self.materialize(raw_bytes)
        return event, self.store.append_event(event)

    def project_many(self, records: Sequence[bytes]) -> tuple[AuthorityEvent, ...]:
        projected: list[AuthorityEvent] = []
        for raw in records:
            event, _inserted = self.project(raw)
            projected.append(event)
        return tuple(projected)

    @staticmethod
    def materialize(raw_bytes: bytes) -> AuthorityEvent:
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
        payload = safe_metadata(
            {
                "native_source_ref": source_ref,
                "native_source_hash": source_hash,
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
    if event_type == "recovery_generation" and (
        facts["new_generation"] <= facts["previous_generation"]
    ):
        raise ProjectionError("recovery generation must advance")
    return facts
