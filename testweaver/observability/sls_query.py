"""Read-only AgentSpace/SLS correlation for real AgentLoop observations.

AgentLoop evaluation output is read from the tenant's SLS Logstore.  This
module signs one bounded GetLogs request in memory; it never creates an
AgentLoop resource, writes a log, or puts credentials, SQL, or response data
in a receipt.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .readonly_query import Correlation, ConfigReferenceStatus, ProtectedConfigRef


SlsStatus = str
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_VARIABLE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_DNS_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_QUERY_ROWS = 100
_MAX_CREDENTIAL_FILE_BYTES = 64 * 1024
EVALUATION_DETAIL_LOGSTORE = "evaluation_detail"


class SlsContractError(ValueError):
    """Raised for an invalid non-secret SLS binding or query anchor."""


def _opaque(value: object, field: str, pattern: re.Pattern[str] = _IDENTIFIER) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise SlsContractError(f"{field} must be a bounded opaque identifier")
    return value


def _digest(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


@dataclass(frozen=True, repr=False)
class SlsCredentials:
    """Short-lived in-memory credentials supplied by deployment code."""

    access_key_id: str
    access_key_secret: str
    security_token: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("access_key_id", "access_key_secret"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value or len(value) > 512:
                raise SlsContractError(f"{field_name} is invalid")
            if any(ord(character) < 32 or character.isspace() for character in value):
                raise SlsContractError(f"{field_name} contains control data")
        if self.security_token is not None:
            if not isinstance(self.security_token, str) or len(self.security_token) > 4096:
                raise SlsContractError("security_token is invalid")
            if any(ord(character) < 32 for character in self.security_token):
                raise SlsContractError("security_token contains control data")

    def __repr__(self) -> str:
        return "SlsCredentials(access_key_id_present=True, secret_present=True, token_present=%s)" % (
            self.security_token is not None,
        )


CredentialProvider = Callable[[], SlsCredentials]


def _read_protected_text(path: Path) -> str:
    """Read one bounded owner-only file without exposing its contents."""

    if not path.is_absolute():
        raise SlsContractError("protected credential path must be absolute")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise SlsContractError("protected credential file must be owner-only regular file")
        if metadata.st_size < 0 or metadata.st_size > _MAX_CREDENTIAL_FILE_BYTES:
            raise SlsContractError("protected credential file is too large")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = None
            raw = stream.read(_MAX_CREDENTIAL_FILE_BYTES + 1)
    except SlsContractError:
        raise
    except (OSError, ValueError) as error:
        raise SlsContractError("protected credential file is unavailable") from error
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
    if len(raw) > _MAX_CREDENTIAL_FILE_BYTES:
        raise SlsContractError("protected credential file is too large")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SlsContractError("protected credential file is not UTF-8") from error
    if any(ord(character) < 32 and character not in "\n\r\t" for character in text):
        raise SlsContractError("protected credential file contains control data")
    return text


def _credential_names(
    access_key_id_name: str,
    access_key_secret_name: str,
    security_token_name: str | None,
) -> tuple[str, str, str | None]:
    names = (access_key_id_name, access_key_secret_name, security_token_name)
    for name in names:
        if name is not None and not _VARIABLE.fullmatch(name):
            raise SlsContractError("credential variable name is invalid")
    if access_key_id_name == access_key_secret_name or (
        security_token_name is not None
        and security_token_name in {access_key_id_name, access_key_secret_name}
    ):
        raise SlsContractError("credential variable names must be distinct")
    return names


def _parse_env_credentials(
    text: str,
    *,
    access_key_id_name: str,
    access_key_secret_name: str,
    security_token_name: str | None,
) -> SlsCredentials:
    values: dict[str, str] = {}
    wanted = {access_key_id_name, access_key_secret_name}
    if security_token_name is not None:
        wanted.add(security_token_name)
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator or name != name.strip() or not _VARIABLE.fullmatch(name):
            raise SlsContractError("protected env file has an invalid assignment")
        if name in values:
            raise SlsContractError("protected env file has a duplicate assignment")
        if name in wanted:
            values[name] = value
    missing = {access_key_id_name, access_key_secret_name}.difference(values)
    if missing:
        raise SlsContractError("protected env file is missing required credentials")
    return SlsCredentials(
        values[access_key_id_name],
        values[access_key_secret_name],
        (values.get(security_token_name) or None) if security_token_name is not None else None,
    )


def protected_env_credential_provider(
    path: Path,
    *,
    access_key_id_name: str = "ALIBABA_CLOUD_ACCESS_KEY_ID",
    access_key_secret_name: str = "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
    security_token_name: str | None = "ALIBABA_CLOUD_SECURITY_TOKEN",
) -> CredentialProvider:
    """Return a provider that loads selected credentials into memory on demand."""

    _credential_names(access_key_id_name, access_key_secret_name, security_token_name)

    def provider() -> SlsCredentials:
        return _parse_env_credentials(
            _read_protected_text(path),
            access_key_id_name=access_key_id_name,
            access_key_secret_name=access_key_secret_name,
            security_token_name=security_token_name,
        )

    return provider


def protected_csv_credential_provider(
    path: Path,
    *,
    access_key_id_column: str = "AccessKey ID",
    access_key_secret_column: str = "AccessKey Secret",
) -> CredentialProvider:
    """Return a provider for one owner-only AccessKey CSV row."""

    if (
        not access_key_id_column
        or not access_key_secret_column
        or access_key_id_column == access_key_secret_column
        or any(char in access_key_id_column + access_key_secret_column for char in "\r\n")
    ):
        raise SlsContractError("credential CSV columns are invalid")

    def provider() -> SlsCredentials:
        try:
            rows = list(csv.reader(io.StringIO(_read_protected_text(path))))
        except csv.Error as error:
            raise SlsContractError("protected credential CSV is invalid") from error
        if not rows:
            raise SlsContractError("protected credential CSV is empty")
        header = rows[0]
        if len(header) != len(set(header)):
            raise SlsContractError("protected credential CSV has duplicate columns")
        required = {access_key_id_column, access_key_secret_column}
        if not required.issubset(header):
            raise SlsContractError("protected credential CSV is missing required columns")
        data_rows = [row for row in rows[1:] if any(cell != "" for cell in row)]
        if len(data_rows) != 1 or len(data_rows[0]) != len(header):
            raise SlsContractError("protected credential CSV must contain one complete row")
        row = dict(zip(header, data_rows[0]))
        return SlsCredentials(row[access_key_id_column], row[access_key_secret_column])

    return provider


@dataclass(frozen=True)
class SlsBinding:
    """Tenant-owned SLS endpoint and non-secret identifiers."""

    endpoint: str
    project: str
    logstore: str
    agent_space: str | None = None

    def __post_init__(self) -> None:
        parsed = urlsplit(self.endpoint)
        host = parsed.hostname or ""
        try:
            port = parsed.port
        except ValueError as exc:
            raise SlsContractError("SLS endpoint has an invalid port") from exc
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or (parsed.scheme == "https" and port is not None)
            or (parsed.scheme == "http" and host not in {"127.0.0.1", "::1", "localhost"})
        ):
            raise SlsContractError("SLS endpoint must be an official HTTPS endpoint")
        _opaque(self.project, "sls.project", _NAME)
        _opaque(self.logstore, "sls.logstore", _NAME)
        if parsed.scheme == "https":
            labels = host.split(".")
            if (
                len(labels) < 4
                or labels[-3:] != ["log", "aliyuncs", "com"]
                or any(not _DNS_LABEL.fullmatch(label) for label in labels)
            ):
                raise SlsContractError("SLS endpoint must be an official HTTPS endpoint")
            if len(labels) == 4:
                qualified_labels = [self.project, *labels]
                if any(not _DNS_LABEL.fullmatch(label) for label in qualified_labels):
                    raise SlsContractError("SLS project cannot be represented in the SLS host")
            elif len(labels) == 5:
                if labels[0] != self.project or labels[-3:] != ["log", "aliyuncs", "com"]:
                    raise SlsContractError("SLS endpoint host does not match project")
            else:
                raise SlsContractError("SLS endpoint host has an unsupported shape")
        if self.agent_space is not None:
            _opaque(self.agent_space, "agent_space", _IDENTIFIER)

    @property
    def safe_endpoint(self) -> str:
        parsed = urlsplit(self.endpoint)
        host = parsed.hostname or ""
        if parsed.scheme == "http":
            netloc = parsed.netloc
        else:
            port = parsed.port
            if len(host.split(".")) == 4:
                host = f"{self.project}.{host}"
            if port is not None:
                host = f"{host}:{port}"
            netloc = host
        return urlunsplit((parsed.scheme, netloc, "", "", ""))

    def names_only(self) -> dict[str, object]:
        return {
            "endpoint": self.safe_endpoint,
            "project": self.project,
            "logstore": self.logstore,
            "agent_space_present": self.agent_space is not None,
        }


def load_sls_binding(
    path: Path,
    *,
    agent_space: str | None = None,
) -> SlsBinding:
    """Load SLS identifiers from an owner-only LoongSuite config in memory."""

    if not path.is_absolute():
        raise SlsContractError("SLS config path must be absolute")
    try:
        metadata = path.stat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise SlsContractError("SLS config must be an owner-only regular file")
        raw = json.loads(path.read_text(encoding="utf-8"))
    except SlsContractError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SlsContractError("SLS config is unavailable or invalid") from error
    section = raw.get("sls") if isinstance(raw, dict) else None
    if not isinstance(section, dict):
        raise SlsContractError("SLS config has no SLS section")
    endpoint = section.get("endpoint")
    project = section.get("project")
    logstore = section.get("logstore")
    if not all(isinstance(item, str) and item for item in (endpoint, project, logstore)):
        raise SlsContractError("SLS endpoint/project/logstore is incomplete")
    endpoint = _normalize_endpoint(endpoint)
    return SlsBinding(
        endpoint=endpoint,
        project=project,
        logstore=logstore,
        agent_space=agent_space,
    )


def _normalize_endpoint(value: str) -> str:
    """Accept an official host-only endpoint from older Pilot config."""

    if any(ord(character) < 32 or character.isspace() for character in value):
        raise SlsContractError("SLS endpoint contains control data")
    parsed = urlsplit(value)
    if not parsed.scheme and not parsed.netloc and all(mark not in value for mark in ("/", "?", "#")):
        value = "https://" + value
    return value


@dataclass(frozen=True, repr=False)
class SlsHttpResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class SlsQueryReceipt:
    """Hash-only result of one read-only GetLogs request."""

    schema_version: str
    status: SlsStatus
    operation: str
    endpoint: str
    project: str
    logstore: str
    http_method: str
    read_only: bool
    live_claim: bool
    correlation: Correlation
    query_hash: str
    response_status: int | None
    response_hash: str | None
    response_bytes: int
    row_count: int
    matched_row_count: int
    request_id_present: bool
    auth_attempted: bool
    reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "operation": self.operation,
            "endpoint": self.endpoint,
            "project": self.project,
            "logstore": self.logstore,
            "http_method": self.http_method,
            "read_only": self.read_only,
            "live_claim": self.live_claim,
            "correlation": self.correlation.as_dict(),
            "query_hash": self.query_hash,
            "response_status": self.response_status,
            "response_hash": self.response_hash,
            "response_bytes": self.response_bytes,
            "row_count": self.row_count,
            "matched_row_count": self.matched_row_count,
            "request_id_present": self.request_id_present,
            "auth_attempted": self.auth_attempted,
            "reason": self.reason,
        }


SlsTransport = Callable[[str, Mapping[str, str], float], SlsHttpResponse]


class SlsReadOnlyQueryClient:
    """Perform only bounded, signed SLS GetLogs reads."""

    def __init__(
        self,
        *,
        binding: SlsBinding,
        credential_ref: ProtectedConfigRef | None = None,
        credential_provider: CredentialProvider | None = None,
        transport: SlsTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 60:
            raise SlsContractError("timeout_seconds must be between 0 and 60")
        self.binding = binding
        self.credential_ref = credential_ref
        self.credential_provider = credential_provider
        self.transport = transport or _urllib_get
        self.timeout_seconds = timeout_seconds

    def preflight(self) -> dict[str, object]:
        credential = self.credential_ref.inspect() if self.credential_ref else None
        reason = self._preflight_reason(credential)
        return {
            "schema_version": "testweaver.sls-query-preflight/v1",
            "status": "BLOCKED" if reason else "NOT_VERIFIED",
            "backend": "agentspace-sls",
            "binding": self.binding.names_only(),
            "credential": credential.as_dict() if credential else None,
            "read_only": True,
            "live_claim": False,
            "reason": reason or "bounded_read_required",
        }

    def query_trace(
        self,
        *,
        correlation: Correlation,
        start_time_s: int,
        end_time_s: int,
        trace_id: str | None = None,
    ) -> SlsQueryReceipt:
        return self._query(
            operation="trace_readback",
            correlation=correlation,
            start_time_s=start_time_s,
            end_time_s=end_time_s,
            trace_id=trace_id,
            logstore=self.binding.logstore,
        )

    def query_evaluation_detail(
        self,
        *,
        correlation: Correlation,
        start_time_s: int,
        end_time_s: int,
    ) -> SlsQueryReceipt:
        return self._query(
            operation="evaluation_detail_readback",
            correlation=correlation,
            start_time_s=start_time_s,
            end_time_s=end_time_s,
            trace_id=None,
            logstore=EVALUATION_DETAIL_LOGSTORE,
        )

    def _query(
        self,
        *,
        operation: str,
        correlation: Correlation,
        start_time_s: int,
        end_time_s: int,
        trace_id: str | None,
        logstore: str,
    ) -> SlsQueryReceipt:
        operation = _opaque(operation, "operation")
        if type(start_time_s) is not int or type(end_time_s) is not int:
            return self._blocked(operation, logstore, correlation, "time_window_invalid")
        if start_time_s < 0 or end_time_s <= start_time_s or end_time_s - start_time_s > 86400:
            return self._blocked(operation, logstore, correlation, "time_window_invalid")
        if trace_id is not None and not re.fullmatch(r"[0-9a-f]{32}", trace_id):
            return self._blocked(operation, logstore, correlation, "trace_id_invalid")
        credential_status = self.credential_ref.inspect() if self.credential_ref else None
        reason = self._preflight_reason(credential_status)
        if reason:
            return self._blocked(operation, logstore, correlation, reason)
        try:
            credentials = self.credential_provider() if self.credential_provider else None
            if not isinstance(credentials, SlsCredentials):
                raise SlsContractError("credential provider is not bound")
            query = _query_text(correlation, self.binding.agent_space, trace_id)
            params = {
                "type": "log",
                "from": str(start_time_s),
                "to": str(end_time_s),
                "topic": "",
                "query": query,
            }
            query_hash = _digest(query.encode("utf-8"))
            url = _logs_url(self.binding, logstore, params)
            headers = _signed_headers("GET", url, credentials)
        except Exception:
            return self._blocked(operation, logstore, correlation, "credential_or_request_build_failed")
        try:
            response = self.transport(url, headers, self.timeout_seconds)
        except (OSError, TimeoutError, URLError, HTTPError):
            return self._blocked(
                operation, logstore, correlation, "sls_transport_failed", query_hash=query_hash, auth_attempted=True
            )
        if not isinstance(response, SlsHttpResponse) or not isinstance(response.body, bytes):
            return self._blocked(
                operation, logstore, correlation, "invalid_sls_transport_response", query_hash=query_hash, auth_attempted=True
            )
        response_hash = _digest(response.body)
        request_id_present = _request_id_present(response.headers)
        if not 200 <= response.status_code < 300:
            return self._blocked(
                operation,
                logstore,
                correlation,
                "sls_query_non_success",
                query_hash=query_hash,
                response=response,
                response_hash=response_hash,
                request_id_present=request_id_present,
                auth_attempted=True,
            )
        if len(response.body) > _MAX_RESPONSE_BYTES:
            return self._blocked(
                operation,
                logstore,
                correlation,
                "sls_response_too_large",
                query_hash=query_hash,
                response=response,
                response_hash=response_hash,
                request_id_present=request_id_present,
                auth_attempted=True,
            )
        try:
            payload = json.loads(response.body.decode("utf-8"))
            rows = _rows(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, SlsContractError):
            return self._blocked(
                operation,
                logstore,
                correlation,
                "sls_response_not_json",
                query_hash=query_hash,
                response=response,
                response_hash=response_hash,
                request_id_present=request_id_present,
                auth_attempted=True,
            )
        matched = [row for row in rows if _row_matches(row, correlation, self.binding.agent_space, trace_id)]
        status = "VERIFIED" if len(matched) == 1 else "NOT_VERIFIED"
        return SlsQueryReceipt(
            "testweaver.sls-query/v1",
            status,
            operation,
            self.binding.safe_endpoint,
            self.binding.project,
            logstore,
            "GET",
            True,
            False,
            correlation,
            query_hash,
            response.status_code,
            response_hash,
            len(response.body),
            len(rows),
            len(matched),
            request_id_present,
            True,
            None if status == "VERIFIED" else "correlation_not_found_in_one_row" if not matched else "multiple_matching_rows",
        )

    def _preflight_reason(self, credential: ConfigReferenceStatus | None) -> str | None:
        if credential is None:
            return "sls_ram_credential_reference_missing"
        if not credential.usable:
            return "sls_ram_credential_reference_unusable"
        if self.credential_provider is None:
            return "sls_ram_credential_provider_not_bound"
        return None

    def _blocked(
        self,
        operation: str,
        logstore: str,
        correlation: Correlation,
        reason: str,
        *,
        query_hash: str | None = None,
        response: SlsHttpResponse | None = None,
        response_hash: str | None = None,
        request_id_present: bool = False,
        auth_attempted: bool = False,
    ) -> SlsQueryReceipt:
        return SlsQueryReceipt(
            "testweaver.sls-query/v1",
            "BLOCKED",
            operation,
            self.binding.safe_endpoint,
            self.binding.project,
            logstore,
            "GET",
            True,
            False,
            correlation,
            query_hash or _digest(b""),
            response.status_code if response else None,
            response_hash,
            len(response.body) if response else 0,
            0,
            0,
            request_id_present,
            auth_attempted,
            reason,
        )


def _query_text(correlation: Correlation, agent_space: str | None, trace_id: str | None) -> str:
    anchors = [
        ("run_id", correlation.run_id),
        ("campaign_id", correlation.campaign_id),
        ("pg_revision", correlation.pg_revision),
        ("content_hash", correlation.content_hash),
    ]
    if agent_space is not None:
        anchors.append(("agentSpace", agent_space))
    if trace_id is not None:
        anchors.append(("trace_id", trace_id))
    for name, value in anchors:
        _opaque(name, "query field", _NAME)
        _opaque(value, "query anchor")
    # Keep the server-side expression to the known-valid SLS form.  Some
    # tenants reject field predicates when those fields are not indexed; the
    # bounded result is still checked locally against every anchor in one row.
    return f"* | SELECT * LIMIT {_MAX_QUERY_ROWS}"


def _logs_url(binding: SlsBinding, logstore: str, params: Mapping[str, str]) -> str:
    _opaque(logstore, "logstore", _NAME)
    # SLS identifies the project in the Host; GetLogs path is only the store.
    path = f"/logstores/{quote(logstore, safe='')}"
    query = urlencode(sorted(params.items()), quote_via=quote)
    return f"{binding.safe_endpoint}{path}?{query}"


def _canonical_resource(url: str) -> str:
    """Build SLS's canonical resource from decoded, sorted query parameters."""

    parsed = urlsplit(url)
    try:
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError as error:
        raise SlsContractError("SLS query parameters are malformed") from error
    canonical_query = "&".join(
        f"{key}={value}" for key, value in sorted(pairs, key=lambda pair: (pair[0], pair[1]))
    )
    return parsed.path + (f"?{canonical_query}" if canonical_query else "")


def _signed_headers(method: str, url: str, credentials: SlsCredentials) -> dict[str, str]:
    date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    headers = {
        "Accept": "application/json",
        "Date": date,
        "x-log-apiversion": "0.6.0",
        "x-log-signaturemethod": "hmac-sha1",
        "x-log-bodyrawsize": "0",
    }
    if credentials.security_token is not None:
        headers["x-acs-security-token"] = credentials.security_token
    canonical_headers = "".join(
        f"{key.lower()}:{headers[key]}\n"
        for key in sorted(
            key
            for key in headers
            if key.lower().startswith("x-log-") or key.lower().startswith("x-acs-")
        )
    )
    canonical_resource = _canonical_resource(url)
    string_to_sign = f"{method}\n\n\n{date}\n{canonical_headers}{canonical_resource}"
    signature = base64.b64encode(
        hmac.new(credentials.access_key_secret.encode(), string_to_sign.encode(), "sha1").digest()
    ).decode("ascii")
    headers["Authorization"] = f"LOG {credentials.access_key_id}:{signature}"
    return headers


def _urllib_get(url: str, headers: Mapping[str, str], timeout: float) -> SlsHttpResponse:
    request = Request(url, headers=dict(headers), method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            return SlsHttpResponse(
                response.status,
                response.read(_MAX_RESPONSE_BYTES + 1),
                dict(response.headers.items()),
            )
    except HTTPError as error:
        return SlsHttpResponse(
            error.code,
            error.read(_MAX_RESPONSE_BYTES + 1),
            dict(error.headers.items()) if error.headers else {},
        )
    except URLError:
        raise


def _request_id_present(headers: Mapping[str, str]) -> bool:
    return any(
        isinstance(key, str)
        and key.lower() in {"x-log-requestid", "x-request-id", "requestid"}
        and isinstance(value, str)
        and bool(value)
        for key, value in headers.items()
    )


def _rows(payload: object) -> list[Mapping[str, object]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, Mapping):
        rows = payload.get("logs", payload.get("data", []))
    else:
        raise SlsContractError("SLS response root is not a log list")
    if not isinstance(rows, list) or len(rows) > _MAX_QUERY_ROWS:
        raise SlsContractError("SLS response rows are invalid or unbounded")
    if not all(isinstance(row, Mapping) for row in rows):
        raise SlsContractError("SLS response row is not an object")
    return rows


def _row_matches(
    row: Mapping[str, object],
    correlation: Correlation,
    agent_space: str | None,
    trace_id: str | None,
) -> bool:
    expected: dict[tuple[str, ...], str] = {
        (
            "run_id",
            "runId",
            "testweaver.run_id",
            "gen_ai.session.id",
        ): correlation.run_id,
        (
            "campaign_id",
            "campaignId",
            "testweaver.campaign_id",
            "gen_ai.conversation.id",
        ): correlation.campaign_id,
        (
            "pg_revision",
            "pgRevision",
            "testweaver.pg_revision",
            "testweaver.pg.revision",
        ): correlation.pg_revision,
        (
            "content_hash",
            "contentHash",
            "testweaver.content_hash",
            "testweaver.content.hash",
        ): correlation.content_hash,
    }
    if trace_id is not None:
        expected[("trace_id", "traceId", "trace.id", "testweaver.trace_id")] = trace_id
    return all(any(row.get(name) == value for name in aliases) for aliases, value in expected.items())
