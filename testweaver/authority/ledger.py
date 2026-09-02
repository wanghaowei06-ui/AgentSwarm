"""Observed side-effect/tool ledger; this module never performs the call."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from testweaver.contracts.validator import canonical_hash

from .store import AuthorityError, AuthorityStore, _ensure_sealed, _safe_value, validate_hash, validate_ref


_DECISIONS = frozenset({"allow", "deny"})
_EFFECTS = frozenset({"none", "read", "write", "external", "blocked", "unknown"})
_FENCING = frozenset({"passed", "blocked", "not_applicable"})


@dataclass(frozen=True, slots=True)
class SideEffectEntry:
    entry_id: str
    call_ref: str
    run_id: str
    campaign_id: str
    trace_id: str
    actor_ref: str
    tool_ref: str
    operation: str
    target_ref: str
    decision: str
    effect: str
    fencing: str
    observed: bool
    occurred_at: str
    request_hash: str
    result_hash: str | None
    provenance: str
    content_hash: str

    def __post_init__(self) -> None:
        self.validate()

    @classmethod
    def create(
        cls,
        *,
        entry_id: str,
        call_ref: str,
        run_id: str,
        campaign_id: str,
        trace_id: str,
        actor_ref: str,
        tool_ref: str,
        operation: str,
        target_ref: str,
        decision: str,
        effect: str,
        fencing: str,
        occurred_at: str,
        request_hash: str,
        result_hash: str | None,
        provenance: str,
        observed: bool = True,
    ) -> "SideEffectEntry":
        values = {
            "entry_id": entry_id,
            "call_ref": call_ref,
            "run_id": run_id,
            "campaign_id": campaign_id,
            "trace_id": trace_id,
            "actor_ref": actor_ref,
            "tool_ref": tool_ref,
            "operation": operation,
            "target_ref": target_ref,
            "decision": decision,
            "effect": effect,
            "fencing": fencing,
            "observed": observed,
            "occurred_at": occurred_at,
            "request_hash": request_hash,
            "result_hash": result_hash,
            "provenance": provenance,
        }
        return cls(**values, content_hash=canonical_hash(_safe_value(values, "side_effect")))

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "entry_id": self.entry_id,
            "call_ref": self.call_ref,
            "run_id": self.run_id,
            "campaign_id": self.campaign_id,
            "trace_id": self.trace_id,
            "actor_ref": self.actor_ref,
            "tool_ref": self.tool_ref,
            "operation": self.operation,
            "target_ref": self.target_ref,
            "decision": self.decision,
            "effect": self.effect,
            "fencing": self.fencing,
            "observed": self.observed,
            "occurred_at": self.occurred_at,
            "request_hash": self.request_hash,
            "result_hash": self.result_hash,
            "provenance": self.provenance,
        }
        if include_hash:
            value["content_hash"] = self.content_hash
        return value

    def validate(self) -> None:
        for field in (
            "entry_id",
            "call_ref",
            "run_id",
            "campaign_id",
            "trace_id",
            "actor_ref",
            "tool_ref",
            "operation",
            "target_ref",
            "occurred_at",
            "provenance",
        ):
            validate_ref(getattr(self, field), field)
        if self.decision not in _DECISIONS:
            raise AuthorityError("side-effect decision must be allow or deny")
        if self.effect not in _EFFECTS:
            raise AuthorityError("side-effect effect is unsupported")
        if self.fencing not in _FENCING:
            raise AuthorityError("side-effect fencing is unsupported")
        if self.observed is not True:
            raise AuthorityError("ledger accepts only an observed actual call")
        if self.decision == "deny" and self.fencing != "blocked":
            raise AuthorityError("denied call must have blocked fencing")
        if self.decision == "allow" and self.fencing == "blocked":
            raise AuthorityError("allowed call cannot have blocked fencing")
        validate_hash(self.request_hash, "request_hash")
        if self.result_hash is not None:
            validate_hash(self.result_hash, "result_hash")
        _ensure_sealed(self.as_dict(), "content_hash")


class SideEffectLedger:
    def __init__(self, store: AuthorityStore):
        self.store = store

    def append(self, entry: SideEffectEntry) -> bool:
        entry.validate()
        return self.store.append_record(
            table="tw_side_effect_ledger",
            identity_column="call_ref",
            identity_value=entry.call_ref,
            content_hash=entry.content_hash,
            columns=(
                "entry_id",
                "call_ref",
                "run_id",
                "campaign_id",
                "trace_id",
                "actor_ref",
                "tool_ref",
                "operation",
                "target_ref",
                "decision",
                "effect",
                "fencing",
                "observed",
                "occurred_at",
                "request_hash",
                "result_hash",
                "provenance",
                "content_hash",
            ),
            values=(
                entry.entry_id,
                entry.call_ref,
                entry.run_id,
                entry.campaign_id,
                entry.trace_id,
                entry.actor_ref,
                entry.tool_ref,
                entry.operation,
                entry.target_ref,
                entry.decision,
                entry.effect,
                entry.fencing,
                entry.observed,
                entry.occurred_at,
                entry.request_hash,
                entry.result_hash,
                entry.provenance,
                entry.content_hash,
            ),
        )

    def entries(self, *, run_id: str | None = None) -> tuple[SideEffectEntry, ...]:
        clauses = ""
        params: tuple[str, ...] = ()
        if run_id is not None:
            validate_ref(run_id, "run_id")
            clauses = " WHERE run_id = ?"
            params = (run_id,)
        rows = self.store.rows(
            "SELECT entry_id, call_ref, run_id, campaign_id, trace_id, actor_ref, tool_ref, "
            "operation, target_ref, decision, effect, fencing, observed, occurred_at, "
            "request_hash, result_hash, provenance, content_hash "
            f"FROM tw_side_effect_ledger{clauses} ORDER BY occurred_at, entry_id",
            params,
        )
        return tuple(
            SideEffectEntry(
                entry_id=row[0],
                call_ref=row[1],
                run_id=row[2],
                campaign_id=row[3],
                trace_id=row[4],
                actor_ref=row[5],
                tool_ref=row[6],
                operation=row[7],
                target_ref=row[8],
                decision=row[9],
                effect=row[10],
                fencing=row[11],
                observed=bool(row[12]),
                occurred_at=row[13],
                request_hash=row[14],
                result_hash=row[15],
                provenance=row[16],
                content_hash=row[17],
            )
            for row in rows
        )


__all__ = ["SideEffectEntry", "SideEffectLedger"]
