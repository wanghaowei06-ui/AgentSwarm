"""Small, real OTLP/HTTP GenAI span bridge.

The bridge emits one standard OTLP span and never creates an AgentTeams or
AgentLoop object.  It keeps authentication in a caller-owned callback and
returns only hashes and status metadata, so a failed export remains a
verifiable probe rather than a LIVE claim.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import time_ns
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .readonly_query import Correlation


_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_OPAQUE = re.compile(r"^[^\s\x00-\x1f\x7f]{1,512}$")
_MAX_REQUEST_BYTES = 4 * 1024 * 1024


class OtlpContractError(ValueError):
    """Raised when an OTLP bridge input is unsafe or incomplete."""


def _opaque(value: object, field: str) -> str:
    if not isinstance(value, str) or not _OPAQUE.fullmatch(value):
        raise OtlpContractError(f"{field} must be a non-empty opaque reference")
    return value


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise OtlpContractError(f"{field} must be a sha256 digest")
    return value


@dataclass(frozen=True)
class EvidenceRef:
    """A non-secret evidence locator bound to one content hash."""

    ref: str
    content_hash: str

    def __post_init__(self) -> None:
        _opaque(self.ref, "evidence_ref.ref")
        _hash(self.content_hash, "evidence_ref.content_hash")


@dataclass(frozen=True)
class GenAIContext:
    """Identifiers and non-content facts attached to a real agent turn."""

    correlation: Correlation
    agent_id: str
    task_id: str
    skill: str
    skill_version: str
    provider: str
    model: str
    evidence_refs: tuple[EvidenceRef, ...]
    usage: Mapping[str, int] | None = None
    latency_ms: float | None = None
    observation_kind: str = "agent_turn"

    def __post_init__(self) -> None:
        for field in (
            "agent_id",
            "task_id",
            "skill",
            "skill_version",
            "provider",
            "model",
            "observation_kind",
        ):
            _opaque(getattr(self, field), field)
        if not self.evidence_refs:
            raise OtlpContractError("evidence_refs must not be empty")
        if self.usage is not None:
            allowed = {"input_tokens", "output_tokens", "total_tokens"}
            if set(self.usage) - allowed:
                raise OtlpContractError("usage has unsupported fields")
            for field, value in self.usage.items():
                if type(value) is not int or value < 0:
                    raise OtlpContractError(f"usage.{field} must be a non-negative integer")
        if self.latency_ms is not None and (
            isinstance(self.latency_ms, bool)
            or not isinstance(self.latency_ms, (int, float))
            or not math.isfinite(float(self.latency_ms))
            or self.latency_ms < 0
        ):
            raise OtlpContractError("latency_ms must be a finite non-negative number")

    def attributes(self) -> dict[str, object]:
        """Return only identifiers, hashes and usage facts; never content."""

        values: dict[str, object] = {
            "gen_ai.conversation.id": self.correlation.campaign_id,
            "gen_ai.session.id": self.correlation.run_id,
            "gen_ai.agent.id": self.agent_id,
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.provider.name": self.provider,
            "gen_ai.request.model": self.model,
            "agentteams.task.id": self.task_id,
            "testweaver.run_id": self.correlation.run_id,
            "testweaver.campaign_id": self.correlation.campaign_id,
            "testweaver.pg_revision": self.correlation.pg_revision,
            "testweaver.content_hash": self.correlation.content_hash,
            "testweaver.skill.name": self.skill,
            "testweaver.skill.version": self.skill_version,
            "testweaver.evidence.refs": [item.ref for item in self.evidence_refs],
            "testweaver.evidence.hashes": [item.content_hash for item in self.evidence_refs],
            "testweaver.observation.kind": self.observation_kind,
        }
        if self.usage is not None:
            values.update(
                {
                    f"gen_ai.usage.{field}": value
                    for field, value in self.usage.items()
                }
            )
        if self.latency_ms is not None:
            values["testweaver.latency_ms"] = self.latency_ms
        return values


@dataclass(frozen=True, repr=False)
class OtlpResponse:
    status_code: int
    body: bytes


@dataclass(frozen=True)
class OtlpReceipt:
    """Sanitized export result; ``body`` and headers are intentionally absent."""

    schema_version: str
    status: str
    endpoint: str
    http_method: str
    read_only_native_state: bool
    live_claim: bool
    trace_id: str
    span_id: str
    request_hash: str
    response_status: int | None
    response_hash: str | None
    response_bytes: int
    reason: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "endpoint": self.endpoint,
            "http_method": self.http_method,
            "read_only_native_state": self.read_only_native_state,
            "live_claim": self.live_claim,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "request_hash": self.request_hash,
            "response_status": self.response_status,
            "response_hash": self.response_hash,
            "response_bytes": self.response_bytes,
            "reason": self.reason,
        }


OtlpTransport = Callable[[str, Mapping[str, str], bytes, float], OtlpResponse]
HeaderProvider = Callable[[], Mapping[str, str]]


def _endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.rstrip("/").endswith("/v1/traces")
        or (parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "::1", "localhost"})
    ):
        raise OtlpContractError("OTLP endpoint must be an authenticated /v1/traces URL")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _otlp_value(value: object) -> dict[str, object]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return {"arrayValue": {"values": [_otlp_value(item) for item in value]}}
    raise OtlpContractError("OTLP attribute has unsupported value type")


def build_otlp_payload(
    context: GenAIContext,
    *,
    trace_id: str | None = None,
    span_id: str | None = None,
    started_ns: int | None = None,
    ended_ns: int | None = None,
) -> tuple[dict[str, object], str, str]:
    """Build one OTLP/HTTP JSON request without writing it anywhere."""

    trace_id = trace_id or secrets.token_hex(16)
    span_id = span_id or secrets.token_hex(8)
    if not re.fullmatch(r"[0-9a-f]{32}", trace_id) or not re.fullmatch(r"[0-9a-f]{16}", span_id):
        raise OtlpContractError("trace_id or span_id has invalid format")
    started_ns = started_ns or time_ns()
    ended_ns = ended_ns or max(started_ns, time_ns())
    if started_ns <= 0 or ended_ns < started_ns:
        raise OtlpContractError("OTLP span time window is invalid")
    attributes = [
        {"key": key, "value": _otlp_value(value)}
        for key, value in context.attributes().items()
    ]
    payload: dict[str, object] = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "testweaver"}},
                        {"key": "service.version", "value": {"stringValue": "observability-v1"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "testweaver.observability", "version": "1"},
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": span_id,
                                "name": "testweaver.agent.turn",
                                "kind": "SPAN_KIND_INTERNAL",
                                "startTimeUnixNano": str(started_ns),
                                "endTimeUnixNano": str(ended_ns),
                                "attributes": attributes,
                                "status": {"code": "STATUS_CODE_OK"},
                            }
                        ],
                    }
                ],
            }
        ]
    }
    return payload, trace_id, span_id


def _urllib_post(url: str, headers: Mapping[str, str], body: bytes, timeout: float) -> OtlpResponse:
    request = Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return OtlpResponse(response.status, response.read(_MAX_REQUEST_BYTES + 1))
    except HTTPError as error:
        return OtlpResponse(error.code, error.read(_MAX_REQUEST_BYTES + 1))
    except URLError:
        raise


def emit_genai_span(
    *,
    endpoint: str,
    context: GenAIContext,
    header_provider: HeaderProvider | None = None,
    transport: OtlpTransport | None = None,
    timeout_seconds: float = 10.0,
) -> OtlpReceipt:
    """Emit one real OTLP span and return a non-LIVE, hash-only receipt."""

    if timeout_seconds <= 0 or timeout_seconds > 60:
        raise OtlpContractError("timeout_seconds must be between 0 and 60")
    safe_endpoint = _endpoint(endpoint)
    payload, trace_id, span_id = build_otlp_payload(context)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > _MAX_REQUEST_BYTES:
        raise OtlpContractError("OTLP request exceeds the bounded size")
    request_hash = "sha256:" + hashlib.sha256(body).hexdigest()
    headers: dict[str, str] = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if header_provider is not None:
        try:
            supplied = header_provider()
            if not isinstance(supplied, Mapping):
                raise TypeError
            for key, value in supplied.items():
                if (
                    not isinstance(key, str)
                    or not key
                    or any(ord(character) < 32 for character in key)
                    or not isinstance(value, str)
                    or any(ord(character) < 32 for character in value)
                ):
                    raise ValueError
                headers[key] = value
        except Exception:
            return OtlpReceipt(
                "testweaver.otlp-receipt/v1",
                "BLOCKED",
                safe_endpoint,
                "POST",
                True,
                False,
                trace_id,
                span_id,
                request_hash,
                None,
                None,
                0,
                "auth_header_provider_failed",
            )
    sender = transport or _urllib_post
    try:
        response = sender(safe_endpoint, headers, body, timeout_seconds)
    except (OSError, TimeoutError, URLError):
        return OtlpReceipt(
            "testweaver.otlp-receipt/v1",
            "BLOCKED",
            safe_endpoint,
            "POST",
            True,
            False,
            trace_id,
            span_id,
            request_hash,
            None,
            None,
            0,
            "otlp_transport_failed",
        )
    if not isinstance(response, OtlpResponse) or not isinstance(response.body, bytes):
        return OtlpReceipt(
            "testweaver.otlp-receipt/v1",
            "BLOCKED",
            safe_endpoint,
            "POST",
            True,
            False,
            trace_id,
            span_id,
            request_hash,
            None,
            None,
            0,
            "invalid_otlp_transport_response",
        )
    response_hash = "sha256:" + hashlib.sha256(response.body).hexdigest()
    accepted = 200 <= response.status_code < 300
    return OtlpReceipt(
        "testweaver.otlp-receipt/v1",
        "EXPORT_ACCEPTED" if accepted else "BLOCKED",
        safe_endpoint,
        "POST",
        True,
        False,
        trace_id,
        span_id,
        request_hash,
        response.status_code,
        response_hash,
        len(response.body),
        None if accepted else "otlp_export_non_success",
    )


@dataclass(frozen=True, repr=False)
class LoongSuiteOtlpBinding:
    """In-memory CMS binding loaded from a deployment-owned config file."""

    endpoint: str
    project: str
    workspace: str
    _license_key: str
    config_path: str
    config_mode: int

    def __repr__(self) -> str:
        return (
            "LoongSuiteOtlpBinding("
            f"endpoint={self.endpoint!r}, project={self.project!r}, "
            f"workspace={self.workspace!r}, license_key_present=True)"
        )

    def headers(self) -> dict[str, str]:
        return {
            "x-arms-license-key": self._license_key,
            "x-arms-project": self.project,
            "x-cms-workspace": self.workspace,
        }

    def names_only(self) -> dict[str, object]:
        return {
            "config_path": self.config_path,
            "config_mode": self.config_mode,
            "endpoint": self.endpoint,
            "project_present": bool(self.project),
            "workspace_present": bool(self.workspace),
            "license_key_present": bool(self._license_key),
        }


def load_loongsuite_otlp_binding(path: Path) -> LoongSuiteOtlpBinding:
    """Load only the CMS export shape; the license key never leaves memory."""

    if not path.is_absolute():
        raise OtlpContractError("LoongSuite config path must be absolute")
    try:
        metadata = path.stat()
        mode = stat.S_IMODE(metadata.st_mode)
        if not stat.S_ISREG(metadata.st_mode) or mode & 0o077:
            raise OtlpContractError("LoongSuite config must be an owner-only regular file")
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OtlpContractError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise OtlpContractError("LoongSuite config is unavailable or invalid") from error
    cms = raw.get("cms") if isinstance(raw, dict) else None
    if not isinstance(cms, dict):
        raise OtlpContractError("LoongSuite config has no CMS section")
    endpoint = cms.get("endpoint")
    license_key = cms.get("licenseKey")
    workspace = cms.get("workspace")
    if not all(isinstance(item, str) and item for item in (endpoint, license_key, workspace)):
        raise OtlpContractError("LoongSuite CMS binding is incomplete")
    parsed = urlsplit(endpoint)
    hostname = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or not hostname.endswith(".aliyuncs.com")
        or parsed.query
        or parsed.fragment
        or not parsed.path.rstrip("/").endswith("/apm/trace/opentelemetry")
    ):
        raise OtlpContractError("LoongSuite CMS endpoint is not an official OTLP endpoint")
    project = hostname.split(".", 1)[0]
    return LoongSuiteOtlpBinding(
        endpoint=urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") + "/v1/traces", "", "")),
        project=_opaque(project, "LoongSuite project"),
        workspace=_opaque(workspace, "LoongSuite workspace"),
        _license_key=license_key,
        config_path=str(path),
        config_mode=mode,
    )
