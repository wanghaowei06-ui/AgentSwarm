"""Bounded, read-only XTrace server-side readback for a known real Trace ID."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from testweaver.authority import (
    AuthorityError,
    digest_bytes,
    validate_hash,
    validate_ref,
)
from testweaver.contracts.validator import canonical_hash

from .agentloop_client import AgentLoopCredentialLease, CredentialCallback
from .tea_transport import (
    AlibabaCloudCredential,
    TeaCaller,
    TeaCallFailure,
    _call_with_tea,
    _normalize_response,
    _request_id,
    _request_id_from_body,
    _validate_endpoint,
    _validate_region,
)

_TRACE_HEX_LENGTHS = {16, 30, 32}
_TERMINAL_STATUSES = {401, 403}


@dataclass(frozen=True, slots=True)
class XTraceCorrelation:
    campaign_id: str
    run_id: str
    pg_revision: int
    content_hash: str

    def __post_init__(self) -> None:
        validate_ref(self.campaign_id, "campaign_id")
        validate_ref(self.run_id, "run_id")
        if (
            isinstance(self.pg_revision, bool)
            or not isinstance(self.pg_revision, int)
            or self.pg_revision < 1
        ):
            raise AuthorityError("PostgreSQL revision must be positive")
        validate_hash(self.content_hash, "content_hash")


class XTraceHTTPResponse:
    __slots__ = ("body", "error_code", "request_id", "status_code")

    status_code: int
    body: bytes
    request_id: str | None
    error_code: str | None

    def __init__(
        self,
        status_code: int,
        body: bytes,
        request_id: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.body = body
        self.request_id = request_id
        self.error_code = error_code

    def __repr__(self) -> str:
        return (
            f"XTraceHTTPResponse(status_code={self.status_code!r}, body=<redacted>, "
            f"request_id_present={self.request_id is not None!r}, "
            f"error_code={self.error_code!r})"
        )


class XTraceTransport(Protocol):
    def get_trace(
        self,
        *,
        region: str,
        trace_id: str,
        credential: object,
    ) -> XTraceHTTPResponse: ...


class TeaXTraceTransport:
    """Signed XTrace/2019-08-08 RPC transport for GetTrace only."""

    __slots__ = ("caller",)

    def __init__(self, *, caller: TeaCaller | None = None) -> None:
        self.caller = caller or _call_with_tea

    def get_trace(
        self,
        *,
        region: str,
        trace_id: str,
        credential: object,
    ) -> XTraceHTTPResponse:
        _validate_region(region)
        hostname = _validate_endpoint(
            f"https://xtrace.{region}.aliyuncs.com", product="xtrace", region=region
        )
        _validate_trace_id(trace_id)
        if not isinstance(credential, AlibabaCloudCredential):
            raise AuthorityError(
                "XTrace Tea transport requires protected Alibaba credentials"
            )
        try:
            response = self.caller(
                product="xtrace",
                version="2019-08-08",
                operation="GetTrace",
                style="RPC",
                method="POST",
                hostname=hostname,
                region=region,
                path="/",
                query={
                    "TraceID": trace_id,
                    "RegionId": region,
                    "PageNumber": "1",
                    "PageSize": "100",
                },
                body=None,
                credential=credential,
            )
        except TeaCallFailure as exc:
            return XTraceHTTPResponse(
                exc.status_code,
                b"",
                request_id=exc.request_id,
                error_code=exc.error_code,
            )
        status_code, headers, body = _normalize_response(response)
        return XTraceHTTPResponse(
            status_code,
            body,
            _request_id(headers) or _request_id_from_body(body),
        )


@dataclass(frozen=True, slots=True)
class XTraceReadbackReceipt:
    status: str
    attempt_count: int
    response_status: int | None
    response_hash: str | None
    request_id_hash: str | None
    trace_id_hash: str
    span_count: int
    trace_id_matched: bool
    authority_anchor_matches: Mapping[str, bool]
    observed_at: str
    reason: str | None
    content_hash: str

    def __post_init__(self) -> None:
        if self.status not in {"API_QUERY_VERIFIED", "NOT_VERIFIED", "BLOCKED"}:
            raise AuthorityError("XTrace readback status is invalid")
        if not 1 <= self.attempt_count <= 3:
            raise AuthorityError("XTrace attempt count is outside the bounded limit")
        if self.span_count < 0:
            raise AuthorityError("XTrace span count must be non-negative")
        if set(self.authority_anchor_matches) != {
            "campaign_id",
            "run_id",
            "pg_revision",
            "content_hash",
        }:
            raise AuthorityError("XTrace authority anchor set is incomplete")
        for value in (self.trace_id_hash, self.content_hash):
            validate_hash(value, "XTrace receipt hash")
        for value in (self.response_hash, self.request_id_hash):
            if value is not None:
                validate_hash(value, "XTrace optional hash")
        expected = canonical_hash(_receipt_values(self))
        if self.content_hash != expected:
            raise AuthorityError("XTrace readback receipt is not sealed")


@dataclass(slots=True)
class XTraceReadbackClient:
    region: str
    transport: XTraceTransport
    credentials: CredentialCallback
    clock: Callable[[], str]
    sleeper: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        _validate_region(self.region)

    def get_trace(
        self,
        *,
        trace_id: str,
        correlation: XTraceCorrelation,
        max_attempts: int = 1,
        poll_interval_seconds: float = 5.0,
        max_elapsed_seconds: float = 90.0,
    ) -> XTraceReadbackReceipt:
        _validate_trace_id(trace_id)
        if not 1 <= max_attempts <= 3:
            raise AuthorityError("XTrace readback allows at most three attempts")
        if not 0 <= poll_interval_seconds <= 45:
            raise AuthorityError("XTrace poll interval is outside the bounded limit")
        if not 0 < max_elapsed_seconds <= 90:
            raise AuthorityError("XTrace elapsed budget is outside the bounded limit")
        trace_id_hash = digest_bytes(trace_id.encode())
        started = self.monotonic()
        last: XTraceReadbackReceipt | None = None
        for attempt in range(1, max_attempts + 1):
            if attempt > 1 and self.monotonic() - started >= max_elapsed_seconds:
                break
            try:
                lease = self.credentials()
                if not isinstance(lease, AgentLoopCredentialLease):
                    raise AuthorityError(
                        "credential callback returned an invalid lease"
                    )
                validate_ref(lease.protected_ref, "credential_protected_ref")
            except Exception:  # noqa: BLE001 - protected runtime boundary
                return _seal_receipt(
                    status="BLOCKED",
                    attempt_count=attempt,
                    response_status=None,
                    response_hash=None,
                    request_id_hash=None,
                    trace_id_hash=trace_id_hash,
                    span_count=0,
                    trace_id_matched=False,
                    authority_anchor_matches=_empty_anchor_matches(),
                    observed_at=self.clock(),
                    reason="CREDENTIAL_UNAVAILABLE",
                )
            try:
                response = self.transport.get_trace(
                    region=self.region,
                    trace_id=trace_id,
                    credential=lease.material,
                )
            except Exception:  # noqa: BLE001 - cloud boundary
                return _seal_receipt(
                    status="BLOCKED",
                    attempt_count=attempt,
                    response_status=None,
                    response_hash=None,
                    request_id_hash=None,
                    trace_id_hash=trace_id_hash,
                    span_count=0,
                    trace_id_matched=False,
                    authority_anchor_matches=_empty_anchor_matches(),
                    observed_at=self.clock(),
                    reason="ENDPOINT_UNAVAILABLE",
                )
            if response.status_code in _TERMINAL_STATUSES:
                return _seal_receipt(
                    status="BLOCKED",
                    attempt_count=attempt,
                    response_status=response.status_code,
                    response_hash=digest_bytes(response.body),
                    request_id_hash=_optional_hash(response.request_id),
                    trace_id_hash=trace_id_hash,
                    span_count=0,
                    trace_id_matched=False,
                    authority_anchor_matches=_empty_anchor_matches(),
                    observed_at=self.clock(),
                    reason="PERMISSION_DENIED",
                )
            if not 200 <= response.status_code < 300:
                return _seal_receipt(
                    status="BLOCKED",
                    attempt_count=attempt,
                    response_status=response.status_code,
                    response_hash=digest_bytes(response.body),
                    request_id_hash=_optional_hash(response.request_id),
                    trace_id_hash=trace_id_hash,
                    span_count=0,
                    trace_id_matched=False,
                    authority_anchor_matches=_empty_anchor_matches(),
                    observed_at=self.clock(),
                    reason="API_REJECTED",
                )
            last = _receipt_from_success(
                response=response,
                attempt=attempt,
                trace_id=trace_id,
                trace_id_hash=trace_id_hash,
                correlation=correlation,
                observed_at=self.clock(),
            )
            if last.status == "API_QUERY_VERIFIED":
                return last
            if attempt < max_attempts:
                remaining = max_elapsed_seconds - (self.monotonic() - started)
                if remaining <= 0:
                    break
                self.sleeper(min(poll_interval_seconds, remaining))
        if last is not None:
            return last
        return _seal_receipt(
            status="NOT_VERIFIED",
            attempt_count=1,
            response_status=None,
            response_hash=None,
            request_id_hash=None,
            trace_id_hash=trace_id_hash,
            span_count=0,
            trace_id_matched=False,
            authority_anchor_matches=_empty_anchor_matches(),
            observed_at=self.clock(),
            reason="ELAPSED_BUDGET_EXHAUSTED",
        )


def _receipt_from_success(
    *,
    response: XTraceHTTPResponse,
    attempt: int,
    trace_id: str,
    trace_id_hash: str,
    correlation: XTraceCorrelation,
    observed_at: str,
) -> XTraceReadbackReceipt:
    spans = _parse_spans(response.body)
    matching_spans = [span for span in spans if span.get("TraceID") == trace_id]
    tags: dict[str, str] = {}
    for span in matching_spans:
        for entry in _tag_entries(span.get("TagEntryList")):
            key = entry.get("Key")
            value = entry.get("Value")
            if (
                isinstance(key, str)
                and isinstance(value, (str, int))
                and not isinstance(value, bool)
            ):
                tags[key] = str(value)
    matches = {
        "campaign_id": tags.get("testweaver.campaign_id") == correlation.campaign_id,
        "run_id": tags.get("testweaver.run_id") == correlation.run_id,
        "pg_revision": tags.get("testweaver.pg_revision")
        == str(correlation.pg_revision),
        "content_hash": tags.get("testweaver.content_hash") == correlation.content_hash,
    }
    verified = bool(matching_spans) and all(matches.values())
    return _seal_receipt(
        status="API_QUERY_VERIFIED" if verified else "NOT_VERIFIED",
        attempt_count=attempt,
        response_status=response.status_code,
        response_hash=digest_bytes(response.body),
        request_id_hash=_optional_hash(response.request_id),
        trace_id_hash=trace_id_hash,
        span_count=len(spans),
        trace_id_matched=bool(matching_spans),
        authority_anchor_matches=matches,
        observed_at=observed_at,
        reason=None if verified else "TRACE_OR_AUTHORITY_ANCHORS_NOT_OBSERVED",
    )


def _parse_spans(body: bytes) -> list[Mapping[str, Any]]:
    if len(body) > 4 * 1024 * 1024:
        return []
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(value, Mapping):
        return []
    spans = value.get("Spans", [])
    if isinstance(spans, Mapping):
        spans = spans.get("Span", [])
    if not isinstance(spans, list):
        return []
    return [span for span in spans[:1000] if isinstance(span, Mapping)]


def _tag_entries(value: object) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        value = value.get("TagEntry", [])
    if not isinstance(value, list):
        return []
    return [entry for entry in value[:1000] if isinstance(entry, Mapping)]


def _validate_trace_id(trace_id: str) -> None:
    if (
        not isinstance(trace_id, str)
        or len(trace_id) not in _TRACE_HEX_LENGTHS
        or any(character not in "0123456789abcdefABCDEF" for character in trace_id)
    ):
        raise AuthorityError("XTrace TraceID must be a bounded hexadecimal identifier")


def _empty_anchor_matches() -> dict[str, bool]:
    return {
        "campaign_id": False,
        "run_id": False,
        "pg_revision": False,
        "content_hash": False,
    }


def _optional_hash(value: str | None) -> str | None:
    return digest_bytes(value.encode()) if value else None


def _receipt_values(receipt: XTraceReadbackReceipt) -> dict[str, object]:
    return {
        "status": receipt.status,
        "attempt_count": receipt.attempt_count,
        "response_status": receipt.response_status,
        "response_hash": receipt.response_hash,
        "request_id_hash": receipt.request_id_hash,
        "trace_id_hash": receipt.trace_id_hash,
        "span_count": receipt.span_count,
        "trace_id_matched": receipt.trace_id_matched,
        "authority_anchor_matches": dict(receipt.authority_anchor_matches),
        "observed_at": receipt.observed_at,
        "reason": receipt.reason,
    }


def _seal_receipt(**values: Any) -> XTraceReadbackReceipt:
    return XTraceReadbackReceipt(**values, content_hash=canonical_hash(values))


__all__ = [
    "TeaXTraceTransport",
    "XTraceCorrelation",
    "XTraceHTTPResponse",
    "XTraceReadbackClient",
    "XTraceReadbackReceipt",
]
