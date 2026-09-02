"""Minimal read-only correlation for real AgentLoop and OTel query results.

This module deliberately does not load credentials, start services, emit traces,
create AgentLoop resources, or control AgentTeams runs.  A deployment may bind a
private header provider from its own secret-aware runtime, but this module only
keeps the protected reference and never puts headers or response bodies in a
receipt.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen


QueryStatus = Literal["VERIFIED", "NOT_VERIFIED", "BLOCKED"]
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")
_VARIABLE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_HERO_TUPLE_FIELDS = ("campaign_id", "run_id", "pg_revision", "content_hash", "trace_id")
_CORRELATION_FIELDS = ("campaign_id", "run_id", "pg_revision", "content_hash")
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class ObservabilityContractError(ValueError):
    """Raised for an invalid local correlation or endpoint contract."""


def _opaque(value: str, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ObservabilityContractError(f"{field} must be a non-empty opaque reference")
    if any(ord(character) < 32 or character.isspace() for character in value):
        raise ObservabilityContractError(f"{field} contains whitespace or control data")
    return value


@dataclass(frozen=True)
class Correlation:
    """Stable, non-secret identity for one real TestWeaver run."""

    campaign_id: str
    run_id: str
    pg_revision: str
    content_hash: str

    def __post_init__(self) -> None:
        for field in ("campaign_id", "run_id", "pg_revision"):
            value = _opaque(getattr(self, field), field)
            if not _IDENTIFIER.fullmatch(value):
                raise ObservabilityContractError(f"{field} has invalid characters")
        if not isinstance(self.content_hash, str) or not _HASH.fullmatch(self.content_hash):
            raise ObservabilityContractError("content_hash must be a sha256 digest")

    def as_dict(self) -> dict[str, str]:
        return {
            "campaign_id": self.campaign_id,
            "run_id": self.run_id,
            "pg_revision": self.pg_revision,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class ConfigReferenceStatus:
    """Names-only metadata for a protected config reference."""

    path: str
    exists: bool
    usable: bool
    mode: int | None
    owner_uid: int | None
    owner_gid: int | None
    variable_names: tuple[str, ...]
    reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "exists": self.exists,
            "usable": self.usable,
            "mode": self.mode,
            "owner_uid": self.owner_uid,
            "owner_gid": self.owner_gid,
            "variable_names": list(self.variable_names),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ProtectedConfigRef:
    """A location-only reference; ``inspect`` never opens the file."""

    path: Path
    variable_names: tuple[str, ...] = ()
    owner_only: bool = True

    def __post_init__(self) -> None:
        if not self.path.is_absolute():
            raise ObservabilityContractError("protected config path must be absolute")
        if not isinstance(self.owner_only, bool):
            raise ObservabilityContractError("owner_only must be boolean")
        for name in self.variable_names:
            if not _VARIABLE.fullmatch(name):
                raise ObservabilityContractError(f"invalid protected variable name: {name}")

    def inspect(self) -> ConfigReferenceStatus:
        """Return only path, permission and variable-name metadata."""

        path_text = str(self.path)
        try:
            metadata = self.path.stat()
        except OSError:
            return ConfigReferenceStatus(
                path=path_text,
                exists=False,
                usable=False,
                mode=None,
                owner_uid=None,
                owner_gid=None,
                variable_names=self.variable_names,
                reason="missing_or_unreadable",
            )

        mode = stat.S_IMODE(metadata.st_mode)
        if not stat.S_ISREG(metadata.st_mode):
            reason = "not_a_regular_file"
            usable = False
        elif self.owner_only and mode & 0o077:
            reason = "not_owner_only"
            usable = False
        else:
            reason = None
            usable = True
        return ConfigReferenceStatus(
            path=path_text,
            exists=True,
            usable=usable,
            mode=mode,
            owner_uid=metadata.st_uid,
            owner_gid=metadata.st_gid,
            variable_names=self.variable_names,
            reason=reason,
        )


@dataclass(frozen=True)
class EndpointReference:
    """An endpoint and optional backend-specific read-only query path."""

    name: str
    base_url: str
    query_path: str | None = None
    auth_required: bool = True

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.name):
            raise ObservabilityContractError("endpoint name is invalid")
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ObservabilityContractError("endpoint must be an HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ObservabilityContractError("endpoint must not contain inline credentials")
        if parsed.query or parsed.fragment:
            raise ObservabilityContractError("endpoint must not contain query or fragment data")
        if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise ObservabilityContractError("non-loopback endpoint must use HTTPS")
        if self.query_path is not None:
            _validate_query_path(self.query_path)
        if not isinstance(self.auth_required, bool):
            raise ObservabilityContractError("auth_required must be boolean")
        if not self.auth_required and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise ObservabilityContractError("external endpoints require protected auth")

    @property
    def safe_url(self) -> str:
        parsed = urlsplit(self.base_url)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


@dataclass(frozen=True)
class HttpResponse:
    """Small transport result; callers must not expose ``body`` in receipts."""

    status_code: int
    body: bytes


@dataclass(frozen=True)
class QueryPreflight:
    schema_version: str
    status: QueryStatus
    backend: str
    endpoint: str
    read_only: bool
    credential: ConfigReferenceStatus | None
    reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "backend": self.backend,
            "endpoint": self.endpoint,
            "read_only": self.read_only,
            "credential": self.credential.as_dict() if self.credential is not None else None,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class QueryReceipt:
    """Sanitized result of one read-only GET query."""

    schema_version: str
    status: QueryStatus
    backend: str
    operation: str
    endpoint: str
    path: str
    http_method: str
    read_only: bool
    correlation: Correlation
    response_status: int | None
    response_hash: str | None
    matched_fields: tuple[str, ...]
    reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "backend": self.backend,
            "operation": self.operation,
            "endpoint": self.endpoint,
            "path": self.path,
            "http_method": self.http_method,
            "read_only": self.read_only,
            "correlation": self.correlation.as_dict(),
            "response_status": self.response_status,
            "response_hash": self.response_hash,
            "matched_fields": list(self.matched_fields),
            "reason": self.reason,
        }


Transport = Callable[[str, dict[str, str], float], HttpResponse]
HeaderProvider = Callable[[], Mapping[str, str]]


class ReadOnlyQueryClient:
    """Query an already-existing endpoint without any mutating operation."""

    def __init__(
        self,
        *,
        endpoint: EndpointReference,
        credential_ref: ProtectedConfigRef | None = None,
        header_provider: HeaderProvider | None = None,
        transport: Transport | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 60:
            raise ObservabilityContractError("timeout_seconds must be between 0 and 60")
        self.endpoint = endpoint
        self.credential_ref = credential_ref
        self.header_provider = header_provider
        self.transport = transport or _urllib_get
        self.timeout_seconds = timeout_seconds

    def preflight(self, *, backend: str) -> QueryPreflight:
        credential_status = self.credential_ref.inspect() if self.credential_ref is not None else None
        reason = self._auth_block_reason(credential_status)
        return QueryPreflight(
            schema_version="testweaver.observability-query-preflight/v1",
            status="BLOCKED" if reason else "NOT_VERIFIED",
            backend=_opaque(backend, "backend"),
            endpoint=self.endpoint.safe_url,
            read_only=True,
            credential=credential_status,
            reason=reason or "endpoint reachability requires a bounded GET query",
        )

    def query_json(
        self,
        *,
        operation: str,
        path: str,
        correlation: Correlation,
        query: Mapping[str, str] | None = None,
        backend: str = "agentloop",
        additional_anchors: Mapping[str, str] | None = None,
    ) -> QueryReceipt:
        operation = _opaque(operation, "operation")
        backend = _opaque(backend, "backend")
        try:
            _validate_query_path(path)
        except ObservabilityContractError as error:
            return self._blocked(operation, backend, path, correlation, str(error))

        credential_status = self.credential_ref.inspect() if self.credential_ref is not None else None
        auth_reason = self._auth_block_reason(credential_status)
        if auth_reason:
            return self._blocked(operation, backend, path, correlation, auth_reason)

        try:
            url = self._url(path, query)
        except ObservabilityContractError as error:
            return self._blocked(operation, backend, path, correlation, str(error))

        headers: dict[str, str] = {"Accept": "application/json"}
        if self.header_provider is not None:
            try:
                supplied = self.header_provider()
                if not isinstance(supplied, Mapping):
                    raise TypeError
                for key, value in supplied.items():
                    if not isinstance(key, str) or not key or any(
                        ord(character) < 32 for character in key
                    ):
                        raise ValueError
                    if not isinstance(value, str) or any(
                        ord(character) < 32 for character in value
                    ):
                        raise ValueError
                    headers[key] = value
            except Exception:
                return self._blocked(operation, backend, path, correlation, "auth_provider_failed")

        try:
            response = self.transport(url, headers, self.timeout_seconds)
        except (OSError, TimeoutError, URLError, HTTPError):
            return self._blocked(operation, backend, path, correlation, "query_transport_failed")
        if not isinstance(response, HttpResponse):
            return self._blocked(operation, backend, path, correlation, "invalid_transport_response")
        if not 200 <= response.status_code < 300:
            return self._blocked(
                operation,
                backend,
                path,
                correlation,
                "query_returned_non_success",
                response_status=response.status_code,
            )
        if not isinstance(response.body, bytes) or len(response.body) > _MAX_RESPONSE_BYTES:
            return self._blocked(
                operation,
                backend,
                path,
                correlation,
                "query_response_too_large",
                response_status=response.status_code,
            )
        response_hash = "sha256:" + hashlib.sha256(response.body).hexdigest()
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._blocked(
                operation,
                backend,
                path,
                correlation,
                "query_response_not_json",
                response_status=response.status_code,
                response_hash=response_hash,
            )

        anchors: dict[str, str] = correlation.as_dict()
        if additional_anchors:
            for name, value in additional_anchors.items():
                anchors[_opaque(name, "additional_anchor_name")] = _opaque(
                    value, "additional_anchor_value"
                )
        matched = tuple(name for name, value in anchors.items() if _contains_exact(payload, value))
        status: QueryStatus = "VERIFIED" if len(matched) == len(anchors) else "NOT_VERIFIED"
        return QueryReceipt(
            schema_version="testweaver.observability-query/v1",
            status=status,
            backend=backend,
            operation=operation,
            endpoint=self.endpoint.safe_url,
            path=path,
            http_method="GET",
            read_only=True,
            correlation=correlation,
            response_status=response.status_code,
            response_hash=response_hash,
            matched_fields=matched,
            reason=None if status == "VERIFIED" else "correlation_anchors_not_all_observed",
        )

    def query_otel_trace(
        self,
        *,
        trace_id: str,
        correlation: Correlation,
        query_path: str | None = None,
    ) -> QueryReceipt:
        path = query_path or self.endpoint.query_path
        if path is None:
            return self._blocked(
                "otel_trace",
                "otel",
                "/",
                correlation,
                "otel_query_path_not_configured",
            )
        if not _TRACE_ID.fullmatch(trace_id):
            return self._blocked("otel_trace", "otel", path, correlation, "invalid_trace_id")
        if path.rstrip("/").endswith("/v1/traces"):
            return self._blocked(
                "otel_trace",
                "otel",
                path,
                correlation,
                "otel_export_path_is_not_query_path",
            )
        return self.query_json(
            operation="otel_trace",
            backend="otel",
            path=path,
            query={"traceId": trace_id},
            correlation=correlation,
            additional_anchors={"trace_id": trace_id},
        )

    def query_agentloop_evaluation_task(
        self,
        *,
        agent_space: str,
        task_id: str,
        correlation: Correlation,
    ) -> QueryReceipt:
        path = f"/api/v1/evaluation-task/{quote(_opaque(agent_space, 'agent_space'), safe='')}/{quote(_opaque(task_id, 'task_id'), safe='')}"
        return self.query_json(
            operation="evaluation_task",
            backend="agentloop",
            path=path,
            correlation=correlation,
        )

    def query_agentloop_evaluation_runs(
        self,
        *,
        agent_space: str,
        task_id: str,
        correlation: Correlation,
    ) -> QueryReceipt:
        path = f"/api/v1/evaluation-task/{quote(_opaque(agent_space, 'agent_space'), safe='')}/{quote(_opaque(task_id, 'task_id'), safe='')}/runs"
        return self.query_json(
            operation="evaluation_runs",
            backend="agentloop",
            path=path,
            correlation=correlation,
        )

    def query_agentloop_dataset(
        self,
        *,
        agent_space: str,
        dataset_id: str,
        correlation: Correlation,
    ) -> QueryReceipt:
        path = f"/agentspace/{quote(_opaque(agent_space, 'agent_space'), safe='')}/dataset/{quote(_opaque(dataset_id, 'dataset_id'), safe='')}"
        return self.query_json(
            operation="golden_dataset",
            backend="agentloop",
            path=path,
            correlation=correlation,
        )

    def _auth_block_reason(self, status: ConfigReferenceStatus | None) -> str | None:
        if not self.endpoint.auth_required:
            return None
        if status is None:
            return "protected_credential_reference_not_bound"
        if not status.usable:
            return "protected_credential_reference_unusable"
        if self.header_provider is None:
            return "credential_header_provider_not_bound"
        return None

    def _url(self, path: str, query: Mapping[str, str] | None) -> str:
        url = f"{self.endpoint.safe_url}{path}"
        if not query:
            return url
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in query.items()):
            raise ObservabilityContractError("query parameters must be strings")
        encoded = "&".join(
            f"{quote(key, safe='')}={quote(value, safe='')}"
            for key, value in sorted(query.items())
        )
        return f"{url}?{encoded}"

    def _blocked(
        self,
        operation: str,
        backend: str,
        path: str,
        correlation: Correlation,
        reason: str,
        *,
        response_status: int | None = None,
        response_hash: str | None = None,
    ) -> QueryReceipt:
        return QueryReceipt(
            schema_version="testweaver.observability-query/v1",
            status="BLOCKED",
            backend=backend,
            operation=operation,
            endpoint=self.endpoint.safe_url,
            path=path,
            http_method="GET",
            read_only=True,
            correlation=correlation,
            response_status=response_status,
            response_hash=response_hash,
            matched_fields=(),
            reason=reason,
        )


def verify_hero_correlation(
    otel_export: Mapping[str, object], agentloop_query: Mapping[str, object]
) -> dict[str, object]:
    """Compare two frozen, non-synthetic observations without any I/O."""

    observations = (otel_export, agentloop_query)
    expected_sources = ("otel_export", "agentloop_query")
    normalized: list[dict[str, object]] = []
    for observation, expected_source in zip(observations, expected_sources, strict=True):
        if not isinstance(observation, Mapping):
            return {"status": "BLOCKED", "reason": "observation_not_object"}
        missing = [
            field
            for field in (*_HERO_TUPLE_FIELDS, "source", "provider", "model", "usage", "latency_ms", "synthetic")
            if field not in observation
        ]
        if missing:
            return {"status": "NOT_AVAILABLE", "reason": "missing_observation_fields"}
        if observation["source"] != expected_source:
            return {"status": "BLOCKED", "reason": "observation_source_mismatch"}
        if observation["synthetic"] is not False:
            return {"status": "BLOCKED", "reason": "synthetic_observation"}
        try:
            for field in ("campaign_id", "run_id", "pg_revision"):
                value = observation[field]
                if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
                    raise ValueError(field)
            if not isinstance(observation["content_hash"], str) or not _HASH.fullmatch(observation["content_hash"]):
                raise ValueError("content_hash")
            if not isinstance(observation["trace_id"], str) or not _TRACE_ID.fullmatch(observation["trace_id"]):
                raise ValueError("trace_id")
            if not isinstance(observation["provider"], str) or not observation["provider"]:
                raise ValueError("provider")
            if not isinstance(observation["model"], str) or not observation["model"]:
                raise ValueError("model")
            if not isinstance(observation["usage"], Mapping) or not observation["usage"]:
                raise ValueError("usage")
            latency = observation["latency_ms"]
            if isinstance(latency, bool) or not isinstance(latency, (int, float)) or latency < 0:
                raise ValueError("latency_ms")
        except ValueError:
            return {"status": "BLOCKED", "reason": "invalid_observation"}
        normalized.append(dict(observation))

    tuple_values = tuple(normalized[0][field] for field in _HERO_TUPLE_FIELDS)
    if tuple(tuple(observation[field] for field in _HERO_TUPLE_FIELDS) for observation in normalized) != (tuple_values, tuple_values):
        return {"status": "BLOCKED", "reason": "authority_tuple_mismatch"}
    return {
        "status": "VERIFIED",
        "authority_tuple": dict(zip(_HERO_TUPLE_FIELDS, tuple_values, strict=True)),
        "sources": list(expected_sources),
    }


def _validate_query_path(path: str) -> None:
    if not isinstance(path, str) or not path.startswith("/"):
        raise ObservabilityContractError("query path must be absolute")
    if "?" in path or "#" in path or any(ord(character) < 32 for character in path):
        raise ObservabilityContractError("query path must not contain query or control data")


def _contains_exact(value: object, expected: str) -> bool:
    if isinstance(value, str):
        return value == expected
    if isinstance(value, Mapping):
        return any(_contains_exact(child, expected) for child in value.values())
    if isinstance(value, list):
        return any(_contains_exact(child, expected) for child in value)
    return False


def _urllib_get(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            return HttpResponse(status_code=response.status, body=response.read(_MAX_RESPONSE_BYTES + 1))
    except HTTPError as error:
        return HttpResponse(status_code=error.code, body=b"")
    except URLError:
        raise
