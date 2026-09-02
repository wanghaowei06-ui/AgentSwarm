"""Small Nacos v3 data-plane client used by the native Skill package seam.

The AgentTeams controller remains the owner of package installation and
runtime state.  This module only implements the already supported Nacos v3
HTTP publish/download/readback calls.  It does not start a server, inspect a
container, schedule work, or provide a second Skill runtime.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .state import ExternalReadback, _external_readback


NACOS_CONTAINER = "tw-g8-nacos"
NACOS_BASE_URL = "http://127.0.0.1:58848/nacos"
NACOS_NAMESPACE = "testweaver-g8-canary"
NACOS_GROUP = "TESTWEAVER_SKILLOPS"
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_REF = re.compile(r"^\S{1,2048}$")


class NacosRegistryError(RuntimeError):
    """Raised when Nacos violates the v3 publication/readback contract."""


class NacosNotFound(NacosRegistryError):
    """Raised when a requested Nacos resource is absent."""


@dataclass(frozen=True, repr=False)
class NacosHttpResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)


NacosTransport = Callable[
    [str, str, Mapping[str, str], bytes | None, float], NacosHttpResponse
]


@dataclass(frozen=True, repr=False)
class NacosCandidateReadback:
    """Hash-only proof issued by the client's native HTTP transport path."""

    endpoint: str
    namespace_id: str
    skill_name: str
    version: str
    registry_package_hash: str
    registry_status: str
    admin_response_hash: str
    readback_ref: str
    token: ExternalReadback = field(repr=False)

    @property
    def verified(self) -> bool:
        return (
            self.token.verified
            and self.token.classification == "NATIVE_TRANSPORT"
            and self.token.source == "nacos"
            and self.token.ref == self.readback_ref
            and self.token.raw_hash == self.registry_package_hash
        )


def _digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _text(value: object, field: str, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not _REF.fullmatch(value):
        raise NacosRegistryError(f"{field} is invalid")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise NacosRegistryError(f"{field} is invalid")
    return value


def _description(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise NacosRegistryError("description is invalid")
    if any(ord(character) < 0x20 for character in value):
        raise NacosRegistryError("description is invalid")
    return value


def _base_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise NacosRegistryError("Nacos base URL must be credential-free HTTP(S)")
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _response_json(body: bytes) -> dict[str, Any]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NacosRegistryError("Nacos returned a non-JSON control response") from error
    if not isinstance(value, dict):
        raise NacosRegistryError("Nacos control response is not an object")
    code = value.get("code")
    if code in {20004, 22001, 30000}:
        raise NacosNotFound("Nacos resource was not found")
    if code != 0:
        raise NacosRegistryError("Nacos control request failed")
    return value


def _multipart(
    fields: Mapping[str, str], *, filename: str, file_value: bytes
) -> tuple[bytes, str]:
    boundary = "testweaver-nacos-v3-boundary"
    chunks: list[bytes] = []
    for name, value in sorted(fields.items()):
        chunks.extend(
            (
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            )
        )
    chunks.extend(
        (
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            b"Content-Type: application/zip\r\n\r\n",
            file_value,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        )
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _urllib_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes | None,
    timeout: float,
) -> NacosHttpResponse:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return NacosHttpResponse(
                response.status,
                response.read(),
                {key.lower(): value for key, value in response.headers.items()},
            )
    except urllib.error.HTTPError as error:
        return NacosHttpResponse(
            error.code,
            error.read(),
            {key.lower(): value for key, value in error.headers.items()}
            if error.headers
            else {},
        )
    except urllib.error.URLError as error:
        raise NacosRegistryError("Nacos transport failed") from error


class NacosV3Client:
    """Call only the Nacos v3 Skill/config data-plane endpoints."""

    def __init__(
        self,
        base_url: str = NACOS_BASE_URL,
        *,
        namespace: str = NACOS_NAMESPACE,
        group: str = NACOS_GROUP,
        transport: NacosTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 60:
            raise NacosRegistryError("timeout_seconds is outside the bounded range")
        self.base_url = _base_url(base_url)
        self.namespace = _text(namespace, "namespace")
        self.group = _text(group, "group")
        self.transport = transport or _urllib_transport
        self._native_transport = transport is None
        self.timeout_seconds = timeout_seconds

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> NacosHttpResponse:
        if not path.startswith("/") or "?" in path or "#" in path:
            raise NacosRegistryError("Nacos path is invalid")
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(sorted(query.items()))}"
        headers = {
            "User-Agent": "TestWeaver-SkillOps/1.0",
            "Client-Version": "TestWeaver/0.1.0",
        }
        if content_type is not None:
            headers["Content-Type"] = content_type
        try:
            response = self.transport(
                method, url, headers, body, self.timeout_seconds
            )
        except NacosRegistryError:
            raise
        except (OSError, TimeoutError) as error:
            raise NacosRegistryError("Nacos transport failed") from error
        if not isinstance(response, NacosHttpResponse) or not isinstance(response.body, bytes):
            raise NacosRegistryError("Nacos transport response is invalid")
        if not 200 <= response.status_code < 300:
            try:
                _response_json(response.body)
            except NacosNotFound:
                raise
            except NacosRegistryError as error:
                raise NacosRegistryError(
                    f"Nacos HTTP request failed ({response.status_code})"
                ) from error
            raise NacosRegistryError(f"Nacos HTTP request failed ({response.status_code})")
        return response

    def _json_request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        form: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        body = None
        content_type = None
        if form is not None:
            body = urllib.parse.urlencode(sorted(form.items())).encode("utf-8")
            content_type = "application/x-www-form-urlencoded"
        response = self._request(
            method, path, query=query, body=body, content_type=content_type
        )
        return _response_json(response.body)

    def download_skill(self, name: str, version: str) -> bytes:
        """Download one exact Skill ZIP from the v3 client endpoint."""

        name = _text(name, "skill name", _NAME)
        version = _text(version, "skill version", _VERSION)
        response = self._request(
            "GET",
            "/v3/client/ai/skills",
            query={"namespaceId": self.namespace, "name": name, "version": version},
        )
        content_type = response.headers.get("content-type", "")
        if "json" in content_type or response.body.startswith(b"{"):
            _response_json(response.body)
            raise NacosRegistryError("Nacos Skill endpoint returned JSON instead of ZIP")
        return response.body

    def read_skill(self, name: str, version: str) -> dict[str, Any]:
        """Read the admin version record for one exact Skill."""

        name = _text(name, "skill name", _NAME)
        version = _text(version, "skill version", _VERSION)
        response = self._request(
            "GET",
            "/v3/admin/ai/skills",
            query={"namespaceId": self.namespace, "skillName": name},
        )
        data = _response_json(response.body).get("data")
        if not isinstance(data, Mapping):
            raise NacosRegistryError("Nacos Skill readback is malformed")
        versions = data.get("versions")
        if not isinstance(versions, list):
            raise NacosRegistryError("Nacos Skill readback has no versions")
        for item in versions:
            if isinstance(item, Mapping) and item.get("version") == version:
                return {
                    "skill_name": name,
                    "version": version,
                    "registry_status": item.get("status", "unknown"),
                    "scope": data.get("scope"),
                    "admin_response_hash": _digest(response.body),
                }
        raise NacosNotFound("Nacos Skill version was not found")

    def publish_skill(
        self,
        *,
        name: str,
        version: str,
        zip_bytes: bytes,
        package_hash: str,
    ) -> dict[str, Any]:
        """Publish one ZIP through v3 upload/submit/publish and read it back."""

        name = _text(name, "skill name", _NAME)
        version = _text(version, "skill version", _VERSION)
        if not isinstance(zip_bytes, bytes) or not zip_bytes:
            raise NacosRegistryError("Skill ZIP bytes are required")
        if not isinstance(package_hash, str) or not _HASH.fullmatch(package_hash):
            raise NacosRegistryError("package_hash is invalid")
        if package_hash != _digest(zip_bytes):
            raise NacosRegistryError("package_hash does not match ZIP bytes")
        multipart, content_type = _multipart(
            {
                "namespaceId": self.namespace,
                "overwrite": "false",
                "skillName": name,
                "version": version,
                "commitMsg": "TestWeaver SkillOps native package",
            },
            filename=f"{name}-{version}.zip",
            file_value=zip_bytes,
        )
        _response_json(
            self._request(
                "POST",
                "/v3/admin/ai/skills/upload",
                body=multipart,
                content_type=content_type,
            ).body
        )
        self._json_request(
            "POST",
            "/v3/admin/ai/skills/submit",
            form={"namespaceId": self.namespace, "skillName": name, "version": version},
        )
        last_publish_error: NacosRegistryError | None = None
        for attempt in range(20):
            try:
                self._json_request(
                    "POST",
                    "/v3/admin/ai/skills/publish",
                    form={
                        "namespaceId": self.namespace,
                        "skillName": name,
                        "version": version,
                        "updateLatestLabel": "false",
                    },
                )
                break
            except NacosRegistryError as error:
                last_publish_error = error
                if attempt == 19:
                    raise
                time.sleep(0.25)
        else:  # pragma: no cover - the loop either breaks or raises above
            if last_publish_error is not None:
                raise last_publish_error
        downloaded = self.download_skill(name, version)
        registry_hash = _digest(downloaded)
        governance = self.read_skill(name, version)
        return {
            "schema_version": "testweaver.nacos-skill-readback/v1",
            "endpoint": self.base_url,
            "namespace_id": self.namespace,
            "skill_name": name,
            "version": version,
            "local_package_hash": package_hash,
            "registry_package_hash": registry_hash,
            "exact_version_readback": registry_hash == package_hash,
            "classification": (
                "NATIVE_TRANSPORT"
                if self._native_transport and self.transport is _urllib_transport
                else "UNATTESTED_PARTIAL"
            ),
            **governance,
        }

    def publish_skill_exact(
        self,
        *,
        name: str,
        version: str,
        zip_bytes: bytes,
        package_hash: str,
        expected_endpoint: str,
        expected_namespace: str,
    ) -> NacosCandidateReadback:
        """Publish/read back through native HTTP and bind protected provenance."""

        endpoint = _base_url(expected_endpoint)
        namespace = _text(expected_namespace, "expected_namespace")
        if endpoint != self.base_url or namespace != self.namespace:
            raise NacosRegistryError("protected Nacos endpoint/namespace mismatch")
        if not self._native_transport or self.transport is not _urllib_transport:
            raise NacosRegistryError(
                "injected Nacos transcripts are UNATTESTED_PARTIAL"
            )
        result = self.publish_skill(
            name=name,
            version=version,
            zip_bytes=zip_bytes,
            package_hash=package_hash,
        )
        if (
            result.get("classification") != "NATIVE_TRANSPORT"
            or result.get("exact_version_readback") is not True
            or result.get("registry_package_hash") != package_hash
            or result.get("version") != version
            or result.get("namespace_id") != namespace
            or result.get("endpoint") != endpoint
            or result.get("registry_status") not in {"online", "published"}
        ):
            raise NacosRegistryError("Nacos candidate exact readback failed")
        downloaded = self.download_skill(name, version)
        if _digest(downloaded) != package_hash:
            raise NacosRegistryError("final Nacos package readback changed after publish")
        readback_ref = f"nacos:{endpoint}#{namespace}/{name}@{version}"
        token = _external_readback(
            source="nacos",
            ref=readback_ref,
            raw=downloaded,
            classification="NATIVE_TRANSPORT",
            claims=tuple(
                sorted(
                    {
                        "endpoint": endpoint,
                        "namespace_id": namespace,
                        "skill_name": name,
                        "version": version,
                        "content_hash": package_hash,
                        "admin_response_hash": str(result["admin_response_hash"]),
                        "registry_status": str(result["registry_status"]),
                    }.items()
                )
            ),
            verified=True,
        )
        return NacosCandidateReadback(
            endpoint=endpoint,
            namespace_id=namespace,
            skill_name=name,
            version=version,
            registry_package_hash=package_hash,
            registry_status=str(result["registry_status"]),
            admin_response_hash=str(result["admin_response_hash"]),
            readback_ref=readback_ref,
            token=token,
        )

    def read_config(self, data_id: str, *, group: str | None = None) -> tuple[str, str]:
        """Read one config content/md5 pair through the v3 client endpoint."""

        data_id = _text(data_id, "data_id", _NAME)
        group_name = _text(group or self.group, "group")
        data = self._json_request(
            "GET",
            "/v3/client/cs/config",
            query={
                "namespaceId": self.namespace,
                "groupName": group_name,
                "dataId": data_id,
            },
        ).get("data")
        if not isinstance(data, Mapping) or data.get("success") is not True:
            raise NacosNotFound("Nacos config was not found")
        content = data.get("content")
        md5 = data.get("md5")
        if not isinstance(content, str) or not isinstance(md5, str) or not _REF.fullmatch(md5):
            raise NacosRegistryError("Nacos config readback is malformed")
        return content, md5

    def publish_config(
        self,
        *,
        data_id: str,
        content: str,
        description: str,
        group: str | None = None,
    ) -> dict[str, Any]:
        """Publish one versioned config then perform exact client readback."""

        data_id = _text(data_id, "data_id", _NAME)
        description = _description(description)
        if not isinstance(content, str) or not content or "\x00" in content:
            raise NacosRegistryError("config content is invalid")
        group_name = _text(group or self.group, "group")
        result = self._json_request(
            "POST",
            "/v3/admin/cs/config",
            form={
                "namespaceId": self.namespace,
                "groupName": group_name,
                "dataId": data_id,
                "content": content,
                "type": "json",
                "appName": "testweaver-skillops",
                "desc": description,
            },
        )
        if result.get("data") is not True:
            raise NacosRegistryError("Nacos config publish was not acknowledged")
        read_content, md5 = self.read_config(data_id, group=group_name)
        return {
            "schema_version": "testweaver.nacos-config-readback/v1",
            "namespace_id": self.namespace,
            "group_name": group_name,
            "data_id": data_id,
            "content_md5": md5,
            "exact_content_readback": read_content == content,
        }


# Keep the old import name as a thin data-plane compatibility alias.  It no
# longer accepts a repository root or owns any container/runtime lifecycle.
NacosRegistry = NacosV3Client
NacosClient = NacosV3Client
