"""Fail-closed, pure in-memory Skill evolution records.

AgentTeams owns Skill discovery/load/invoke and Agent/Project/Task state. This
module only binds externally supplied references and advances one explicit
review sequence. It performs no I/O, dispatch, package mutation, or signing.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import InitVar, dataclass, field, fields
from typing import ClassVar, Literal, TypeVar

from testweaver.contracts.validator import canonical_hash


class SkillOpsError(ValueError):
    """Raised for malformed or unsafe Skill evolution data."""


class SkillOpsStateError(SkillOpsError):
    """Raised when a required prior evolution fact is absent."""


_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REF = re.compile(r"^\S{1,2048}$")
_SOURCE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
_KINDS = frozenset({"dataset", "evaluation", "trace", "evidence", "result"})
_OBSERVATIONS = frozenset({"trace", "evidence", "result"})
_SOURCES = {
    "dataset": frozenset({"frozen-dataset", "evaluation-export"}),
    "evaluation": frozenset({"evaluation-export", "agentloop-sls"}),
    "trace": frozenset({"agentteams-native", "otel-genai", "agentloop-sls", "evaluation-export"}),
    "evidence": frozenset({"agentteams-native", "otel-genai", "agentloop-sls", "evaluation-export"}),
    "result": frozenset({"agentteams-native", "otel-genai", "agentloop-sls", "evaluation-export"}),
}
_STATUSES = frozenset({"PASS", "FAIL", "BLOCKED", "NOT_AVAILABLE"})
_PROVENANCES = frozenset({"LIVE", "FROZEN", "FIXTURE", "SYNTHETIC", "REPLAY"})
_CLASSIFICATIONS = frozenset({"LIVE_ATTESTED", "NON_LIVE"})
_READBACK_SOURCE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
_READBACK_TOKEN = object()
_MAX_READBACK_BYTES = 4 * 1024 * 1024
_ARTIFACT_READBACK_SOURCES = {
    "agentteams-native": "agentteams",
    "otel-genai": "otel",
    "agentloop-sls": "agentloop",
    "evaluation-export": "evaluation",
}


def _text(value: object, field: str, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise SkillOpsError(f"{field} must be a bounded string")
    if any(char.isspace() or ord(char) < 0x20 for char in value):
        raise SkillOpsError(f"{field} must not contain whitespace or control characters")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise SkillOpsError(f"{field} has an invalid format")
    return value


def _ref(value: object, field: str) -> str:
    return _text(value, field, _REF)


def _name(value: object, field: str) -> str:
    return _text(value, field, _NAME)


def _version(value: object, field: str) -> str:
    return _text(value, field, _VERSION)


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise SkillOpsError(f"{field} must be a sha256 digest")
    return value


def _revision(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SkillOpsError(f"{field} must be a positive immutable revision")
    return value


@dataclass(frozen=True, slots=True, repr=False)
class ExternalReadback:
    """An opaque token issued after a collector read the external source.

    The token deliberately is not part of any serialized record.  A plain
    ``attested=True`` flag or a caller-supplied mapping cannot create one: the
    only public constructor that seals it requires the raw bytes just read by
    the external collector.  Integration code remains responsible for doing
    the real Matrix/AgentTeams/registry/AgentLoop readback; this module only
    carries the resulting hash across the contract boundary.
    """

    source: str
    ref: str
    raw_hash: str
    _seal: object = field(default=None, init=False, repr=False, compare=False)

    @classmethod
    def from_raw(cls, *, source: str, ref: str, raw: bytes) -> "ExternalReadback":
        if not isinstance(source, str) or _READBACK_SOURCE.fullmatch(source) is None:
            raise SkillOpsError("external readback source is invalid")
        _ref(ref, "external readback ref")
        if not isinstance(raw, bytes) or not raw or len(raw) > _MAX_READBACK_BYTES:
            raise SkillOpsError("external readback raw bytes are required")
        value = cls(source=source, ref=ref, raw_hash=f"sha256:{hashlib.sha256(raw).hexdigest()}")
        object.__setattr__(value, "_seal", _READBACK_TOKEN)
        return value

    @property
    def verified(self) -> bool:
        return self._seal is _READBACK_TOKEN


def _artifact(value: object, field: str, kind: str) -> ArtifactRef:
    if not isinstance(value, ArtifactRef) or value.kind != kind:
        raise SkillOpsError(f"{field} must be an {kind} reference")
    return value


def _jsonable(value: object) -> object:
    if isinstance(value, ArtifactRef):
        return value.as_dict()
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


T = TypeVar("T")


def _make(cls: type[T], values: dict[str, object]) -> T:
    payload_values = {key: value for key, value in values.items() if key != "verified_readback"}
    payload = {"artifact_type": cls.artifact_type, **_jsonable(payload_values)}  # type: ignore[attr-defined]
    return cls(**values, record_hash=canonical_hash(payload))  # type: ignore[call-arg]


class _Sealed:
    artifact_type: ClassVar[str]
    record_hash: str

    def _payload(self) -> dict[str, object]:
        return {
            "artifact_type": self.artifact_type,
            **{
                item.name: _jsonable(getattr(self, item.name))
                for item in fields(self)
                if item.name != "record_hash" and not item.name.startswith("_")
            },
        }

    def as_dict(self, *, include_hash: bool = True) -> dict[str, object]:
        payload = self._payload()
        if include_hash:
            payload["record_hash"] = self.record_hash
        return payload

    def _check_hash(self) -> None:
        if _hash(self.record_hash, "record_hash") != canonical_hash(self._payload()):
            raise SkillOpsError("record_hash does not seal the record")


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """A reference, hash, and attestation; never artifact content."""

    kind: Literal["dataset", "evaluation", "trace", "evidence", "result"]
    ref: str
    content_hash: str
    source_kind: str
    provenance: Literal["LIVE", "FROZEN", "FIXTURE", "SYNTHETIC", "REPLAY"]
    classification: Literal["LIVE_ATTESTED", "NON_LIVE"]
    attestation_ref: str
    attested: bool = False
    run_id: str | None = None
    verified_readback: InitVar[ExternalReadback | None] = None
    _readback_token: object = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self, verified_readback: ExternalReadback | None) -> None:
        if self.kind not in _KINDS:
            raise SkillOpsError("artifact kind is unsupported")
        _ref(self.ref, "artifact.ref")
        _hash(self.content_hash, "artifact.content_hash")
        _text(self.source_kind, "artifact.source_kind", _SOURCE)
        if self.source_kind not in _SOURCES[self.kind]:
            raise SkillOpsError("artifact source is not allowed for its kind")
        if self.provenance not in _PROVENANCES:
            raise SkillOpsError("artifact provenance is unsupported")
        if self.classification not in _CLASSIFICATIONS:
            raise SkillOpsError("artifact classification is unsupported")
        if self.provenance == "LIVE" and self.classification != "LIVE_ATTESTED":
            raise SkillOpsError("LIVE artifacts require LIVE_ATTESTED classification")
        if self.provenance != "LIVE" and self.classification != "NON_LIVE":
            raise SkillOpsError("non-LIVE artifacts require NON_LIVE classification")
        _ref(self.attestation_ref, "artifact.attestation_ref")
        if self.provenance == "LIVE":
            if self.attested is not True:
                raise SkillOpsError("LIVE artifacts require an external readback")
            if verified_readback is None or not verified_readback.verified:
                raise SkillOpsError("LIVE artifacts require a verified external readback")
            if verified_readback.source != _ARTIFACT_READBACK_SOURCES[self.source_kind]:
                raise SkillOpsError("external readback source does not match artifact source")
            if verified_readback.raw_hash != self.content_hash:
                raise SkillOpsError("external readback hash does not match artifact")
            object.__setattr__(self, "_readback_token", verified_readback)
        elif self.attested is True or verified_readback is not None:
            raise SkillOpsError("non-LIVE artifacts cannot carry an attestation")
        if self.kind in _OBSERVATIONS and self.run_id is None:
            raise SkillOpsError("observations require a run_id")
        if self.run_id is not None:
            _ref(self.run_id, "artifact.run_id")

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "ref": self.ref,
            "content_hash": self.content_hash,
            "source_kind": self.source_kind,
            "provenance": self.provenance,
            "classification": self.classification,
            "attestation_ref": self.attestation_ref,
            "attested": self.attested,
            "run_id": self.run_id,
        }


def _refs(value: object, field: str, run_id: str | None = None) -> tuple[ArtifactRef, ...]:
    if not isinstance(value, tuple) or not value or not all(isinstance(item, ArtifactRef) for item in value):
        raise SkillOpsError(f"{field} must contain immutable references")
    if run_id is not None and any(item.run_id != run_id for item in value):
        raise SkillOpsError(f"{field} crosses the frozen run boundary")
    if any(item.kind not in _OBSERVATIONS for item in value):
        raise SkillOpsError(f"{field} contains a non-observation reference")
    return value


@dataclass(frozen=True, slots=True)
class Baseline(_Sealed):
    artifact_type: ClassVar[str] = "skillops.baseline/v1"
    baseline_id: str
    dataset_ref: ArtifactRef
    evaluation_ref: ArtifactRef
    run_id: str
    trace_refs: tuple[ArtifactRef, ...]
    evidence_refs: tuple[ArtifactRef, ...]
    record_hash: str

    @classmethod
    def freeze(cls, **values: object) -> "Baseline":
        return _make(cls, values)

    def __post_init__(self) -> None:
        _ref(self.baseline_id, "baseline_id")
        _artifact(self.dataset_ref, "baseline.dataset_ref", "dataset")
        _artifact(self.evaluation_ref, "baseline.evaluation_ref", "evaluation")
        _ref(self.run_id, "baseline.run_id")
        _refs(self.trace_refs, "trace_refs", self.run_id)
        _refs(self.evidence_refs, "evidence_refs", self.run_id)
        self._check_hash()


@dataclass(frozen=True, slots=True)
class Attribution(_Sealed):
    artifact_type: ClassVar[str] = "skillops.attribution/v1"
    attribution_id: str
    skill_name: str
    base_version: str
    baseline_ref: str
    baseline_hash: str
    baseline_run_id: str
    trace_refs: tuple[ArtifactRef, ...]
    evidence_refs: tuple[ArtifactRef, ...]
    record_hash: str

    @classmethod
    def create(
        cls,
        *,
        attribution_id: str,
        skill_name: str,
        base_version: str,
        baseline: Baseline,
        trace_refs: tuple[ArtifactRef, ...],
        evidence_refs: tuple[ArtifactRef, ...],
    ) -> "Attribution":
        return _make(cls, {
            "attribution_id": attribution_id,
            "skill_name": skill_name,
            "base_version": base_version,
            "baseline_ref": baseline.baseline_id,
            "baseline_hash": baseline.record_hash,
            "baseline_run_id": baseline.run_id,
            "trace_refs": trace_refs,
            "evidence_refs": evidence_refs,
        })

    def __post_init__(self) -> None:
        _ref(self.attribution_id, "attribution_id")
        _name(self.skill_name, "skill_name")
        _version(self.base_version, "base_version")
        _ref(self.baseline_ref, "baseline_ref")
        _hash(self.baseline_hash, "baseline_hash")
        _ref(self.baseline_run_id, "attribution.baseline_run_id")
        _refs(self.trace_refs, "attribution.trace_refs", self.baseline_run_id)
        _refs(self.evidence_refs, "attribution.evidence_refs", self.baseline_run_id)
        self._check_hash()


@dataclass(frozen=True, slots=True)
class SkillProposal(_Sealed):
    artifact_type: ClassVar[str] = "skillops.proposal/v1"
    proposal_id: str
    skill_name: str
    base_version: str
    candidate_version: str
    content_hash: str
    rollback_ref: str
    baseline_ref: str
    baseline_hash: str
    attribution_ref: str
    attribution_hash: str
    record_hash: str

    @classmethod
    def create(
        cls,
        *,
        proposal_id: str,
        skill_name: str,
        base_version: str,
        candidate_version: str,
        content_hash: str,
        rollback_ref: str,
        baseline: Baseline,
        attribution: Attribution,
    ) -> "SkillProposal":
        return _make(cls, {
            "proposal_id": proposal_id,
            "skill_name": skill_name,
            "base_version": base_version,
            "candidate_version": candidate_version,
            "content_hash": content_hash,
            "rollback_ref": rollback_ref,
            "baseline_ref": baseline.baseline_id,
            "baseline_hash": baseline.record_hash,
            "attribution_ref": attribution.attribution_id,
            "attribution_hash": attribution.record_hash,
        })

    def __post_init__(self) -> None:
        _ref(self.proposal_id, "proposal_id")
        _name(self.skill_name, "skill_name")
        _version(self.base_version, "base_version")
        _version(self.candidate_version, "candidate_version")
        if self.base_version == self.candidate_version:
            raise SkillOpsError("candidate_version must differ from base_version")
        _hash(self.content_hash, "proposal.content_hash")
        for field, value in (("rollback_ref", self.rollback_ref), ("baseline_ref", self.baseline_ref), ("attribution_ref", self.attribution_ref)):
            _ref(value, field)
        _hash(self.baseline_hash, "baseline_hash")
        _hash(self.attribution_hash, "attribution_hash")
        self._check_hash()


@dataclass(frozen=True, slots=True)
class HumanDecision(_Sealed):
    artifact_type: ClassVar[str] = "skillops.human-decision/v1"
    decision_id: str
    decision_revision: int
    proposal_ref: str
    proposal_hash: str
    actor_ref: str
    identity_ref: str
    attestation_ref: str
    actor_kind: Literal["external-human"]
    decision: Literal["APPROVE", "REJECT"]
    decided_at: str
    record_hash: str

    @classmethod
    def create(
        cls,
        *,
        decision_id: str,
        decision_revision: int,
        proposal: SkillProposal,
        actor_ref: str,
        identity_ref: str,
        attestation_ref: str,
        actor_kind: Literal["external-human"],
        decision: Literal["APPROVE", "REJECT"],
        decided_at: str,
    ) -> "HumanDecision":
        return _make(cls, {
            "decision_id": decision_id,
            "decision_revision": decision_revision,
            "proposal_ref": proposal.proposal_id,
            "proposal_hash": proposal.record_hash,
            "actor_ref": actor_ref,
            "identity_ref": identity_ref,
            "attestation_ref": attestation_ref,
            "actor_kind": actor_kind,
            "decision": decision,
            "decided_at": decided_at,
        })

    def __post_init__(self) -> None:
        _ref(self.decision_id, "decision_id")
        _revision(self.decision_revision, "decision_revision")
        _ref(self.proposal_ref, "proposal_ref")
        _hash(self.proposal_hash, "proposal_hash")
        _ref(self.actor_ref, "actor_ref")
        _ref(self.identity_ref, "identity_ref")
        _ref(self.attestation_ref, "attestation_ref")
        if self.actor_kind != "external-human":
            raise SkillOpsError("actor_kind must be external-human")
        if self.decision not in {"APPROVE", "REJECT"}:
            raise SkillOpsError("decision is unsupported")
        _ref(self.decided_at, "decided_at")
        self._check_hash()


@dataclass(frozen=True, slots=True)
class HumanDecisionVerification(_Sealed):
    """A sealed result returned by an external live-event readback verifier."""

    artifact_type: ClassVar[str] = "skillops.human-decision-verification/v1"
    verification_ref: str
    source: Literal["matrix-live-readback"]
    event_ref: str
    event_hash: str
    sender: str
    identity_ref: str
    decision_ref: str
    decision_hash: str
    proposal_ref: str
    proposal_hash: str
    decision_revision: int
    decision: Literal["APPROVE", "REJECT"]
    baseline_ref: str
    baseline_hash: str
    run_id: str
    verified_at: str
    record_hash: str
    verified_readback: InitVar[ExternalReadback | None] = None
    _readback_token: object = field(default=None, init=False, repr=False, compare=False)

    @classmethod
    def create(cls, **values: object) -> "HumanDecisionVerification":
        return _make(cls, values)

    def __post_init__(self, verified_readback: ExternalReadback | None) -> None:
        _ref(self.verification_ref, "verification_ref")
        if self.source != "matrix-live-readback":
            raise SkillOpsError("verification source must be matrix-live-readback")
        _ref(self.event_ref, "event_ref")
        _hash(self.event_hash, "event_hash")
        _ref(self.sender, "sender")
        _ref(self.identity_ref, "identity_ref")
        _ref(self.decision_ref, "decision_ref")
        _hash(self.decision_hash, "decision_hash")
        _ref(self.proposal_ref, "proposal_ref")
        _hash(self.proposal_hash, "proposal_hash")
        _revision(self.decision_revision, "decision_revision")
        if self.decision not in {"APPROVE", "REJECT"}:
            raise SkillOpsError("verified decision is unsupported")
        _ref(self.baseline_ref, "baseline_ref")
        _hash(self.baseline_hash, "baseline_hash")
        _ref(self.run_id, "run_id")
        _ref(self.verified_at, "verified_at")
        if verified_readback is None or not verified_readback.verified:
            raise SkillOpsError("verification requires an external readback token")
        if verified_readback.source != "matrix":
            raise SkillOpsError("verification readback source must be Matrix")
        if verified_readback.raw_hash != self.event_hash:
            raise SkillOpsError("verification readback hash does not match event_hash")
        object.__setattr__(self, "_readback_token", verified_readback)
        self._check_hash()


HumanDecisionVerifier = Callable[
    [HumanDecision, SkillProposal, Baseline], HumanDecisionVerification | bool
]


@dataclass(frozen=True, slots=True)
class _EvaluationObservation(_Sealed):
    artifact_type: ClassVar[str]
    observation_id: str
    proposal_ref: str
    proposal_hash: str
    candidate_version: str
    dataset_ref: ArtifactRef
    evaluation_ref: ArtifactRef
    result_ref: ArtifactRef
    trace_refs: tuple[ArtifactRef, ...]
    evidence_refs: tuple[ArtifactRef, ...]
    status: Literal["PASS", "FAIL", "BLOCKED", "NOT_AVAILABLE"]
    record_hash: str

    @classmethod
    def create(cls, **values: object) -> "_EvaluationObservation":
        return _make(cls, values)

    def __post_init__(self) -> None:
        _ref(self.observation_id, "observation_id")
        _ref(self.proposal_ref, "proposal_ref")
        _hash(self.proposal_hash, "proposal_hash")
        _version(self.candidate_version, "candidate_version")
        _artifact(self.dataset_ref, "evaluation.dataset_ref", "dataset")
        _artifact(self.evaluation_ref, "evaluation.evaluation_ref", "evaluation")
        _artifact(self.result_ref, "evaluation.result_ref", "result")
        _refs(self.trace_refs, "evaluation.trace_refs", self.result_ref.run_id)
        _refs(self.evidence_refs, "evaluation.evidence_refs", self.result_ref.run_id)
        if self.status not in _STATUSES:
            raise SkillOpsError("evaluation status is unsupported")
        if self.status in {"PASS", "FAIL"} and (
            self.result_ref.provenance != "LIVE"
            or self.result_ref.classification != "LIVE_ATTESTED"
            or not isinstance(self.result_ref._readback_token, ExternalReadback)
            or not self.result_ref._readback_token.verified
        ):
            raise SkillOpsError("completed evaluations require a verified external readback")
        self._check_hash()


@dataclass(frozen=True, slots=True)
class CanaryObservation(_EvaluationObservation):
    artifact_type: ClassVar[str] = "skillops.canary/v1"


@dataclass(frozen=True, slots=True)
class ReevaluationObservation(_EvaluationObservation):
    artifact_type: ClassVar[str] = "skillops.reevaluation/v1"


@dataclass(frozen=True, slots=True)
class SkillReceipt(_Sealed):
    artifact_type: ClassVar[str] = "skillops.receipt/v1"
    receipt_id: str
    proposal_ref: str
    proposal_hash: str
    action: Literal["PROMOTE", "ROLLBACK"]
    base_version: str
    candidate_version: str
    active_version: str
    rollback_ref: str
    baseline_hash: str
    canary_ref: str
    canary_hash: str
    reevaluation_ref: str
    reevaluation_hash: str
    human_decision_ref: str
    human_decision_hash: str
    human_verification_ref: str
    human_verification_hash: str
    record_hash: str

    @classmethod
    def create(cls, **values: object) -> "SkillReceipt":
        return _make(cls, values)

    def __post_init__(self) -> None:
        _ref(self.receipt_id, "receipt_id")
        _ref(self.proposal_ref, "proposal_ref")
        _hash(self.proposal_hash, "proposal_hash")
        if self.action not in {"PROMOTE", "ROLLBACK"}:
            raise SkillOpsError("receipt action is unsupported")
        for field, value in (("base_version", self.base_version), ("candidate_version", self.candidate_version), ("active_version", self.active_version)):
            _version(value, field)
        expected_active = self.candidate_version if self.action == "PROMOTE" else self.base_version
        if self.active_version != expected_active:
            raise SkillOpsError("receipt active_version does not match action")
        for field, value in (("rollback_ref", self.rollback_ref), ("canary_ref", self.canary_ref), ("reevaluation_ref", self.reevaluation_ref), ("human_decision_ref", self.human_decision_ref), ("human_verification_ref", self.human_verification_ref)):
            _ref(value, field)
        for field, value in (("baseline_hash", self.baseline_hash), ("canary_hash", self.canary_hash), ("reevaluation_hash", self.reevaluation_hash), ("human_decision_hash", self.human_decision_hash), ("human_verification_hash", self.human_verification_hash)):
            _hash(value, field)
        self._check_hash()


class SkillEvolution:
    """One append-only, generic lifecycle for any declarative Skill."""

    __slots__ = ("skill_name", "_state", "_baseline", "_attribution", "_proposal", "_human_decision", "_human_verification", "_canary", "_reevaluation", "_receipt")

    def __init__(self, skill_name: str) -> None:
        self.skill_name = _name(skill_name, "skill_name")
        self._state = "EMPTY"
        self._baseline = self._attribution = self._proposal = None
        self._human_decision = self._human_verification = None
        self._canary = self._reevaluation = self._receipt = None

    state = property(lambda self: self._state)
    baseline = property(lambda self: self._baseline)
    attribution = property(lambda self: self._attribution)
    proposal = property(lambda self: self._proposal)
    human_decision = property(lambda self: self._human_decision)
    human_verification = property(lambda self: self._human_verification)
    canary = property(lambda self: self._canary)
    reevaluation = property(lambda self: self._reevaluation)
    receipt = property(lambda self: self._receipt)

    def freeze_baseline(self, value: Baseline) -> None:
        if not isinstance(value, Baseline):
            raise SkillOpsStateError("baseline must be a Baseline record")
        self._expect("EMPTY")
        self._baseline, self._state = value, "BASELINE_FROZEN"

    def attribute(self, value: Attribution) -> None:
        if not isinstance(value, Attribution):
            raise SkillOpsStateError("attribution must be an Attribution record")
        self._expect("BASELINE_FROZEN")
        if self._baseline is None or (value.baseline_ref, value.baseline_hash) != (self._baseline.baseline_id, self._baseline.record_hash):
            raise SkillOpsStateError("attribution is not bound to this baseline")
        if value.skill_name != self.skill_name:
            raise SkillOpsStateError("attribution Skill does not match lifecycle")
        if value.baseline_run_id != self._baseline.run_id:
            raise SkillOpsStateError("attribution is bound to a different baseline run")
        self._attribution, self._state = value, "ATTRIBUTED"

    def propose(self, value: SkillProposal) -> None:
        if not isinstance(value, SkillProposal):
            raise SkillOpsStateError("proposal must be a SkillProposal record")
        self._expect("ATTRIBUTED")
        if self._baseline is None or self._attribution is None:
            raise SkillOpsStateError("baseline or attribution is missing")
        if value.skill_name != self.skill_name or (value.baseline_ref, value.baseline_hash) != (self._baseline.baseline_id, self._baseline.record_hash) or (value.attribution_ref, value.attribution_hash) != (self._attribution.attribution_id, self._attribution.record_hash) or value.base_version != self._attribution.base_version:
            raise SkillOpsStateError("proposal is not bound to the attributed baseline")
        self._proposal, self._state = value, "PROPOSED"

    def record_human_decision(
        self,
        value: HumanDecision,
        *,
        verifier: HumanDecisionVerifier | None,
    ) -> HumanDecisionVerification:
        if not isinstance(value, HumanDecision):
            raise SkillOpsStateError("decision must be a HumanDecision record")
        self._expect("PROPOSED")
        value._check_hash()
        if self._proposal is None or value.actor_kind != "external-human" or (value.proposal_ref, value.proposal_hash) != (self._proposal.proposal_id, self._proposal.record_hash):
            raise SkillOpsStateError("decision is not an external decision for this proposal")
        if verifier is None or not callable(verifier):
            raise SkillOpsStateError("external decision verifier is required")
        if self._baseline is None:
            raise SkillOpsStateError("baseline is missing for decision verification")
        try:
            verification = verifier(value, self._proposal, self._baseline)
        except Exception as exc:
            raise SkillOpsStateError("external decision verification failed") from exc
        if verification is False:
            raise SkillOpsStateError("external decision verification returned false")
        if not isinstance(verification, HumanDecisionVerification):
            raise SkillOpsStateError("external decision verification record is required")
        try:
            verification._check_hash()
        except SkillOpsError as exc:
            raise SkillOpsStateError("external decision verification is not sealed") from exc
        expected = {
            "source": "matrix-live-readback",
            "event_ref": value.attestation_ref,
            "sender": value.actor_ref,
            "identity_ref": value.identity_ref,
            "decision_ref": value.decision_id,
            "decision_hash": value.record_hash,
            "proposal_ref": self._proposal.proposal_id,
            "proposal_hash": self._proposal.record_hash,
            "decision_revision": value.decision_revision,
            "decision": value.decision,
            "baseline_ref": self._baseline.baseline_id,
            "baseline_hash": self._baseline.record_hash,
            "run_id": self._baseline.run_id,
        }
        if any(getattr(verification, key) != expected_value for key, expected_value in expected.items()):
            raise SkillOpsStateError("external decision verification does not match lifecycle")
        if not isinstance(verification._readback_token, ExternalReadback) or not verification._readback_token.verified:
            raise SkillOpsStateError("external decision verification lacks a readback token")
        self._human_decision = value
        self._human_verification = verification
        self._state = "HUMAN_APPROVED" if value.decision == "APPROVE" else "REJECTED"
        return verification

    def record_canary(self, value: CanaryObservation) -> None:
        if not isinstance(value, CanaryObservation):
            raise SkillOpsStateError("canary must be a CanaryObservation record")
        self._expect("HUMAN_APPROVED")
        self._check_evaluation(value)
        self._canary, self._state = value, "CANARY_RECORDED"

    def record_reevaluation(self, value: ReevaluationObservation) -> None:
        if not isinstance(value, ReevaluationObservation):
            raise SkillOpsStateError("reevaluation must be a ReevaluationObservation record")
        self._expect("CANARY_RECORDED")
        self._check_evaluation(value)
        if self._baseline is None or value.dataset_ref != self._baseline.dataset_ref or value.evaluation_ref != self._baseline.evaluation_ref:
            raise SkillOpsStateError("reevaluation must use the identical frozen dataset/evaluation")
        if self._canary is not None and (
            value.result_ref.ref == self._canary.result_ref.ref
            or value.result_ref.content_hash == self._canary.result_ref.content_hash
        ):
            raise SkillOpsStateError("reevaluation must use a distinct result reference and hash")
        self._reevaluation, self._state = value, "REEVALUATED"

    def close(self, value: SkillReceipt) -> None:
        if not isinstance(value, SkillReceipt):
            raise SkillOpsStateError("receipt must be a SkillReceipt record")
        self._expect("REEVALUATED")
        if not all((self._baseline, self._proposal, self._human_decision, self._human_verification, self._canary, self._reevaluation)):
            raise SkillOpsStateError("required evolution facts are missing")
        expected = {
            "proposal_ref": self._proposal.proposal_id,
            "proposal_hash": self._proposal.record_hash,
            "baseline_hash": self._baseline.record_hash,
            "canary_ref": self._canary.observation_id,
            "canary_hash": self._canary.record_hash,
            "reevaluation_ref": self._reevaluation.observation_id,
            "reevaluation_hash": self._reevaluation.record_hash,
            "human_decision_ref": self._human_decision.decision_id,
            "human_decision_hash": self._human_decision.record_hash,
            "human_verification_ref": self._human_verification.verification_ref,
            "human_verification_hash": self._human_verification.record_hash,
            "base_version": self._proposal.base_version,
            "candidate_version": self._proposal.candidate_version,
            "rollback_ref": self._proposal.rollback_ref,
        }
        if any(getattr(value, key) != child for key, child in expected.items()):
            raise SkillOpsStateError("receipt is not bound to this evolution")
        if self._canary.status == "FAIL" and value.action != "ROLLBACK":
            raise SkillOpsStateError("failed canary requires an explicit rollback receipt")
        if value.action == "PROMOTE" and not (self._canary.status == "PASS" and self._reevaluation.status == "PASS"):
            raise SkillOpsStateError("promotion is blocked unless canary and reevaluation both PASS")
        self._receipt, self._state = value, "PROMOTED" if value.action == "PROMOTE" else "ROLLED_BACK"

    def snapshot(self) -> dict[str, object]:
        return {
            "artifact_type": "skillops.state/v1",
            "skill_name": self.skill_name,
            "state": self._state,
            "baseline_ref": self._baseline.baseline_id if self._baseline else None,
            "baseline_hash": self._baseline.record_hash if self._baseline else None,
            "attribution_ref": self._attribution.attribution_id if self._attribution else None,
            "attribution_hash": self._attribution.record_hash if self._attribution else None,
            "proposal_ref": self._proposal.proposal_id if self._proposal else None,
            "proposal_hash": self._proposal.record_hash if self._proposal else None,
            "human_decision_ref": self._human_decision.decision_id if self._human_decision else None,
            "human_decision_hash": self._human_decision.record_hash if self._human_decision else None,
            "human_verification_ref": self._human_verification.verification_ref if self._human_verification else None,
            "human_verification_hash": self._human_verification.record_hash if self._human_verification else None,
            "canary_ref": self._canary.observation_id if self._canary else None,
            "reevaluation_ref": self._reevaluation.observation_id if self._reevaluation else None,
            "receipt_ref": self._receipt.receipt_id if self._receipt else None,
        }

    def _check_evaluation(self, value: _EvaluationObservation) -> None:
        if self._baseline is None or self._proposal is None:
            raise SkillOpsStateError("baseline or proposal is missing")
        if value.proposal_ref != self._proposal.proposal_id or value.proposal_hash != self._proposal.record_hash or value.candidate_version != self._proposal.candidate_version:
            raise SkillOpsStateError("evaluation is not bound to the proposal")
        if value.dataset_ref != self._baseline.dataset_ref or value.evaluation_ref != self._baseline.evaluation_ref:
            raise SkillOpsStateError("evaluation is not bound to the frozen dataset/evaluation")

    def _expect(self, expected: str) -> None:
        if self._state != expected:
            raise SkillOpsStateError(f"state {self._state} cannot accept this transition; expected {expected}")
