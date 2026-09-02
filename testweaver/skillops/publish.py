"""Pure references for publishing a Skill through AgentTeams native packages.

The AgentTeams controller/runtime owns Nacos access, AgentSpec installation, and
rollback.  This module only turns an already-approved Skill proposal into a
hash-bound intent and validates the names-only readback supplied by that native
path; it never performs network, filesystem, Matrix, or task operations.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from .nacos import NacosCandidateReadback
from .state import ExternalReadback


class NativePackageError(ValueError):
    """Raised when an AgentTeams native package reference is not safe."""


_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_ACTIONS = frozenset({"CANARY", "PROMOTE", "ROLLBACK"})
_REF = re.compile(r"^\S{1,2048}$")


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise NativePackageError(f"{field} must be a sha256 digest")
    return value


def _ref(value: object, field: str) -> str:
    if not isinstance(value, str) or not _REF.fullmatch(value):
        raise NativePackageError(f"{field} must be a bounded reference")
    return value


def _package_uri(value: object) -> str:
    if not isinstance(value, str) or not _REF.fullmatch(value):
        raise NativePackageError("package_uri must be a bounded nacos reference")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "nacos"
        or not parsed.netloc
        or not parsed.path
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise NativePackageError("package_uri must be a credential-free nacos URI")
    return value


@dataclass(frozen=True, slots=True)
class NativePackageRef:
    """An immutable AgentSpec package reference already tied to a proposal."""

    package_uri: str
    version: str
    content_hash: str
    rollback_ref: str

    def __post_init__(self) -> None:
        _package_uri(self.package_uri)
        if not isinstance(self.version, str) or not _VERSION.fullmatch(self.version):
            raise NativePackageError("version must be semantic version")
        _hash(self.content_hash, "content_hash")
        _ref(self.rollback_ref, "rollback_ref")


def build_native_publish_intent(
    candidate: NativePackageRef,
    *,
    action: str,
) -> dict[str, str]:
    """Build data for the existing native publisher; do not send it here."""

    if not isinstance(candidate, NativePackageRef):
        raise NativePackageError("candidate must be a NativePackageRef")
    if action not in _ACTIONS:
        raise NativePackageError("publish action is unsupported")
    return {
        "schema_version": "testweaver.native-package-intent/v1",
        "action": action,
        "package_uri": candidate.package_uri,
        "version": candidate.version,
        "content_hash": candidate.content_hash,
        "rollback_ref": candidate.rollback_ref,
    }


def verify_native_package_readback(
    candidate: NativePackageRef,
    *,
    action: str,
    readback: Mapping[str, object],
    readback_token: ExternalReadback | None = None,
) -> dict[str, str]:
    """Verify selected fields from a native AgentSpec/package readback."""

    intent = build_native_publish_intent(candidate, action=action)
    if action != "CANARY":
        raise NativePackageError(
            "PROMOTE/ROLLBACK require an exact operation receipt via verify_close"
        )
    if not isinstance(readback, Mapping):
        raise NativePackageError("native package readback must be an object")
    if readback_token is None or not readback_token.verified:
        raise NativePackageError("native package readback requires an external token")
    if readback_token.source != "nacos":
        raise NativePackageError("native package readback token source is invalid")
    if readback_token.classification != "NATIVE_TRANSPORT":
        raise NativePackageError("native package readback is UNATTESTED_PARTIAL")
    required = ("package_uri", "version", "content_hash", "readback_ref")
    if any(field not in readback for field in required):
        raise NativePackageError("native package readback is incomplete")
    values = {
        "schema_version": "testweaver.native-package-readback/v1",
        "action": action,
        "package_uri": _package_uri(readback["package_uri"]),
        "version": readback["version"],
        "content_hash": _hash(readback["content_hash"], "readback.content_hash"),
        "readback_ref": _ref(readback["readback_ref"], "readback_ref"),
        "rollback_ref": candidate.rollback_ref,
    }
    if readback_token.ref != values["readback_ref"]:
        raise NativePackageError("native package readback token does not match readback")
    if values["package_uri"] != intent["package_uri"] or values["version"] != intent["version"] or values["content_hash"] != intent["content_hash"]:
        raise NativePackageError("native package readback does not match candidate")
    if (
        readback_token.claim("version") != candidate.version
        or readback_token.claim("content_hash") != candidate.content_hash
    ):
        raise NativePackageError("native transport receipt does not match candidate")
    sealed = dict(values)
    sealed["record_hash"] = "sha256:" + hashlib.sha256(
        json.dumps(sealed, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return sealed


def verify_nacos_candidate_readback(
    candidate: NativePackageRef,
    *,
    skill_name: str,
    readback: NacosCandidateReadback,
    expected_endpoint: str,
    expected_namespace: str,
) -> dict[str, str]:
    """Reconcile an attested native Nacos publish with the candidate tuple."""

    if not isinstance(candidate, NativePackageRef):
        raise NativePackageError("candidate must be a NativePackageRef")
    if not isinstance(readback, NacosCandidateReadback) or not readback.verified:
        raise NativePackageError("candidate publish requires native Nacos provenance")
    parsed_endpoint = urlsplit(expected_endpoint)
    if (
        parsed_endpoint.scheme not in {"http", "https"}
        or not parsed_endpoint.netloc
        or parsed_endpoint.username is not None
        or parsed_endpoint.password is not None
        or parsed_endpoint.query
        or parsed_endpoint.fragment
    ):
        raise NativePackageError("expected Nacos endpoint is invalid")
    endpoint = expected_endpoint.rstrip("/")
    namespace = _ref(expected_namespace, "expected_namespace")
    name = _ref(skill_name, "skill_name")
    package_path = [part for part in urlsplit(candidate.package_uri).path.split("/") if part]
    if not package_path or package_path[0] != namespace:
        raise NativePackageError("candidate package URI crosses the Nacos namespace")
    expected = {
        "endpoint": endpoint,
        "namespace_id": namespace,
        "skill_name": name,
        "version": candidate.version,
        "content_hash": candidate.content_hash,
    }
    observed = {
        "endpoint": readback.endpoint,
        "namespace_id": readback.namespace_id,
        "skill_name": readback.skill_name,
        "version": readback.version,
        "content_hash": readback.registry_package_hash,
    }
    if observed != expected or any(
        readback.token.claim(key) != value for key, value in expected.items()
    ):
        raise NativePackageError("native Nacos readback does not match candidate")
    if (
        readback.token.claim("admin_response_hash") != readback.admin_response_hash
        or readback.token.claim("registry_status") != readback.registry_status
        or readback.registry_status not in {"online", "published"}
    ):
        raise NativePackageError("native Nacos governance readback is not publish-complete")
    sealed = {
        "schema_version": "testweaver.nacos-candidate-verification/v1",
        **expected,
        "registry_status": readback.registry_status,
        "admin_response_hash": readback.admin_response_hash,
        "readback_ref": readback.readback_ref,
        "classification": "LIVE_ATTESTED",
    }
    sealed["record_hash"] = "sha256:" + hashlib.sha256(
        json.dumps(sealed, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return sealed
