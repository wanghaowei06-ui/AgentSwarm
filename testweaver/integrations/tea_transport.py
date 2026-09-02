"""Alibaba Cloud Tea transports with runtime-only protected credentials.

This module signs AgentLoop requests but never owns an AgentLoop resource and
never persists credential values or response bodies.  Callers decide which
bounded create/read operation is allowed and retain only sanitized receipts.
"""

from __future__ import annotations

import csv
import io
import json
import os
import stat
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from testweaver.authority import AuthorityError

from .agentloop_client import AgentLoopHTTPResponse

_MAX_CREDENTIAL_BYTES = 64 * 1024
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class AlibabaCloudCredential:
    """Non-dataclass secret carrier; repr and dataclasses.asdict cannot expand it."""

    __slots__ = ("_access_key_id", "_access_key_secret", "_security_token")

    def __init__(
        self,
        access_key_id: str,
        access_key_secret: str,
        security_token: str | None = None,
    ) -> None:
        for value in (access_key_id, access_key_secret):
            if not isinstance(value, str) or not value or len(value) > 1024:
                raise AuthorityError("Alibaba Cloud credential material is invalid")
            if any(ord(character) < 32 for character in value):
                raise AuthorityError(
                    "Alibaba Cloud credential material contains control data"
                )
        if security_token is not None and (
            not isinstance(security_token, str)
            or not security_token
            or len(security_token) > 8192
            or any(ord(character) < 32 for character in security_token)
        ):
            raise AuthorityError("Alibaba Cloud security token is invalid")
        self._access_key_id = access_key_id
        self._access_key_secret = access_key_secret
        self._security_token = security_token

    def __repr__(self) -> str:
        return "AlibabaCloudCredential(<redacted>)"

    def _runtime_values(self) -> tuple[str, str, str | None]:
        return self._access_key_id, self._access_key_secret, self._security_token


def load_protected_csv_credential(path: Path) -> AlibabaCloudCredential:
    """Load one owner-only AccessKey CSV without following symlinks."""

    if not path.is_absolute():
        raise AuthorityError("credential path must be absolute")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise AuthorityError("credential file must be an owner-only regular file")
        if metadata.st_size < 1 or metadata.st_size > _MAX_CREDENTIAL_BYTES:
            raise AuthorityError("credential file size is outside the bounded limit")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = None
            raw = stream.read(_MAX_CREDENTIAL_BYTES + 1)
    except AuthorityError:
        raise
    except OSError as exc:
        raise AuthorityError("credential file is unavailable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(raw) > _MAX_CREDENTIAL_BYTES:
        raise AuthorityError("credential file size is outside the bounded limit")
    try:
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise AuthorityError("credential CSV is invalid") from exc
    if len(rows) != 2 or rows[0] != ["AccessKey ID", "AccessKey Secret"]:
        raise AuthorityError(
            "credential CSV must contain the exact two-column header and one row"
        )
    if len(rows[1]) != 2 or not all(rows[1]):
        raise AuthorityError("credential CSV data row is incomplete")
    return AlibabaCloudCredential(rows[1][0], rows[1][1])


class TeaCallFailure(RuntimeError):
    def __init__(
        self,
        status_code: int,
        *,
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__("Alibaba Cloud API request failed")
        self.status_code = status_code
        self.error_code = error_code
        self.request_id = request_id


TeaCaller = Callable[..., Mapping[str, Any]]


class TeaAgentLoopTransport:
    """Signed AgentLoop/2026-05-20 ROA transport with one request per call."""

    __slots__ = ("caller", "region")

    def __init__(self, region: str, *, caller: TeaCaller | None = None) -> None:
        _validate_region(region)
        self.region = region
        self.caller = caller or _call_with_tea

    def request(
        self,
        *,
        operation: str,
        method: str,
        endpoint: str,
        path: str,
        query: Mapping[str, str],
        body: bytes | None,
        credential: object,
    ) -> AgentLoopHTTPResponse:
        hostname = _validate_endpoint(endpoint, product="agentloop", region=self.region)
        if method not in {"GET", "POST"} or not path.startswith("/") or "?" in path:
            raise AuthorityError("AgentLoop request shape is invalid")
        if not isinstance(credential, AlibabaCloudCredential):
            raise AuthorityError(
                "AgentLoop Tea transport requires protected Alibaba credentials"
            )
        parsed_body: Mapping[str, Any] | None = None
        if body is not None:
            try:
                candidate = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AuthorityError("AgentLoop request body is not JSON") from exc
            if not isinstance(candidate, Mapping):
                raise AuthorityError("AgentLoop request body must be an object")
            parsed_body = candidate
        try:
            response = self.caller(
                product="agentloop",
                version="2026-05-20",
                operation=operation,
                style="ROA",
                method=method,
                hostname=hostname,
                region=self.region,
                path=path,
                query=dict(query),
                body=parsed_body,
                credential=credential,
            )
        except TeaCallFailure as exc:
            return AgentLoopHTTPResponse(
                exc.status_code,
                b"",
                request_id=exc.request_id,
                error_code=exc.error_code,
            )
        status_code, headers, response_body = _normalize_response(response)
        return AgentLoopHTTPResponse(
            status_code,
            response_body,
            request_id=_request_id(headers),
            error_code=None,
        )


def _validate_endpoint(endpoint: str, *, product: str, region: str) -> str:
    parsed = urlsplit(endpoint)
    expected = f"{product}.{region}.aliyuncs.com"
    if (
        parsed.scheme != "https"
        or parsed.hostname != expected
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise AuthorityError(
            f"{product} endpoint must be canonical HTTPS for its region"
        )
    return expected


def _validate_region(region: str) -> None:
    if (
        not isinstance(region, str)
        or not region
        or len(region) > 64
        or any(
            not (character.islower() or character.isdigit() or character == "-")
            for character in region
        )
    ):
        raise AuthorityError("Alibaba Cloud region is invalid")


def _normalize_response(
    response: Mapping[str, Any],
) -> tuple[int, Mapping[str, Any], bytes]:
    status_code = response.get("status_code", response.get("statusCode"))
    if isinstance(status_code, bool) or not isinstance(status_code, int):
        raise AuthorityError("Tea response has no status code")
    headers = response.get("headers")
    if not isinstance(headers, Mapping):
        headers = {}
    body = response.get("body", {})
    if isinstance(body, bytes):
        encoded = body
    else:
        try:
            encoded = json.dumps(
                body,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise AuthorityError("Tea response body is not bounded JSON") from exc
    if len(encoded) > _MAX_RESPONSE_BYTES:
        raise AuthorityError("Tea response body exceeds the bounded limit")
    return status_code, headers, encoded


def _request_id(headers: Mapping[str, Any]) -> str | None:
    for key, value in headers.items():
        if str(key).lower() in {"x-acs-request-id", "x-request-id"} and isinstance(
            value, str
        ):
            return value
    return None


def _call_with_tea(**request: Any) -> Mapping[str, Any]:
    """Import Alibaba Tea lazily so contract tests do not require the SDK."""

    try:
        from alibabacloud_tea_openapi import models as openapi_models
        from alibabacloud_tea_openapi.client import Client as OpenApiClient
        from alibabacloud_tea_util import models as util_models
        from Tea.exceptions import TeaException
    except ImportError as exc:
        raise AuthorityError("Alibaba Cloud Tea dependencies are unavailable") from exc
    credential = request["credential"]
    assert isinstance(credential, AlibabaCloudCredential)
    access_key_id, access_key_secret, security_token = credential._runtime_values()
    config = openapi_models.Config(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        security_token=security_token,
        endpoint=request["hostname"],
        region_id=request["region"],
        connect_timeout=3000,
        read_timeout=10000,
    )
    client = OpenApiClient(config)
    style = request["style"]
    pathname = request["path"] if style == "ROA" else "/"
    try:
        return client.call_api(
            openapi_models.Params(
                action=request["operation"],
                version=request["version"],
                protocol="HTTPS",
                pathname=pathname,
                method=request["method"],
                auth_type="AK",
                body_type="json",
                req_body_type="json",
                style=style,
            ),
            openapi_models.OpenApiRequest(
                query=request["query"],
                body=request["body"],
            ),
            util_models.RuntimeOptions(
                autoretry=False,
                max_attempts=1,
                connect_timeout=3000,
                read_timeout=10000,
            ),
        )
    except TeaException as exc:
        data = getattr(exc, "data", None)
        if not isinstance(data, Mapping):
            data = {}
        status_code = getattr(exc, "status_code", None) or data.get("statusCode") or 500
        if isinstance(status_code, bool) or not isinstance(status_code, int):
            status_code = 500
        error_code = data.get("Code") or data.get("code")
        request_id = data.get("RequestId") or data.get("requestId")
        raise TeaCallFailure(
            status_code,
            error_code=error_code if isinstance(error_code, str) else None,
            request_id=request_id if isinstance(request_id, str) else None,
        ) from None


__all__ = [
    "AlibabaCloudCredential",
    "TeaAgentLoopTransport",
    "TeaCallFailure",
    "load_protected_csv_credential",
]
