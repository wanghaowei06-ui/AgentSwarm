"""Failure/Process Capsule records and read-only hit projections."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from testweaver.contracts.validator import canonical_hash

from .store import (
    AuthorityConflict,
    AuthorityError,
    AuthorityStore,
    _ensure_sealed,
    _safe_value,
    canonical_json,
    validate_hash,
    validate_ref,
)


_CAPSULE_TYPES = frozenset({"failure", "process"})
_CAPSULE_STATES = frozenset({"OPEN", "RESOLVED", "RECURRED", "NOT_OBSERVED"})


def _refs(value: Sequence[Mapping[str, Any]], field: str) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise AuthorityError(f"{field} must be a list of references")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping) or set(item) != {"ref", "content_hash"}:
            raise AuthorityError(f"{field}[{index}] has an invalid shape")
        result.append({"ref": validate_ref(item["ref"], f"{field}[{index}].ref"), "content_hash": validate_hash(item["content_hash"], f"{field}[{index}].content_hash")})
    if not result:
        raise AuthorityError(f"{field} must not be empty")
    return tuple(result)


@dataclass(frozen=True, slots=True)
class CapsuleRecord:
    """A body-free, immutable Failure or Process Capsule."""

    capsule_id: str
    capsule_type: str
    state: str
    fingerprint: str
    fault_owner: str
    target_fault_domains: tuple[str, ...]
    observation_ref: str
    evidence_refs: tuple[Mapping[str, Any], ...]
    baseline_strategy: str
    observed_strategy: str
    root_cause_ref: str | None
    repair_ref: str | None
    regression_refs: tuple[str, ...]
    artifact_ref: str
    artifact_hash: str
    run_id: str
    campaign_id: str
    trace_id: str
    revision: int
    provenance: str
    content_hash: str

    def __post_init__(self) -> None:
        self.validate()

    @classmethod
    def create(
        cls,
        *,
        capsule_id: str,
        capsule_type: str,
        state: str,
        fingerprint: str,
        fault_owner: str,
        target_fault_domains: Sequence[str],
        observation_ref: str,
        evidence_refs: Sequence[Mapping[str, Any]],
        baseline_strategy: str,
        observed_strategy: str,
        root_cause_ref: str | None,
        repair_ref: str | None,
        regression_refs: Sequence[str],
        artifact_ref: str,
        artifact_hash: str,
        run_id: str,
        campaign_id: str,
        trace_id: str,
        revision: int,
        provenance: str,
    ) -> "CapsuleRecord":
        values: dict[str, Any] = {
            "capsule_id": capsule_id,
            "capsule_type": capsule_type,
            "state": state,
            "fingerprint": fingerprint,
            "fault_owner": fault_owner,
            "target_fault_domains": tuple(target_fault_domains),
            "observation_ref": observation_ref,
            "evidence_refs": tuple(dict(item) for item in evidence_refs),
            "baseline_strategy": baseline_strategy,
            "observed_strategy": observed_strategy,
            "root_cause_ref": root_cause_ref,
            "repair_ref": repair_ref,
            "regression_refs": tuple(regression_refs),
            "artifact_ref": artifact_ref,
            "artifact_hash": artifact_hash,
            "run_id": run_id,
            "campaign_id": campaign_id,
            "trace_id": trace_id,
            "revision": revision,
            "provenance": provenance,
        }
        serialized = dict(values)
        serialized["target_fault_domains"] = list(values["target_fault_domains"])
        serialized["evidence_refs"] = [dict(item) for item in values["evidence_refs"]]
        serialized["regression_refs"] = list(values["regression_refs"])
        return cls(**values, content_hash=canonical_hash(_safe_value(serialized, "capsule")))

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "capsule_id": self.capsule_id,
            "capsule_type": self.capsule_type,
            "state": self.state,
            "fingerprint": self.fingerprint,
            "fault_owner": self.fault_owner,
            "target_fault_domains": list(self.target_fault_domains),
            "observation_ref": self.observation_ref,
            "evidence_refs": [dict(item) for item in self.evidence_refs],
            "baseline_strategy": self.baseline_strategy,
            "observed_strategy": self.observed_strategy,
            "root_cause_ref": self.root_cause_ref,
            "repair_ref": self.repair_ref,
            "regression_refs": list(self.regression_refs),
            "artifact_ref": self.artifact_ref,
            "artifact_hash": self.artifact_hash,
            "run_id": self.run_id,
            "campaign_id": self.campaign_id,
            "trace_id": self.trace_id,
            "revision": self.revision,
            "provenance": self.provenance,
        }
        if include_hash:
            value["content_hash"] = self.content_hash
        return value

    def validate(self) -> None:
        for field in (
            "capsule_id",
            "fingerprint",
            "fault_owner",
            "observation_ref",
            "baseline_strategy",
            "observed_strategy",
            "run_id",
            "campaign_id",
            "trace_id",
            "provenance",
        ):
            validate_ref(getattr(self, field), field)
        if self.capsule_type not in _CAPSULE_TYPES:
            raise AuthorityError("capsule_type must be failure or process")
        if self.state not in _CAPSULE_STATES:
            raise AuthorityError("capsule state is unsupported")
        if type(self.revision) is not int or self.revision < 1:
            raise AuthorityError("capsule revision must be positive")
        if not isinstance(self.target_fault_domains, tuple) or not self.target_fault_domains:
            raise AuthorityError("target_fault_domains must be non-empty")
        for item in self.target_fault_domains:
            validate_ref(item, "target_fault_domains[]")
        _refs(self.evidence_refs, "evidence_refs")
        if self.root_cause_ref is not None:
            validate_ref(self.root_cause_ref, "root_cause_ref")
        if self.repair_ref is not None:
            validate_ref(self.repair_ref, "repair_ref")
        if not isinstance(self.regression_refs, tuple):
            raise AuthorityError("regression_refs must be a tuple")
        for item in self.regression_refs:
            validate_ref(item, "regression_refs[]")
        validate_ref(self.artifact_ref, "artifact_ref")
        validate_hash(self.artifact_hash, "artifact_hash")
        _ensure_sealed(self.as_dict(), "content_hash")


FailureCapsule = CapsuleRecord
ProcessCapsule = CapsuleRecord


@dataclass(frozen=True, slots=True)
class CapsuleHit:
    hit_id: str
    capsule_id: str
    capsule_revision: int
    capsule_content_hash: str
    matched_fingerprint: str
    recurrence: bool
    evidence_ref: str
    run_id: str
    campaign_id: str
    trace_id: str
    occurred_at: str
    provenance: str
    content_hash: str

    def __post_init__(self) -> None:
        self.validate()

    @classmethod
    def create(
        cls,
        *,
        hit_id: str,
        capsule_id: str,
        capsule_revision: int,
        capsule_content_hash: str,
        matched_fingerprint: str,
        recurrence: bool,
        evidence_ref: str,
        run_id: str,
        campaign_id: str,
        trace_id: str,
        occurred_at: str,
        provenance: str,
    ) -> "CapsuleHit":
        values = {
            "hit_id": hit_id,
            "capsule_id": capsule_id,
            "capsule_revision": capsule_revision,
            "capsule_content_hash": capsule_content_hash,
            "matched_fingerprint": matched_fingerprint,
            "recurrence": recurrence,
            "evidence_ref": evidence_ref,
            "run_id": run_id,
            "campaign_id": campaign_id,
            "trace_id": trace_id,
            "occurred_at": occurred_at,
            "provenance": provenance,
        }
        return cls(**values, content_hash=canonical_hash(_safe_value(values, "capsule_hit")))

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "hit_id": self.hit_id,
            "capsule_id": self.capsule_id,
            "capsule_revision": self.capsule_revision,
            "capsule_content_hash": self.capsule_content_hash,
            "matched_fingerprint": self.matched_fingerprint,
            "recurrence": self.recurrence,
            "evidence_ref": self.evidence_ref,
            "run_id": self.run_id,
            "campaign_id": self.campaign_id,
            "trace_id": self.trace_id,
            "occurred_at": self.occurred_at,
            "provenance": self.provenance,
        }
        if include_hash:
            value["content_hash"] = self.content_hash
        return value

    def validate(self) -> None:
        for field in (
            "hit_id",
            "capsule_id",
            "matched_fingerprint",
            "evidence_ref",
            "run_id",
            "campaign_id",
            "trace_id",
            "occurred_at",
            "provenance",
        ):
            validate_ref(getattr(self, field), field)
        if type(self.capsule_revision) is not int or self.capsule_revision < 1:
            raise AuthorityError("capsule_revision must be positive")
        if type(self.recurrence) is not bool:
            raise AuthorityError("recurrence must be a boolean observation")
        validate_hash(self.capsule_content_hash, "capsule_content_hash")
        _ensure_sealed(self.as_dict(), "content_hash")


class CapsuleAuthority:
    def __init__(self, store: AuthorityStore):
        self.store = store

    def persist(self, capsule: CapsuleRecord) -> bool:
        capsule.validate()
        record_key = f"{capsule.capsule_id}:{capsule.revision}"
        existing = self.store.rows(
            "SELECT content_hash FROM tw_capsules WHERE record_key = ?",
            (record_key,),
        )
        if existing:
            if existing[0][0] == capsule.content_hash:
                return False
            raise AuthorityConflict("capsule revision is already bound to different content")
        latest = self.store.rows(
            "SELECT revision FROM tw_capsules WHERE capsule_id = ? ORDER BY revision DESC LIMIT 1",
            (capsule.capsule_id,),
        )
        if latest and capsule.revision != latest[0][0] + 1:
            raise AuthorityError("capsule revision must advance by one")
        if not latest and capsule.revision != 1:
            raise AuthorityError("the first capsule revision must be one")
        return self.store.append_record(
            table="tw_capsules",
            identity_column="record_key",
            identity_value=record_key,
            content_hash=capsule.content_hash,
            columns=(
                "record_key",
                "capsule_id",
                "capsule_type",
                "state",
                "fingerprint",
                "fault_owner",
                "target_fault_domains_json",
                "observation_ref",
                "evidence_refs_json",
                "baseline_strategy",
                "observed_strategy",
                "root_cause_ref",
                "repair_ref",
                "regression_refs_json",
                "artifact_ref",
                "artifact_hash",
                "run_id",
                "campaign_id",
                "trace_id",
                "revision",
                "provenance",
                "content_hash",
            ),
            values=(
                record_key,
                capsule.capsule_id,
                capsule.capsule_type,
                capsule.state,
                capsule.fingerprint,
                capsule.fault_owner,
                canonical_json(capsule.target_fault_domains),
                capsule.observation_ref,
                canonical_json(capsule.evidence_refs),
                capsule.baseline_strategy,
                capsule.observed_strategy,
                capsule.root_cause_ref,
                capsule.repair_ref,
                canonical_json(capsule.regression_refs),
                capsule.artifact_ref,
                capsule.artifact_hash,
                capsule.run_id,
                capsule.campaign_id,
                capsule.trace_id,
                capsule.revision,
                capsule.provenance,
                capsule.content_hash,
            ),
        )

    def search(
        self,
        *,
        fingerprint: str,
        capsule_type: str | None = None,
    ) -> tuple[CapsuleRecord, ...]:
        validate_ref(fingerprint, "fingerprint")
        params: list[str] = [fingerprint]
        clause = "fingerprint = ?"
        if capsule_type is not None:
            if capsule_type not in _CAPSULE_TYPES:
                raise AuthorityError("capsule_type is unsupported")
            clause += " AND capsule_type = ?"
            params.append(capsule_type)
        # Legacy/handwritten rows without a positive revision or evidence
        # reference are not searchable. Persisted records are validated on
        # write, but keep the read path fail-closed for older stores too.
        clause += " AND revision > 0 AND evidence_refs_json <> '[]'"
        rows = self.store.rows(
            "SELECT capsule_id, capsule_type, state, fingerprint, fault_owner, "
            "target_fault_domains_json, observation_ref, evidence_refs_json, baseline_strategy, "
            "observed_strategy, root_cause_ref, repair_ref, regression_refs_json, artifact_ref, "
            "artifact_hash, run_id, campaign_id, trace_id, revision, provenance, content_hash "
            f"FROM tw_capsules WHERE {clause} ORDER BY revision, capsule_id",
            params,
        )
        return tuple(
            CapsuleRecord(
                capsule_id=row[0], capsule_type=row[1], state=row[2], fingerprint=row[3], fault_owner=row[4],
                target_fault_domains=tuple(json.loads(row[5])), observation_ref=row[6],
                evidence_refs=tuple(json.loads(row[7])), baseline_strategy=row[8], observed_strategy=row[9],
                root_cause_ref=row[10], repair_ref=row[11], regression_refs=tuple(json.loads(row[12])),
                artifact_ref=row[13], artifact_hash=row[14], run_id=row[15], campaign_id=row[16], trace_id=row[17],
                revision=row[18], provenance=row[19], content_hash=row[20],
            )
            for row in rows
        )

    def record_hit(self, hit: CapsuleHit) -> bool:
        hit.validate()
        capsule = self.store.rows(
            "SELECT fingerprint, content_hash FROM tw_capsules WHERE capsule_id = ? AND revision = ?",
            (hit.capsule_id, hit.capsule_revision),
        )
        if not capsule:
            raise AuthorityError("capsule hit references an unknown capsule revision")
        if capsule[0][0] != hit.matched_fingerprint or capsule[0][1] != hit.capsule_content_hash:
            raise AuthorityError("capsule hit does not match the referenced capsule")
        return self.store.append_record(
            table="tw_capsule_hits",
            identity_column="hit_id",
            identity_value=hit.hit_id,
            content_hash=hit.content_hash,
            columns=(
                "hit_id",
                "capsule_id",
                "capsule_revision",
                "capsule_content_hash",
                "matched_fingerprint",
                "recurrence",
                "evidence_ref",
                "run_id",
                "campaign_id",
                "trace_id",
                "occurred_at",
                "provenance",
                "content_hash",
            ),
            values=(
                hit.hit_id,
                hit.capsule_id,
                hit.capsule_revision,
                hit.capsule_content_hash,
                hit.matched_fingerprint,
                hit.recurrence,
                hit.evidence_ref,
                hit.run_id,
                hit.campaign_id,
                hit.trace_id,
                hit.occurred_at,
                hit.provenance,
                hit.content_hash,
            ),
        )


__all__ = [
    "CapsuleAuthority",
    "CapsuleHit",
    "CapsuleRecord",
    "FailureCapsule",
    "ProcessCapsule",
]
