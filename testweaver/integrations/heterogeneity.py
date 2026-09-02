"""Sealed evidence that records, but never makes, a Manager choice."""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from typing import Any

from testweaver.authority import (
    AuthorityError,
    AuthorityEvent,
    safe_metadata,
    validate_hash,
    validate_ref,
)
from testweaver.contracts.validator import canonical_hash
from testweaver.integrations.projector import LIVE_SOURCE_ATTESTED, UNATTESTED_PARTIAL

_ATTESTED_FACT_TOKEN = object()


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
    projection_classification: str
    manager_source_attestation_ref: str | None
    manager_source_attestation_hash: str | None
    runtime_source_attestation_ref: str | None
    runtime_source_attestation_hash: str | None
    content_hash: str
    _trust_token: InitVar[object] = None
    _trust_seal: object = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self, _trust_token: object) -> None:
        if _trust_token is _ATTESTED_FACT_TOKEN:
            object.__setattr__(self, "_trust_seal", _ATTESTED_FACT_TOKEN)
        self.validate()

    @classmethod
    def create(cls, **values: Any) -> HeterogeneityPolicyFact:
        forbidden = {
            "projection_classification",
            "manager_source_attestation_ref",
            "manager_source_attestation_hash",
            "runtime_source_attestation_ref",
            "runtime_source_attestation_hash",
        }
        if forbidden.intersection(values):
            raise AuthorityError("caller cannot self-assert heterogeneity source trust")
        return cls._create_with_trust(
            values,
            projection_classification=UNATTESTED_PARTIAL,
            manager_source_attestation_ref=None,
            manager_source_attestation_hash=None,
            runtime_source_attestation_ref=None,
            runtime_source_attestation_hash=None,
            trust_token=None,
        )

    @classmethod
    def create_attested(
        cls,
        *,
        manager_projection: AuthorityEvent,
        runtime_projection: AuthorityEvent,
        **values: Any,
    ) -> HeterogeneityPolicyFact:
        """Seal a fact only after two independently source-attested projections."""

        _attested_projection(manager_projection, "manager_choice")
        _attested_projection(runtime_projection, "dsh_call")
        if (
            manager_projection.run_id != values.get("run_id")
            or runtime_projection.run_id != values.get("run_id")
            or manager_projection.campaign_id != values.get("campaign_id")
            or runtime_projection.campaign_id != values.get("campaign_id")
        ):
            raise AuthorityError("heterogeneity projections cross their run lineage")
        if (
            values.get("manager_choice_ref") != manager_projection.provenance
            or values.get("manager_choice_hash") != manager_projection.request_hash
        ):
            raise AuthorityError("Manager choice does not match its attested projection")
        runtime_payload = runtime_projection.payload
        for field in (
            "actual_runtime",
            "actual_provider",
            "actual_model",
            "input_tokens",
            "output_tokens",
            "latency_ms",
            "request_hash",
            "response_hash",
        ):
            projected_field = field.removeprefix("actual_")
            if values.get(field) != runtime_payload.get(projected_field):
                raise AuthorityError("runtime observation differs from its attested projection")
        return cls._create_with_trust(
            values,
            projection_classification=LIVE_SOURCE_ATTESTED,
            manager_source_attestation_ref=manager_projection.payload[
                "collector_attestation_ref"
            ],
            manager_source_attestation_hash=manager_projection.payload[
                "collector_attestation_hash"
            ],
            runtime_source_attestation_ref=runtime_projection.payload[
                "collector_attestation_ref"
            ],
            runtime_source_attestation_hash=runtime_projection.payload[
                "collector_attestation_hash"
            ],
            trust_token=_ATTESTED_FACT_TOKEN,
        )

    @classmethod
    def _create_with_trust(
        cls,
        values: dict[str, Any],
        *,
        projection_classification: str,
        manager_source_attestation_ref: str | None,
        manager_source_attestation_hash: str | None,
        runtime_source_attestation_ref: str | None,
        runtime_source_attestation_hash: str | None,
        trust_token: object,
    ) -> HeterogeneityPolicyFact:
        draft = {
            **values,
            "candidates": [item.as_dict() for item in values["candidates"]],
            "projection_classification": projection_classification,
            "manager_source_attestation_ref": manager_source_attestation_ref,
            "manager_source_attestation_hash": manager_source_attestation_hash,
            "runtime_source_attestation_ref": runtime_source_attestation_ref,
            "runtime_source_attestation_hash": runtime_source_attestation_hash,
        }
        safe_metadata(draft, "heterogeneity_policy_fact")
        return cls(
            **values,
            projection_classification=projection_classification,
            manager_source_attestation_ref=manager_source_attestation_ref,
            manager_source_attestation_hash=manager_source_attestation_hash,
            runtime_source_attestation_ref=runtime_source_attestation_ref,
            runtime_source_attestation_hash=runtime_source_attestation_hash,
            content_hash=canonical_hash(draft),
            _trust_token=trust_token,
        )

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
        if self.projection_classification not in {
            UNATTESTED_PARTIAL,
            LIVE_SOURCE_ATTESTED,
        }:
            raise AuthorityError("heterogeneity projection classification is invalid")
        attestation_fields = (
            self.manager_source_attestation_ref,
            self.manager_source_attestation_hash,
            self.runtime_source_attestation_ref,
            self.runtime_source_attestation_hash,
        )
        if self.projection_classification == LIVE_SOURCE_ATTESTED:
            if self._trust_seal is not _ATTESTED_FACT_TOKEN:
                raise AuthorityError("caller cannot self-assert heterogeneity source trust")
            if any(value is None for value in attestation_fields):
                raise AuthorityError("attested heterogeneity fact lacks source attestations")
            validate_ref(self.manager_source_attestation_ref, "manager_source_attestation_ref")
            validate_hash(
                self.manager_source_attestation_hash,
                "manager_source_attestation_hash",
            )
            validate_ref(self.runtime_source_attestation_ref, "runtime_source_attestation_ref")
            validate_hash(
                self.runtime_source_attestation_hash,
                "runtime_source_attestation_hash",
            )
        elif any(value is not None for value in attestation_fields):
            raise AuthorityError("partial heterogeneity fact cannot retain trusted attestations")
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
            "projection_classification": self.projection_classification,
            "manager_source_attestation_ref": self.manager_source_attestation_ref,
            "manager_source_attestation_hash": self.manager_source_attestation_hash,
            "runtime_source_attestation_ref": self.runtime_source_attestation_ref,
            "runtime_source_attestation_hash": self.runtime_source_attestation_hash,
        }
        if include_hash:
            value["content_hash"] = self.content_hash
        return value


def _attested_projection(event: AuthorityEvent, event_type: str) -> None:
    event.validate()
    if event.event_type != event_type:
        raise AuthorityError(f"expected an attested {event_type} projection")
    if event.payload.get("projection_classification") != LIVE_SOURCE_ATTESTED:
        raise AuthorityError(f"{event_type} projection is not externally attested")
    for suffix in ("ref", "hash"):
        if not event.payload.get(f"collector_attestation_{suffix}"):
            raise AuthorityError(f"{event_type} projection lacks collector attestation")
