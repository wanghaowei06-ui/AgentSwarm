"""Thin binding between a native Worker assignment and an external backend.

This module is deliberately not an orchestration or process runner.  The native
Leader supplies the assignment, and the native Worker lifecycle supplies the
already-produced result.  The binding only carries opaque references in and
normalizes the result back out.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .codex_cli import CodexCliLaunch, build_codex_cli_launch
from .config import (
    AdapterConfig,
    ExecutionLimits,
    ProtectedReference,
    ProviderRoute,
)
from .result import NativeReferences, NormalizedResult, Provenance
from .result import normalize_result as normalize_worker_result


DSH_PROVIDER_PROFILES = frozenset({"deepseek", "aliyun-bailian"})


class NativeWorkerAdapterError(ValueError):
    """Raised when a native assignment cannot be bound safely."""


def _reference(value: ProtectedReference | Mapping[str, Any], field: str) -> ProtectedReference:
    if isinstance(value, ProtectedReference):
        return value
    try:
        return ProtectedReference.from_mapping(value, field)
    except (TypeError, AttributeError) as exc:
        raise NativeWorkerAdapterError(f"{field} must be a protected reference") from exc


def _opaque(value: Any, field: str, maximum: int = 2000) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise NativeWorkerAdapterError(f"{field} must be an opaque native reference")
    if any(char.isspace() or ord(char) < 32 for char in value):
        raise NativeWorkerAdapterError(f"{field} must not contain whitespace or control data")
    return value


@dataclass(frozen=True)
class DshProviderProfile:
    """A provider-neutral DSH route made only from protected references."""

    provider: str
    route: ProviderRoute

    def __post_init__(self) -> None:
        if self.provider != self.route.provider:
            raise NativeWorkerAdapterError("DSH profile provider does not match its route")

    @classmethod
    def from_provider(
        cls,
        provider: str,
        *,
        endpoint_ref: ProtectedReference | Mapping[str, Any],
        model_ref: ProtectedReference | Mapping[str, Any],
        credential_ref: ProtectedReference | Mapping[str, Any],
        wire_api: Literal["chat", "responses"] = "chat",
    ) -> "DshProviderProfile":
        route = ProviderRoute(
            provider=provider,
            endpoint_ref=_reference(endpoint_ref, "endpoint_ref"),
            model_ref=_reference(model_ref, "model_ref"),
            credential_ref=_reference(credential_ref, "credential_ref"),
            wire_api=wire_api,
        )
        return cls(provider=provider, route=route)

    @classmethod
    def deepseek(
        cls,
        *,
        endpoint_ref: ProtectedReference | Mapping[str, Any],
        model_ref: ProtectedReference | Mapping[str, Any],
        credential_ref: ProtectedReference | Mapping[str, Any],
        wire_api: Literal["chat", "responses"] = "chat",
    ) -> "DshProviderProfile":
        return cls.from_provider(
            "deepseek",
            endpoint_ref=endpoint_ref,
            model_ref=model_ref,
            credential_ref=credential_ref,
            wire_api=wire_api,
        )

    @classmethod
    def aliyun_bailian(
        cls,
        *,
        endpoint_ref: ProtectedReference | Mapping[str, Any],
        model_ref: ProtectedReference | Mapping[str, Any],
        credential_ref: ProtectedReference | Mapping[str, Any],
        wire_api: Literal["chat", "responses"] = "chat",
    ) -> "DshProviderProfile":
        return cls.from_provider(
            "aliyun-bailian",
            endpoint_ref=endpoint_ref,
            model_ref=model_ref,
            credential_ref=credential_ref,
            wire_api=wire_api,
        )

    def as_config(self, limits: ExecutionLimits | Mapping[str, Any]) -> AdapterConfig:
        approved_limits = (
            limits if isinstance(limits, ExecutionLimits) else ExecutionLimits.from_mapping(limits)
        )
        return AdapterConfig(adapter_kind="dsh", route=self.route, limits=approved_limits)

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile": self.provider,
            "route": self.route.as_dict(),
        }


@dataclass(frozen=True)
class NativeWorkerAssignment:
    """Opaque native refs received after the Leader has assigned a Task."""

    project_id: str
    task_id: str
    room_id: str
    worker_id: str
    leader_id: str
    task_ref: str
    read_only: bool = True

    def __post_init__(self) -> None:
        for field in ("project_id", "task_id", "room_id", "worker_id", "leader_id", "task_ref"):
            _opaque(getattr(self, field), f"assignment.{field}")
        if self.read_only is not True:
            raise NativeWorkerAdapterError("native assignment must be read-only")

    @property
    def native_refs(self) -> NativeReferences:
        return NativeReferences(
            project_id=self.project_id,
            task_id=self.task_id,
            room_id=self.room_id,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "task_id": self.task_id,
            "room_id": self.room_id,
            "worker_id": self.worker_id,
            "leader_id": self.leader_id,
            "task_ref": self.task_ref,
            "read_only": True,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "NativeWorkerAssignment":
        if not isinstance(value, Mapping):
            raise NativeWorkerAdapterError("native assignment must be an object")
        required = {"project_id", "task_id", "room_id", "worker_id", "leader_id", "task_ref", "read_only"}
        if set(value) != required:
            raise NativeWorkerAdapterError("native assignment has unsupported or missing fields")
        return cls(
            project_id=value["project_id"],
            task_id=value["task_id"],
            room_id=value["room_id"],
            worker_id=value["worker_id"],
            leader_id=value["leader_id"],
            task_ref=value["task_ref"],
            read_only=value["read_only"],
        )


@dataclass(frozen=True)
class NativeWorkerInvocation:
    """A prepared call boundary; it performs no dispatch or process control."""

    assignment: NativeWorkerAssignment
    config: AdapterConfig
    provenance: Provenance
    launch: CodexCliLaunch | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.assignment, NativeWorkerAssignment):
            raise NativeWorkerAdapterError("assignment must be NativeWorkerAssignment")
        if not isinstance(self.config, AdapterConfig):
            raise NativeWorkerAdapterError("config must be AdapterConfig")
        if not isinstance(self.provenance, Provenance):
            raise NativeWorkerAdapterError("provenance must be Provenance")
        if self.config.adapter_kind == "codex-cli" and self.launch is None:
            object.__setattr__(self, "launch", build_codex_cli_launch())
        if self.config.adapter_kind == "dsh" and self.launch is not None:
            raise NativeWorkerAdapterError("DSH invocation cannot carry a Codex launch")

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "adapter_kind": self.config.adapter_kind,
            "native_assignment": self.assignment.as_dict(),
            "provider": self.config.route.provider,
            "model_ref": self.config.route.model_ref.as_dict(),
            "config": self.config.as_dict(),
            "provenance": self.provenance.as_dict(),
            "lifecycle_owner": "agentteams-native-worker",
            "dispatch_owner": "native-leader",
            "result_owner": "native-leader",
        }
        if self.launch is not None:
            payload["launch"] = self.launch.as_dict()
        return payload

    def normalize_result(
        self,
        raw_result: Mapping[str, Any],
        *,
        latency_seconds: float | None = None,
    ) -> NormalizedResult:
        """Normalize a result already returned by the external Worker backend."""

        if not isinstance(raw_result, Mapping):
            raise NativeWorkerAdapterError("worker result must be an object")
        if latency_seconds is not None:
            if "elapsed_seconds" in raw_result and raw_result["elapsed_seconds"] != latency_seconds:
                raise NativeWorkerAdapterError("latency has two different reported values")
            raw_result = {**raw_result, "elapsed_seconds": latency_seconds}
        return normalize_worker_result(
            raw_result,
            config=self.config,
            native_refs=self.assignment.native_refs,
            provenance=self.provenance,
        )


def prepare_native_worker_invocation(
    *,
    assignment: NativeWorkerAssignment,
    config: AdapterConfig,
    provenance: Provenance,
    launch: CodexCliLaunch | None = None,
) -> NativeWorkerInvocation:
    """Bind a native Leader assignment without creating or dispatching work."""

    return NativeWorkerInvocation(
        assignment=assignment,
        config=config,
        provenance=provenance,
        launch=launch,
    )
