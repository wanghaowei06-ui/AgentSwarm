"""Independent Outcome/Boundary Oracle result references."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from testweaver.contracts.validator import canonical_hash

from .store import (
    AuthorityError,
    AuthorityStore,
    RecordInsert,
    _ensure_sealed,
    _safe_value,
    canonical_json,
    validate_hash,
    validate_ref,
)


_ORACLE_KINDS = frozenset({"outcome", "boundary"})
_STATUSES = frozenset({"PASS", "FAIL", "UNCERTAIN", "NOT_OBSERVED", "NOT_AVAILABLE"})


def _evidence_refs(value: Sequence[Mapping[str, Any]]) -> tuple[dict[str, str], ...]:
    if not isinstance(value, (list, tuple)):
        raise AuthorityError("evidence_refs must be a list")
    result: list[dict[str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping) or set(item) != {"ref", "content_hash"}:
            raise AuthorityError(f"evidence_refs[{index}] has an invalid shape")
        result.append(
            {
                "ref": validate_ref(item["ref"], f"evidence_refs[{index}].ref"),
                "content_hash": validate_hash(item["content_hash"], f"evidence_refs[{index}].content_hash"),
            }
        )
    if not result:
        raise AuthorityError("evidence_refs must not be empty")
    return tuple(result)


def _evidence_keys(value: Sequence[Mapping[str, Any]]) -> set[tuple[str, str]]:
    return {(item["ref"], item["content_hash"]) for item in value}


@dataclass(frozen=True, slots=True)
class OracleResult:
    result_id: str
    oracle_kind: str
    run_id: str
    campaign_id: str
    trace_id: str
    identity_ref: str
    process_ref: str
    result_ref: str
    result_hash: str
    evidence_root_ref: str
    evidence_root_hash: str
    evidence_refs: tuple[Mapping[str, Any], ...]
    gold_ref: str | None
    source_ref: str
    status: str
    provenance: str
    content_hash: str
    read_result_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.validate()

    @classmethod
    def create(
        cls,
        *,
        result_id: str,
        oracle_kind: str,
        run_id: str,
        campaign_id: str,
        trace_id: str,
        identity_ref: str,
        process_ref: str,
        result_ref: str,
        result_hash: str,
        evidence_root_ref: str,
        evidence_root_hash: str,
        evidence_refs: Sequence[Mapping[str, Any]],
        gold_ref: str | None,
        source_ref: str,
        status: str,
        provenance: str,
        read_result_refs: Sequence[str] = (),
    ) -> "OracleResult":
        values = {
            "result_id": result_id,
            "oracle_kind": oracle_kind,
            "run_id": run_id,
            "campaign_id": campaign_id,
            "trace_id": trace_id,
            "identity_ref": identity_ref,
            "process_ref": process_ref,
            "result_ref": result_ref,
            "result_hash": result_hash,
            "evidence_root_ref": evidence_root_ref,
            "evidence_root_hash": evidence_root_hash,
            "evidence_refs": tuple(dict(item) for item in evidence_refs),
            "gold_ref": gold_ref,
            "source_ref": source_ref,
            "status": status,
            "provenance": provenance,
            "read_result_refs": tuple(read_result_refs),
        }
        serialized = dict(values)
        serialized["evidence_refs"] = [dict(item) for item in values["evidence_refs"]]
        serialized["read_result_refs"] = list(values["read_result_refs"])
        return cls(**values, content_hash=canonical_hash(_safe_value(serialized, "oracle_result")))

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "result_id": self.result_id,
            "oracle_kind": self.oracle_kind,
            "run_id": self.run_id,
            "campaign_id": self.campaign_id,
            "trace_id": self.trace_id,
            "identity_ref": self.identity_ref,
            "process_ref": self.process_ref,
            "result_ref": self.result_ref,
            "result_hash": self.result_hash,
            "evidence_root_ref": self.evidence_root_ref,
            "evidence_root_hash": self.evidence_root_hash,
            "evidence_refs": [dict(item) for item in self.evidence_refs],
            "gold_ref": self.gold_ref,
            "source_ref": self.source_ref,
            "status": self.status,
            "provenance": self.provenance,
            "read_result_refs": list(self.read_result_refs),
        }
        if include_hash:
            value["content_hash"] = self.content_hash
        return value

    def validate(self) -> None:
        for field in (
            "result_id",
            "run_id",
            "campaign_id",
            "trace_id",
            "identity_ref",
            "process_ref",
            "result_ref",
            "evidence_root_ref",
            "source_ref",
            "provenance",
        ):
            validate_ref(getattr(self, field), field)
        if self.oracle_kind not in _ORACLE_KINDS:
            raise AuthorityError("oracle_kind must be outcome or boundary")
        validate_hash(self.result_hash, "result_hash")
        validate_hash(self.evidence_root_hash, "evidence_root_hash")
        _evidence_refs(self.evidence_refs)
        if self.gold_ref is not None:
            validate_ref(self.gold_ref, "gold_ref")
        if self.oracle_kind == "boundary" and self.gold_ref is not None:
            raise AuthorityError("Boundary Oracle gold_ref must be null")
        if self.status not in _STATUSES:
            raise AuthorityError("oracle status is unsupported")
        if self.read_result_refs:
            raise AuthorityError("an Oracle may not reference another Oracle result")
        _ensure_sealed(self.as_dict(), "content_hash")


def validate_oracle_pair(outcome: OracleResult, boundary: OracleResult) -> None:
    """Validate shared input and independent output custody without scoring."""

    outcome.validate()
    boundary.validate()
    if outcome.oracle_kind != "outcome" or boundary.oracle_kind != "boundary":
        raise AuthorityError("pair must be Outcome followed by Boundary")
    for field in ("run_id", "campaign_id", "trace_id", "evidence_root_ref", "evidence_root_hash"):
        if getattr(outcome, field) != getattr(boundary, field):
            raise AuthorityError(f"Oracle pair does not share {field}")
    if not _evidence_keys(outcome.evidence_refs).intersection(_evidence_keys(boundary.evidence_refs)):
        raise AuthorityError("Oracle pair must share at least one public evidence reference")
    if outcome.identity_ref == boundary.identity_ref:
        raise AuthorityError("Oracle identities must be distinct")
    if outcome.process_ref == boundary.process_ref:
        raise AuthorityError("Oracle processes must be distinct")
    if outcome.result_ref == boundary.result_ref or outcome.result_hash == boundary.result_hash:
        raise AuthorityError("Oracle result references and hashes must be distinct")


class OracleAuthority:
    def __init__(self, store: AuthorityStore):
        self.store = store

    @staticmethod
    def _insert_spec(result: OracleResult) -> RecordInsert:
        return RecordInsert(
            table="tw_oracle_results",
            identity_column="result_id",
            identity_value=result.result_id,
            content_hash=result.content_hash,
            columns=(
                "result_id",
                "oracle_kind",
                "run_id",
                "campaign_id",
                "trace_id",
                "identity_ref",
                "process_ref",
                "result_ref",
                "result_hash",
                "evidence_root_ref",
                "evidence_root_hash",
                "evidence_refs_json",
                "gold_ref",
                "source_ref",
                "status",
                "provenance",
                "content_hash",
            ),
            values=(
                result.result_id,
                result.oracle_kind,
                result.run_id,
                result.campaign_id,
                result.trace_id,
                result.identity_ref,
                result.process_ref,
                result.result_ref,
                result.result_hash,
                result.evidence_root_ref,
                result.evidence_root_hash,
                canonical_json(result.evidence_refs),
                result.gold_ref,
                result.source_ref,
                result.status,
                result.provenance,
                result.content_hash,
            ),
        )

    def persist(self, result: OracleResult) -> bool:
        result.validate()
        return self.store.append_records((self._insert_spec(result),))[0]

    def persist_pair(self, outcome: OracleResult, boundary: OracleResult) -> tuple[bool, bool]:
        validate_oracle_pair(outcome, boundary)
        return self.store.append_records((self._insert_spec(outcome), self._insert_spec(boundary)))


__all__ = ["OracleAuthority", "OracleResult", "validate_oracle_pair"]
