"""Sealed evidence that records, but never makes, a Manager choice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from testweaver.authority import (
    AuthorityError,
    safe_metadata,
    validate_hash,
    validate_ref,
)
from testweaver.contracts.validator import canonical_hash


@dataclass(frozen=True, slots=True)
class CandidateCapability:
    candidate_ref: str
    runtime: str
    provider: str
    model: str
    capability_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    evidence_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        for field in ("candidate_ref", "runtime", "provider", "model"):
            validate_ref(getattr(self, field), field)
        if not self.capability_refs or not self.evidence_refs:
            raise AuthorityError(
                "candidate capability and evidence references are required"
            )
        if len(self.evidence_refs) != len(self.evidence_hashes):
            raise AuthorityError("candidate evidence refs and hashes must align")
        for value in self.capability_refs + self.evidence_refs:
            validate_ref(value, "candidate_reference")
        for value in self.evidence_hashes:
            validate_hash(value, "candidate_evidence_hash")

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_ref": self.candidate_ref,
            "runtime": self.runtime,
            "provider": self.provider,
            "model": self.model,
            "capability_refs": list(self.capability_refs),
            "evidence_refs": list(self.evidence_refs),
            "evidence_hashes": list(self.evidence_hashes),
        }


@dataclass(frozen=True, slots=True)
class HeterogeneityPolicyFact:
    """A post-choice fact; deliberately exposes no choose/rank/dispatch method."""

    fact_id: str
    campaign_id: str
    run_id: str
    revision: int
    policy_ref: str
    policy_hash: str
    candidates: tuple[CandidateCapability, ...]
    manager_choice_ref: str
    manager_choice_hash: str
    chosen_candidate_ref: str
    actual_runtime: str
    actual_provider: str
    actual_model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    request_hash: str
    response_hash: str
    observed_at: str
    content_hash: str

    def __post_init__(self) -> None:
        self.validate()

    @classmethod
    def create(cls, **values: Any) -> HeterogeneityPolicyFact:
        draft = {
            **values,
            "candidates": [item.as_dict() for item in values["candidates"]],
        }
        safe_metadata(draft, "heterogeneity_policy_fact")
        return cls(**values, content_hash=canonical_hash(draft))

    def validate(self) -> None:
        for field in (
            "fact_id",
            "campaign_id",
            "run_id",
            "policy_ref",
            "manager_choice_ref",
            "chosen_candidate_ref",
            "actual_runtime",
            "actual_provider",
            "actual_model",
            "observed_at",
        ):
            validate_ref(getattr(self, field), field)
        for field in (
            "policy_hash",
            "manager_choice_hash",
            "request_hash",
            "response_hash",
            "content_hash",
        ):
            validate_hash(getattr(self, field), field)
        if type(self.revision) is not int or self.revision < 1:
            raise AuthorityError("revision must be positive")
        for field in ("input_tokens", "output_tokens", "latency_ms"):
            if type(getattr(self, field)) is not int or getattr(self, field) < 0:
                raise AuthorityError(f"{field} must be non-negative")
        if len(self.candidates) < 2:
            raise AuthorityError("heterogeneity requires at least two candidates")
        for candidate in self.candidates:
            candidate.validate()
        if len({candidate.candidate_ref for candidate in self.candidates}) != len(
            self.candidates
        ):
            raise AuthorityError("heterogeneity candidates must have unique identities")
        if (
            len(
                {
                    (candidate.runtime, candidate.provider, candidate.model)
                    for candidate in self.candidates
                }
            )
            < 2
        ):
            raise AuthorityError("heterogeneity candidates must expose distinct stacks")
        matching = [
            c for c in self.candidates if c.candidate_ref == self.chosen_candidate_ref
        ]
        if len(matching) != 1:
            raise AuthorityError(
                "Manager choice must identify exactly one declared candidate"
            )
        chosen = matching[0]
        if (chosen.runtime, chosen.provider, chosen.model) != (
            self.actual_runtime,
            self.actual_provider,
            self.actual_model,
        ):
            raise AuthorityError(
                "actual runtime identity differs from the Manager-chosen candidate"
            )
        draft = self.as_dict(include_hash=False)
        if self.content_hash != canonical_hash(draft):
            raise AuthorityError("heterogeneity policy fact is not sealed")

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "fact_id": self.fact_id,
            "campaign_id": self.campaign_id,
            "run_id": self.run_id,
            "revision": self.revision,
            "policy_ref": self.policy_ref,
            "policy_hash": self.policy_hash,
            "candidates": [item.as_dict() for item in self.candidates],
            "manager_choice_ref": self.manager_choice_ref,
            "manager_choice_hash": self.manager_choice_hash,
            "chosen_candidate_ref": self.chosen_candidate_ref,
            "actual_runtime": self.actual_runtime,
            "actual_provider": self.actual_provider,
            "actual_model": self.actual_model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "request_hash": self.request_hash,
            "response_hash": self.response_hash,
            "observed_at": self.observed_at,
        }
        if include_hash:
            value["content_hash"] = self.content_hash
        return value
