"""Provider-neutral configuration references for external worker adapters.

Only locations are accepted here.  This module never reads an environment
variable or a file, so endpoint, model, and credential values cannot enter a
checked-in contract accidentally.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
import re
from collections.abc import Mapping
from pathlib import Path
import stat
from typing import Any, Literal


class AdapterConfigError(ValueError):
    """Raised when a thin adapter configuration is unsafe or incomplete."""


_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_PROVIDER_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AdapterConfigError(f"{field} must be an object")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise AdapterConfigError(f"{field} must be a non-empty token")
    if any(ord(char) < 32 for char in value):
        raise AdapterConfigError(f"{field} contains a control character")
    return value


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AdapterConfigError(f"{field} must be a finite number")
    converted = float(value)
    if not math.isfinite(converted):
        raise AdapterConfigError(f"{field} must be a finite number")
    return converted


def _count(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AdapterConfigError(f"{field} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class ProtectedReference:
    """A protected environment or file location, never its resolved value."""

    source: Literal["env", "file"]
    location: str

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or self.source not in {"env", "file"}:
            raise AdapterConfigError("reference source must be env or file")
        if not isinstance(self.location, str) or not self.location:
            raise AdapterConfigError("reference location must be non-empty")
        if any(char.isspace() or ord(char) < 32 for char in self.location):
            raise AdapterConfigError("reference location contains whitespace or control data")
        if self.source == "env":
            if not _ENV_NAME.fullmatch(self.location):
                raise AdapterConfigError("environment reference must be an uppercase variable name")
        else:
            if not self.location.startswith("/"):
                raise AdapterConfigError("file reference must be an absolute protected path")
            if ".." in self.location.split("/"):
                raise AdapterConfigError("file reference cannot contain parent traversal")

    @classmethod
    def env(cls, name: str) -> "ProtectedReference":
        return cls("env", name)

    @classmethod
    def file(cls, path: str) -> "ProtectedReference":
        return cls("file", path)

    @classmethod
    def from_mapping(cls, value: Any, field: str = "reference") -> "ProtectedReference":
        raw = _mapping(value, field)
        source = raw.get("source")
        if source == "env":
            if set(raw) != {"source", "name"}:
                raise AdapterConfigError(f"{field} must contain source and name only")
            location = raw.get("name")
        elif source == "file":
            if set(raw) != {"source", "path"}:
                raise AdapterConfigError(f"{field} must contain source and path only")
            location = raw.get("path")
        else:
            raise AdapterConfigError(f"{field}.source must be env or file")
        return cls(source, _text(location, f"{field}.location"))

    def as_dict(self) -> dict[str, str]:
        key = "name" if self.source == "env" else "path"
        return {"source": self.source, key: self.location}


@dataclass(frozen=True)
class ReferencePreflight:
    """Names-only availability and permission result for one reference."""

    source: Literal["env", "file"]
    location: str
    present: bool
    usable: bool
    mode: int | None
    owner_uid: int | None
    owner_gid: int | None
    reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "location": self.location,
            "present": self.present,
            "usable": self.usable,
            "mode": self.mode,
            "owner_uid": self.owner_uid,
            "owner_gid": self.owner_gid,
            "reason": self.reason,
        }


def preflight_reference(reference: ProtectedReference) -> ReferencePreflight:
    """Check only reference binding and file metadata; never resolve a value."""

    if not isinstance(reference, ProtectedReference):
        raise AdapterConfigError("reference preflight requires ProtectedReference")
    if reference.source == "env":
        present = reference.location in os.environ
        return ReferencePreflight(
            source="env",
            location=reference.location,
            present=present,
            usable=present,
            mode=None,
            owner_uid=None,
            owner_gid=None,
            reason=None if present else "environment_name_not_bound",
        )

    try:
        metadata = Path(reference.location).stat()
    except OSError:
        return ReferencePreflight(
            source="file",
            location=reference.location,
            present=False,
            usable=False,
            mode=None,
            owner_uid=None,
            owner_gid=None,
            reason="file_missing_or_unreadable",
        )

    mode = stat.S_IMODE(metadata.st_mode)
    if not stat.S_ISREG(metadata.st_mode):
        usable = False
        reason = "file_not_regular"
    elif mode & 0o077:
        usable = False
        reason = "file_not_owner_only"
    else:
        usable = True
        reason = None
    return ReferencePreflight(
        source="file",
        location=reference.location,
        present=True,
        usable=usable,
        mode=mode,
        owner_uid=metadata.st_uid,
        owner_gid=metadata.st_gid,
        reason=reason,
    )


@dataclass(frozen=True)
class ExecutionLimits:
    """Approved observation limits; this class does not enforce process control."""

    timeout_seconds: float
    max_model_decisions: int
    max_tool_calls: int
    max_cost_units: float

    def __post_init__(self) -> None:
        timeout = _number(self.timeout_seconds, "timeout_seconds")
        if timeout <= 0 or timeout > 86_400:
            raise AdapterConfigError("timeout_seconds must be greater than zero and at most one day")
        if _count(self.max_model_decisions, "max_model_decisions") < 0:
            raise AdapterConfigError("max_model_decisions must be non-negative")
        if _count(self.max_tool_calls, "max_tool_calls") < 0:
            raise AdapterConfigError("max_tool_calls must be non-negative")
        cost = _number(self.max_cost_units, "max_cost_units")
        if cost < 0:
            raise AdapterConfigError("max_cost_units must be non-negative")

    @classmethod
    def from_mapping(cls, value: Any, field: str = "limits") -> "ExecutionLimits":
        raw = _mapping(value, field)
        required = {
            "timeout_seconds",
            "max_model_decisions",
            "max_tool_calls",
            "max_cost_units",
        }
        if set(raw) != required:
            raise AdapterConfigError(f"{field} must contain the four approved limit fields only")
        return cls(
            timeout_seconds=_number(raw["timeout_seconds"], f"{field}.timeout_seconds"),
            max_model_decisions=_count(raw["max_model_decisions"], f"{field}.max_model_decisions"),
            max_tool_calls=_count(raw["max_tool_calls"], f"{field}.max_tool_calls"),
            max_cost_units=_number(raw["max_cost_units"], f"{field}.max_cost_units"),
        )

    def as_dict(self) -> dict[str, int | float]:
        return {
            "timeout_seconds": self.timeout_seconds,
            "max_model_decisions": self.max_model_decisions,
            "max_tool_calls": self.max_tool_calls,
            "max_cost_units": self.max_cost_units,
        }


@dataclass(frozen=True)
class ProviderRoute:
    """One provider-neutral route whose values are all protected references."""

    provider: str
    endpoint_ref: ProtectedReference
    model_ref: ProtectedReference
    credential_ref: ProtectedReference
    wire_api: Literal["chat", "responses"] = "chat"

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not _PROVIDER_ID.fullmatch(self.provider):
            raise AdapterConfigError("provider must be a lowercase provider identifier")
        if not isinstance(self.endpoint_ref, ProtectedReference):
            raise AdapterConfigError("endpoint_ref must be a protected reference")
        if not isinstance(self.model_ref, ProtectedReference):
            raise AdapterConfigError("model_ref must be a protected reference")
        if not isinstance(self.credential_ref, ProtectedReference):
            raise AdapterConfigError("credential_ref must be a protected reference")
        if not isinstance(self.wire_api, str) or self.wire_api not in {"chat", "responses"}:
            raise AdapterConfigError("wire_api must be chat or responses")

    @classmethod
    def from_mapping(cls, value: Any, field: str = "route") -> "ProviderRoute":
        raw = _mapping(value, field)
        required = {"provider", "endpoint", "model", "credential", "wire_api"}
        if set(raw) != required:
            raise AdapterConfigError(f"{field} must contain provider, endpoint, model, credential, wire_api")
        provider = _text(raw["provider"], f"{field}.provider")
        return cls(
            provider=provider,
            endpoint_ref=ProtectedReference.from_mapping(raw["endpoint"], f"{field}.endpoint"),
            model_ref=ProtectedReference.from_mapping(raw["model"], f"{field}.model"),
            credential_ref=ProtectedReference.from_mapping(raw["credential"], f"{field}.credential"),
            wire_api=raw["wire_api"],
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "endpoint": self.endpoint_ref.as_dict(),
            "model": self.model_ref.as_dict(),
            "credential": self.credential_ref.as_dict(),
            "wire_api": self.wire_api,
        }


@dataclass(frozen=True)
class AdapterConfig:
    """Configuration shared by the DSH and external CLI result boundaries."""

    adapter_kind: Literal["dsh", "codex-cli"]
    route: ProviderRoute
    limits: ExecutionLimits

    def __post_init__(self) -> None:
        if not isinstance(self.adapter_kind, str) or self.adapter_kind not in {"dsh", "codex-cli"}:
            raise AdapterConfigError("adapter_kind must be dsh or codex-cli")
        if not isinstance(self.route, ProviderRoute):
            raise AdapterConfigError("route must be a ProviderRoute")
        if not isinstance(self.limits, ExecutionLimits):
            raise AdapterConfigError("limits must be ExecutionLimits")

    @classmethod
    def from_mapping(cls, value: Any) -> "AdapterConfig":
        raw = _mapping(value, "adapter_config")
        if set(raw) != {"adapter_kind", "route", "limits"}:
            raise AdapterConfigError("adapter_config has unsupported or missing fields")
        return cls(
            adapter_kind=raw["adapter_kind"],
            route=ProviderRoute.from_mapping(raw["route"]),
            limits=ExecutionLimits.from_mapping(raw["limits"]),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "adapter_kind": self.adapter_kind,
            "route": self.route.as_dict(),
            "limits": self.limits.as_dict(),
        }
