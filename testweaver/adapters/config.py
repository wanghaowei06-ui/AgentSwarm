"""Provider-neutral configuration references for external worker adapters.

Only locations are accepted in the checked-in contract.  Runtime binding is
temporary and reads existing protected AgentTeams values only in the Worker.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import math
import os
import re
from collections.abc import Mapping
from pathlib import Path
import stat
from typing import Any, Literal
from urllib.parse import urlsplit

import yaml


class AdapterConfigError(ValueError):
    """Raised when a thin adapter configuration is unsafe or incomplete."""


_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_PROVIDER_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_RUNTIME_CONFIG_MAX_BYTES = 64 * 1024
_PROTECTED_FILE_MAX_BYTES = 64 * 1024
PROTECTED_PROVIDER_DIRECTORY = Path("/var/run/secrets/agentteams/testweaver-provider")
_ADAPTER_FILE_ROOTS = tuple(
    Path(item)
    for item in ("/etc/agentteams", "/run/secrets/agentteams", "/var/run/secrets/agentteams")
)
PROTECTED_REFERENCE_ENV_NAMES = frozenset(
    "HOME CODEX_HOME CODEX_ENDPOINT CODEX_MODEL CODEX_WORKER_MODEL "
    "AGENTTEAMS_AI_GATEWAY_URL AGENTTEAMS_WORKER_GATEWAY_KEY AGENTTEAMS_WORKER_MODEL "
    "DEEPSEEK_API_KEY DEEPSEEK_BASE_URL DEEPSEEK_MODEL "
    "DASHSCOPE_API_KEY DASHSCOPE_BASE_URL DASHSCOPE_MODEL "
    "TESTWEAVER_BAILIAN_CREDENTIAL TESTWEAVER_BAILIAN_ENDPOINT TESTWEAVER_BAILIAN_MODEL "
    "TESTWEAVER_CODEX_CREDENTIAL TESTWEAVER_CODEX_ENDPOINT TESTWEAVER_CODEX_MODEL "
    "TESTWEAVER_DSH_CREDENTIAL TESTWEAVER_DSH_ENDPOINT TESTWEAVER_DSH_MODEL"
    .split()
)


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


def preflight_reference(
    reference: ProtectedReference,
    *,
    dedicated_provider: bool = False,
    allowed_roots: tuple[Path, ...] | None = None,
    field: str | None = None,
) -> ReferencePreflight:
    """Check binding and metadata without returning or persisting a value."""

    if not isinstance(reference, ProtectedReference):
        raise AdapterConfigError("reference preflight requires ProtectedReference")
    if reference.source == "env":
        present = reference.location in os.environ
        usable = present
        reason = None if present else "environment_name_not_bound"
        if present and field in {"endpoint", "model", "credential"}:
            try:
                _validate_reference_value(os.environ.get(reference.location), field)
            except AdapterConfigError:
                usable = False
                reason = "environment_value_invalid"
        return ReferencePreflight(
            source="env",
            location=reference.location,
            present=present,
            usable=usable,
            mode=None,
            owner_uid=None,
            owner_gid=None,
            reason=reason,
        )

    path = Path(reference.location)
    if dedicated_provider:
        return _preflight_dedicated_reference(reference, path)
    if allowed_roots is not None and not _inside(path.resolve(), allowed_roots):
        return ReferencePreflight(
            source="file",
            location=reference.location,
            present=False,
            usable=False,
            mode=None,
            owner_uid=None,
            owner_gid=None,
            reason="file_outside_protected_roots",
        )
    try:
        metadata = path.stat()
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


def preflight_adapter_reference(
    reference: ProtectedReference,
    *,
    dedicated_provider: bool = False,
    field: str | None = None,
) -> ReferencePreflight:
    """Apply the adapter file scope before an execution-time resolution."""

    roots = None if dedicated_provider else _ADAPTER_FILE_ROOTS
    return preflight_reference(
        reference,
        dedicated_provider=dedicated_provider,
        allowed_roots=roots,
        field=field,
    )


def validate_credential(value: Any, field: str = "credential") -> str:
    """Validate a credential before it can enter an external child environment."""

    if not isinstance(value, str) or len(value) < 8:
        raise AdapterConfigError(f"{field} protected value is too short")
    if any(char.isspace() or ord(char) < 32 for char in value):
        raise AdapterConfigError(f"{field} protected value has invalid format")
    return value


def _validate_endpoint(value: Any, field: str = "endpoint") -> str:
    if not isinstance(value, str):
        raise AdapterConfigError(f"{field} protected value has invalid format")
    normalized = value.strip()
    if not normalized:
        raise AdapterConfigError(f"{field} protected value is empty")
    try:
        endpoint = urlsplit(normalized)
    except ValueError as exc:
        raise AdapterConfigError(f"{field} protected value has invalid format") from exc
    if (
        endpoint.scheme not in {"http", "https"}
        or not endpoint.hostname
        or endpoint.username
        or endpoint.password
        or endpoint.query
        or endpoint.fragment
        or any(char.isspace() or ord(char) < 32 for char in normalized)
    ):
        raise AdapterConfigError(f"{field} protected value has invalid format")
    return normalized


def _validate_model(value: Any, field: str = "model") -> str:
    if not isinstance(value, str):
        raise AdapterConfigError(f"{field} protected value has invalid format")
    normalized = value.strip()
    if not normalized:
        raise AdapterConfigError(f"{field} protected value is empty")
    if len(normalized) > 512 or any(
        char.isspace() or ord(char) < 32 for char in normalized
    ):
        raise AdapterConfigError(f"{field} protected value has invalid format")
    return normalized


def _validate_reference_value(value: Any, field: str) -> str:
    if field == "endpoint":
        return _validate_endpoint(value, field)
    if field == "model":
        return _validate_model(value, field)
    if field == "credential":
        return validate_credential(value, field)
    raise AdapterConfigError(f"unsupported protected reference field: {field}")


@contextmanager
def _open_protected_file(reference: ProtectedReference, field: str):
    if not isinstance(reference, ProtectedReference) or reference.source != "file":
        raise AdapterConfigError(f"{field} must be a file reference")
    path = Path(reference.location)
    if path.parent != PROTECTED_PROVIDER_DIRECTORY or path.name in {"", ".", ".."}:
        raise AdapterConfigError(f"{field} file reference is outside the dedicated provider directory")
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = (
        os.O_RDONLY
        | os.O_NONBLOCK
        | os.O_CLOEXEC
        | os.O_NOFOLLOW
    )
    directory_fd = -1
    file_fd = -1
    try:
        directory_fd = os.open(PROTECTED_PROVIDER_DIRECTORY, directory_flags)
        directory_metadata = os.fstat(directory_fd)
        if (
            not stat.S_ISDIR(directory_metadata.st_mode)
            or directory_metadata.st_uid != 0
            or stat.S_IMODE(directory_metadata.st_mode) != 0o700
        ):
            raise AdapterConfigError("dedicated provider directory failed safety checks")
        file_fd = os.open(path.name, file_flags, dir_fd=directory_fd)
        metadata = os.fstat(file_fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) not in {0o400, 0o600}
            or not 0 < metadata.st_size <= _PROTECTED_FILE_MAX_BYTES
        ):
            raise AdapterConfigError(f"{field} protected file failed safety checks")
        yield file_fd, metadata
    except OSError as exc:
        raise AdapterConfigError(f"{field} protected file is unavailable") from exc
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def _preflight_dedicated_reference(
    reference: ProtectedReference,
    path: Path,
) -> ReferencePreflight:
    if path.parent != PROTECTED_PROVIDER_DIRECTORY:
        return ReferencePreflight(
            source="file",
            location=reference.location,
            present=False,
            usable=False,
            mode=None,
            owner_uid=None,
            owner_gid=None,
            reason="file_outside_dedicated_provider_directory",
        )
    try:
        with _open_protected_file(reference, "protected_file") as (_, metadata):
            return ReferencePreflight(
                source="file",
                location=reference.location,
                present=True,
                usable=True,
                mode=stat.S_IMODE(metadata.st_mode),
                owner_uid=metadata.st_uid,
                owner_gid=metadata.st_gid,
                reason=None,
            )
    except AdapterConfigError:
        return ReferencePreflight(
            source="file",
            location=reference.location,
            present=False,
            usable=False,
            mode=None,
            owner_uid=None,
            owner_gid=None,
            reason="file_failed_dedicated_provider_checks",
        )


def read_protected_file(
    reference: ProtectedReference,
    field: str = "protected_file",
) -> str:
    """Read one dedicated owner-only provider reference without exposing its value."""

    try:
        with _open_protected_file(reference, field) as (file_fd, metadata):
            raw = os.read(file_fd, _PROTECTED_FILE_MAX_BYTES + 1)
    except OSError as exc:
        raise AdapterConfigError(f"{field} protected file is unavailable") from exc
    if (
        len(raw) != metadata.st_size
        or b"\x00" in raw
    ):
        raise AdapterConfigError(f"{field} protected file failed safety checks")
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AdapterConfigError(f"{field} protected file is not valid text") from exc
    if field in {"endpoint", "model", "credential"}:
        return _validate_reference_value(decoded, field)
    value = decoded.strip()
    if not value:
        raise AdapterConfigError(f"{field} protected file is empty")
    return value


def preflight_execution_reference(
    reference: ProtectedReference,
    *,
    field: str,
    dedicated_provider: bool = False,
) -> ReferencePreflight:
    """Apply the same reference checks used immediately before execution."""

    if reference.source == "env" and reference.location not in PROTECTED_REFERENCE_ENV_NAMES:
        return ReferencePreflight(
            source="env",
            location=reference.location,
            present=reference.location in os.environ,
            usable=False,
            mode=None,
            owner_uid=None,
            owner_gid=None,
            reason="environment_name_not_allowlisted",
        )
    result = preflight_adapter_reference(
        reference,
        dedicated_provider=dedicated_provider,
        field=field if dedicated_provider else None,
    )
    if not result.usable or not dedicated_provider or reference.source != "file":
        return result
    try:
        read_protected_file(reference, field)
    except AdapterConfigError:
        return ReferencePreflight(
            source=result.source,
            location=result.location,
            present=result.present,
            usable=False,
            mode=result.mode,
            owner_uid=result.owner_uid,
            owner_gid=result.owner_gid,
            reason="file_value_invalid",
        )
    return result


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


def resolve_dsh_file_environment(
    route: ProviderRoute,
    values: dict[str, str],
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Resolve DSH file references in memory and add only its child aliases."""

    file_values: dict[str, str] = {}
    resolved: dict[str, str] = {}
    for field, reference in (
        ("endpoint", route.endpoint_ref),
        ("model", route.model_ref),
        ("credential", route.credential_ref),
    ):
        if reference.source == "file":
            value = read_protected_file(reference, field)
            file_values[field] = value
        else:
            value = os.environ.get(reference.location)
            value = _validate_reference_value(value, field)
            values[reference.location] = value
        resolved[field] = value
    endpoint = resolved["endpoint"]
    credential = resolved["credential"]
    values.update({"DEEPSEEK_BASE_URL": endpoint, "DEEPSEEK_API_KEY": credential})
    return values, tuple((*values.values(), *file_values.values()))


def _runtime_route_fields(path: str, roots: tuple[Path, ...]) -> tuple[bool, str, str]:
    location = path.strip()
    if not location:
        return False, "", ""
    candidate = Path(location)
    if not candidate.is_absolute() or candidate.is_symlink() or not candidate.is_file():
        return True, "", ""
    resolved = candidate.resolve()
    if not any(_inside(resolved, (root,)) for root in roots):
        return True, "", ""
    try:
        if candidate.stat().st_size > _RUNTIME_CONFIG_MAX_BYTES:
            return True, "", ""
        raw = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        return True, "", ""
    desired = raw.get("desired") if isinstance(raw, dict) else None
    model = desired.get("model") if isinstance(desired, dict) else None
    if not isinstance(model, dict):
        return True, "", ""
    endpoint = str(
        model.get("gatewayUrl")
        or model.get("gateway_url")
        or model.get("baseUrl")
        or model.get("base_url")
        or model.get("endpoint")
        or ""
    ).strip()
    model_name = str(model.get("model") or model.get("name") or "").strip()
    parsed = urlsplit(endpoint)
    if (
        endpoint
        and (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment)
    ):
        endpoint = ""
    if any(char.isspace() or ord(char) < 32 for char in model_name) or len(model_name) > 512:
        model_name = ""
    return True, endpoint, model_name


def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or root in path.parents for root in roots)


@contextmanager
def bind_bailian_route(config: AdapterConfig, roots: tuple[Path, ...]):
    """Project missing Bailian refs from native Worker route state briefly."""

    updates: dict[str, str] = {}
    if isinstance(config, AdapterConfig) and config.adapter_kind == "dsh" and config.route.provider == "aliyun-bailian":
        present, endpoint, model = _runtime_route_fields(os.environ.get("TEAMHARNESS_RUNTIME_CONFIG", ""), roots)
        if not present:
            endpoint = os.environ.get("AGENTTEAMS_AI_GATEWAY_URL", "").strip()
        model = model or os.environ.get("AGENTTEAMS_WORKER_MODEL", "").strip()
        candidates = {
            "TESTWEAVER_BAILIAN_ENDPOINT": endpoint,
            "TESTWEAVER_BAILIAN_MODEL": model,
            "TESTWEAVER_BAILIAN_CREDENTIAL": os.environ.get("AGENTTEAMS_WORKER_GATEWAY_KEY", ""),
        }
        for reference in (config.route.endpoint_ref, config.route.model_ref, config.route.credential_ref):
            if reference.source == "env" and reference.location in candidates and not os.environ.get(reference.location):
                if candidates[reference.location]:
                    updates[reference.location] = candidates[reference.location]
    previous = {name: os.environ.get(name) for name in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
