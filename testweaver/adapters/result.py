"""Provider-neutral result, usage, budget, and evidence contracts.

The functions in this module normalize an already-produced result mapping.
They do not launch a process, call a provider, read a credential, or mutate
native AgentTeams state.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from .config import (
    AdapterConfig,
    AdapterConfigError,
    ExecutionLimits,
    ProtectedReference,
    ProviderRoute,
)


class ResultContractError(ValueError):
    """Raised when an external result cannot be safely normalized."""


_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
def canonical_hash(value: Any) -> str:
    """Hash a JSON-compatible value using the source contract's canonical form."""

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ResultContractError(f"value is not canonical JSON: {exc}") from exc
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _opaque(value: Any, field: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise ResultContractError(f"{field} must be a non-empty opaque reference")
    if any(char.isspace() or ord(char) < 32 for char in value):
        raise ResultContractError(f"{field} must not contain whitespace or control data")
    return value


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResultContractError(f"{field} must be a non-negative integer")
    return value


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResultContractError(f"{field} must be a finite number")
    converted = float(value)
    if not math.isfinite(converted) or converted < 0:
        raise ResultContractError(f"{field} must be a non-negative finite number")
    return converted


@dataclass(frozen=True)
class NativeReferences:
    """Opaque native IDs used only for correlation, with no copied state."""

    project_id: str
    task_id: str
    room_id: str
    read_only: ClassVar[bool] = True

    def __post_init__(self) -> None:
        _opaque(self.project_id, "native_refs.project_id")
        _opaque(self.task_id, "native_refs.task_id")
        _opaque(self.room_id, "native_refs.room_id")

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "task_id": self.task_id,
            "room_id": self.room_id,
            "read_only": True,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "NativeReferences":
        if not isinstance(value, Mapping) or set(value) != {"project_id", "task_id", "room_id", "read_only"}:
            raise ResultContractError("native_refs must contain only read-only project/task/room references")
        if value["read_only"] is not True:
            raise ResultContractError("native_refs.read_only must be true")
        return cls(
            project_id=_opaque(value["project_id"], "native_refs.project_id"),
            task_id=_opaque(value["task_id"], "native_refs.task_id"),
            room_id=_opaque(value["room_id"], "native_refs.room_id"),
        )


@dataclass(frozen=True)
class EvidenceReference:
    """A pointer to evidence carried by native filesync/message transport."""

    id: str
    kind: str
    artifact_ref: str
    content_hash: str

    def __post_init__(self) -> None:
        _opaque(self.id, "evidence_ref.id", 200)
        if not isinstance(self.kind, str) or self.kind not in {"file", "message", "artifact"}:
            raise ResultContractError("evidence_ref.kind is not supported")
        _opaque(self.artifact_ref, "evidence_ref.artifact_ref", 2000)
        if not isinstance(self.content_hash, str) or not _HASH.fullmatch(self.content_hash):
            raise ResultContractError("evidence_ref.content_hash must be a sha256 digest")

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "kind": self.kind,
            "artifact_ref": self.artifact_ref,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_mapping(cls, value: Any, field: str = "evidence_ref") -> "EvidenceReference":
        if not isinstance(value, Mapping) or set(value) != {"id", "kind", "artifact_ref", "content_hash"}:
            raise ResultContractError(f"{field} has an invalid shape")
        try:
            return cls(
                id=value["id"],
                kind=value["kind"],
                artifact_ref=value["artifact_ref"],
                content_hash=value["content_hash"],
            )
        except ResultContractError as exc:
            raise ResultContractError(f"{field}: {exc}") from exc


@dataclass(frozen=True)
class Provenance:
    """Source identity for the result, without retaining provider content."""

    source: str
    source_revision: str
    method: str

    def __post_init__(self) -> None:
        _opaque(self.source, "provenance.source", 200)
        _opaque(self.source_revision, "provenance.source_revision", 200)
        if not isinstance(self.method, str) or not 1 <= len(self.method) <= 2000:
            raise ResultContractError("provenance.method must be non-empty")
        if any(ord(char) < 32 for char in self.method):
            raise ResultContractError("provenance.method contains a control character")

    def as_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "source_revision": self.source_revision,
            "method": self.method,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "Provenance":
        if not isinstance(value, Mapping) or set(value) != {"source", "source_revision", "method"}:
            raise ResultContractError("provenance has an invalid shape")
        return cls(value["source"], value["source_revision"], value["method"])


@dataclass(frozen=True)
class Usage:
    """Unified usage counters; None means the upstream did not expose a value."""

    model_decisions: int | None = None
    tool_calls: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_units: float | None = None
    observed: bool = False

    def __post_init__(self) -> None:
        for field in ("model_decisions", "tool_calls", "input_tokens", "output_tokens"):
            value = getattr(self, field)
            if value is not None:
                _integer(value, f"usage.{field}")
        if self.cost_units is not None:
            _number(self.cost_units, "usage.cost_units")
        if not isinstance(self.observed, bool):
            raise ResultContractError("usage.observed must be boolean")

    @classmethod
    def from_mapping(cls, value: Any) -> "Usage":
        if not isinstance(value, Mapping):
            raise ResultContractError("usage must be an object")
        allowed = {
            "model_decisions",
            "modelDecisions",
            "tool_calls",
            "toolCalls",
            "input_tokens",
            "inputTokens",
            "output_tokens",
            "outputTokens",
            "cost_units",
            "costUnits",
            "observed",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ResultContractError(f"usage has unsupported fields: {sorted(unknown)}")

        def pick(snake: str, camel: str) -> Any:
            if snake in value and camel in value:
                raise ResultContractError(f"usage contains both {snake} and {camel}")
            return value.get(snake, value.get(camel))

        fields = {
            "model_decisions": pick("model_decisions", "modelDecisions"),
            "tool_calls": pick("tool_calls", "toolCalls"),
            "input_tokens": pick("input_tokens", "inputTokens"),
            "output_tokens": pick("output_tokens", "outputTokens"),
            "cost_units": pick("cost_units", "costUnits"),
        }
        derived_observed = any(
            value.get(key) is not None
            for key in (
                "model_decisions",
                "modelDecisions",
                "tool_calls",
                "toolCalls",
                "input_tokens",
                "inputTokens",
                "output_tokens",
                "outputTokens",
                "cost_units",
                "costUnits",
            )
        )
        if "observed" in value and value["observed"] is not derived_observed:
            raise ResultContractError("usage.observed does not match the supplied counters")
        observed = derived_observed
        return cls(**fields, observed=observed)

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_decisions": self.model_decisions,
            "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_units": self.cost_units,
            "observed": self.observed,
        }


_STATUS = {
    "COMPLETED": "completed",
    "SUCCESS": "completed",
    "SUCCEEDED": "completed",
    "FAILED": "failed",
    "ERROR": "failed",
    "TIMEOUT": "timed_out",
    "TIMED_OUT": "timed_out",
    "CANCELLED": "terminated",
    "CANCELED": "terminated",
    "BUDGET_EXHAUSTED": "terminated",
    "TERMINATED": "terminated",
}
_TERMINATION = {
    "NONE": "none",
    "TIMEOUT": "timeout",
    "TIMED_OUT": "timeout",
    "CANCELLED": "cancelled",
    "CANCELED": "cancelled",
    "BUDGET_EXCEEDED": "budget_exceeded",
    "BUDGET_EXHAUSTED": "budget_exceeded",
    "PROVIDER_ERROR": "provider_error",
    "ERROR": "provider_error",
    "PROTOCOL_ERROR": "protocol_error",
    "UNKNOWN": "unknown",
}


def _status(value: Any) -> str:
    if not isinstance(value, str):
        raise ResultContractError("result.status must be a string")
    normalized = _STATUS.get(value.strip().upper())
    if normalized is None:
        raise ResultContractError("result.status is unsupported")
    return normalized


def _termination(value: Any) -> str:
    if not isinstance(value, str):
        raise ResultContractError("result.termination must be a string")
    normalized = _TERMINATION.get(value.strip().upper())
    if normalized is None:
        raise ResultContractError("result.termination is unsupported")
    return normalized


def budget_exceeded(usage: Usage, limits: ExecutionLimits) -> str | None:
    """Return the first exceeded approved counter, without changing execution."""

    if usage.model_decisions is not None and usage.model_decisions > limits.max_model_decisions:
        return "model_decision_budget_exceeded"
    if usage.tool_calls is not None and usage.tool_calls > limits.max_tool_calls:
        return "tool_call_budget_exceeded"
    if usage.cost_units is not None and usage.cost_units > limits.max_cost_units:
        return "cost_budget_exceeded"
    return None


@dataclass(frozen=True)
class NormalizedResult:
    """Sealed result projection shared by DSH and the external CLI boundary."""

    schema_version: ClassVar[str] = "testweaver.worker-result/v1"
    version: ClassVar[int] = 1
    revision: ClassVar[int] = 1

    adapter_kind: str
    route: ProviderRoute
    native_refs: NativeReferences
    status: str
    termination: str
    result_ref: str
    evidence_refs: tuple[EvidenceReference, ...]
    provenance: Provenance
    usage: Usage
    limits: ExecutionLimits
    elapsed_seconds: float | None
    content_hash: str

    @property
    def provider(self) -> str:
        """Provider identity copied from the protected route declaration."""

        return self.route.provider

    @property
    def model_ref(self) -> ProtectedReference:
        """Location-only model reference; the model value is never resolved here."""

        return self.route.model_ref

    @property
    def latency_seconds(self) -> float | None:
        """Common latency name for the external Worker's elapsed duration."""

        return self.elapsed_seconds

    def __post_init__(self) -> None:
        if not isinstance(self.adapter_kind, str) or self.adapter_kind not in {"dsh", "codex-cli"}:
            raise ResultContractError("adapter_kind is unsupported")
        if not isinstance(self.route, ProviderRoute):
            raise ResultContractError("route must be a ProviderRoute")
        if not isinstance(self.native_refs, NativeReferences):
            raise ResultContractError("native_refs must be NativeReferences")
        if not isinstance(self.status, str) or self.status not in {
            "completed",
            "failed",
            "timed_out",
            "terminated",
        }:
            raise ResultContractError("status is unsupported")
        if not isinstance(self.termination, str) or self.termination not in {
            "none",
            "timeout",
            "cancelled",
            "budget_exceeded",
            "provider_error",
            "protocol_error",
            "unknown",
        }:
            raise ResultContractError("termination is unsupported")
        _opaque(self.result_ref, "result_ref", 2000)
        if not self.evidence_refs:
            raise ResultContractError("at least one evidence reference is required")
        for evidence in self.evidence_refs:
            if not isinstance(evidence, EvidenceReference):
                raise ResultContractError("evidence_refs must contain EvidenceReference values")
        if not isinstance(self.provenance, Provenance):
            raise ResultContractError("provenance must be Provenance")
        if not isinstance(self.usage, Usage):
            raise ResultContractError("usage must be Usage")
        if not isinstance(self.limits, ExecutionLimits):
            raise ResultContractError("limits must be ExecutionLimits")
        if self.elapsed_seconds is not None:
            _number(self.elapsed_seconds, "elapsed_seconds")
        if self.status == "completed" and self.termination != "none":
            raise ResultContractError("completed result must have no termination reason")
        if self.status == "timed_out" and self.termination != "timeout":
            raise ResultContractError("timed_out result must have timeout termination")
        if self.status == "terminated" and self.termination not in {"cancelled", "budget_exceeded", "unknown"}:
            raise ResultContractError("terminated result has an incompatible termination reason")
        if self.status == "failed" and self.termination == "none":
            raise ResultContractError("failed result requires a termination reason")
        expected = canonical_hash(self._payload())
        if self.content_hash != expected:
            raise ResultContractError("content_hash mismatch")

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "version": self.version,
            "revision": self.revision,
            "adapter_kind": self.adapter_kind,
            "route": self.route.as_dict(),
            "native_refs": self.native_refs.as_dict(),
            "status": self.status,
            "termination": self.termination,
            "result_ref": self.result_ref,
            "evidence_refs": [item.as_dict() for item in self.evidence_refs],
            "provenance": self.provenance.as_dict(),
            "usage": self.usage.as_dict(),
            "limits": self.limits.as_dict(),
            "elapsed_seconds": self.elapsed_seconds,
        }

    def as_dict(self) -> dict[str, Any]:
        payload = self._payload()
        payload["content_hash"] = self.content_hash
        return payload

    @classmethod
    def seal(
        cls,
        *,
        adapter_kind: str,
        route: ProviderRoute,
        native_refs: NativeReferences,
        status: str,
        termination: str,
        result_ref: str,
        evidence_refs: Sequence[EvidenceReference],
        provenance: Provenance,
        usage: Usage,
        limits: ExecutionLimits,
        elapsed_seconds: float | None,
    ) -> "NormalizedResult":
        payload = {
            "schema_version": cls.schema_version,
            "version": cls.version,
            "revision": cls.revision,
            "adapter_kind": adapter_kind,
            "route": route.as_dict(),
            "native_refs": native_refs.as_dict(),
            "status": status,
            "termination": termination,
            "result_ref": result_ref,
            "evidence_refs": [item.as_dict() for item in evidence_refs],
            "provenance": provenance.as_dict(),
            "usage": usage.as_dict(),
            "limits": limits.as_dict(),
            "elapsed_seconds": elapsed_seconds,
        }
        return cls(
            adapter_kind=adapter_kind,
            route=route,
            native_refs=native_refs,
            status=status,
            termination=termination,
            result_ref=result_ref,
            evidence_refs=tuple(evidence_refs),
            provenance=provenance,
            usage=usage,
            limits=limits,
            elapsed_seconds=elapsed_seconds,
            content_hash=canonical_hash(payload),
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "NormalizedResult":
        if not isinstance(value, Mapping):
            raise ResultContractError("normalized result must be an object")
        required = {
            "schema_version",
            "version",
            "revision",
            "adapter_kind",
            "route",
            "native_refs",
            "status",
            "termination",
            "result_ref",
            "evidence_refs",
            "provenance",
            "usage",
            "limits",
            "elapsed_seconds",
            "content_hash",
        }
        if set(value) != required:
            raise ResultContractError("normalized result has unsupported or missing fields")
        if value["schema_version"] != cls.schema_version or value["version"] != cls.version or value["revision"] != cls.revision:
            raise ResultContractError("normalized result version is unsupported")
        evidence_values = value["evidence_refs"]
        if not isinstance(evidence_values, list):
            raise ResultContractError("evidence_refs must be an array")
        if not isinstance(value["content_hash"], str) or not _HASH.fullmatch(value["content_hash"]):
            raise ResultContractError("content_hash must be a sha256 digest")
        try:
            return cls(
                adapter_kind=value["adapter_kind"],
                route=ProviderRoute.from_mapping(value["route"]),
                native_refs=NativeReferences.from_mapping(value["native_refs"]),
                status=value["status"],
                termination=value["termination"],
                result_ref=value["result_ref"],
                evidence_refs=tuple(
                    EvidenceReference.from_mapping(item, f"evidence_refs[{index}]")
                    for index, item in enumerate(evidence_values)
                ),
                provenance=Provenance.from_mapping(value["provenance"]),
                usage=Usage.from_mapping(value["usage"]),
                limits=ExecutionLimits.from_mapping(value["limits"]),
                elapsed_seconds=value["elapsed_seconds"],
                content_hash=value["content_hash"],
            )
        except (AdapterConfigError, ResultContractError) as exc:
            if isinstance(exc, ResultContractError):
                raise
            raise ResultContractError(str(exc)) from exc


def normalize_result(
    raw: Mapping[str, Any],
    *,
    config: AdapterConfig,
    native_refs: NativeReferences,
    provenance: Provenance,
) -> NormalizedResult:
    """Normalize a provider result without retaining raw model/tool content."""

    if not isinstance(raw, Mapping):
        raise ResultContractError("raw result must be an object")
    allowed = {"status", "termination", "result_ref", "evidence_refs", "usage", "elapsed_seconds"}
    if set(raw) - allowed:
        raise ResultContractError("raw result contains fields outside the thin result boundary")
    required = {"status", "result_ref", "evidence_refs", "usage"}
    if not required.issubset(raw):
        raise ResultContractError("raw result is missing status, result_ref, evidence_refs, or usage")
    evidence_values = raw["evidence_refs"]
    if not isinstance(evidence_values, list):
        raise ResultContractError("raw evidence_refs must be an array")
    evidence_refs = tuple(
        EvidenceReference.from_mapping(item, f"evidence_refs[{index}]")
        for index, item in enumerate(evidence_values)
    )
    usage = Usage.from_mapping(raw["usage"])
    status = _status(raw["status"])
    termination = _termination(raw["termination"]) if "termination" in raw else None

    if termination is None:
        if status == "completed":
            termination = "none"
        elif status == "timed_out":
            termination = "timeout"
        elif status == "terminated":
            raise ResultContractError("terminated result requires termination")
        else:
            termination = "provider_error"
    if termination == "timeout":
        status = "timed_out"
    elif termination in {"cancelled", "budget_exceeded", "unknown"} and status == "completed":
        raise ResultContractError("completed result cannot carry a termination reason")
    elif termination in {"cancelled", "budget_exceeded", "unknown"}:
        status = "terminated"
    elif termination in {"provider_error", "protocol_error"} and status == "completed":
        raise ResultContractError("completed result cannot carry an error termination")
    exceeded = budget_exceeded(usage, config.limits)
    if status == "completed" and exceeded is not None:
        status = "terminated"
        termination = "budget_exceeded"

    elapsed = raw.get("elapsed_seconds")
    if elapsed is not None:
        elapsed = _number(elapsed, "elapsed_seconds")
    return NormalizedResult.seal(
        adapter_kind=config.adapter_kind,
        route=config.route,
        native_refs=native_refs,
        status=status,
        termination=termination,
        result_ref=_opaque(raw["result_ref"], "result_ref", 2000),
        evidence_refs=evidence_refs,
        provenance=provenance,
        usage=usage,
        limits=config.limits,
        elapsed_seconds=elapsed,
    )


# Public name used by native Worker callers; the normalized projection remains
# the single implementation and schema.
WorkerResult = NormalizedResult
