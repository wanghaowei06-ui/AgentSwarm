"""Small strict validator for TestWeaver native data artifacts.

The JSON files under ``schemas/`` are the interchange contract. This module
keeps the focused local check dependency-free and only validates data shape,
references, and the canonical envelope hash. It cannot create, route, or
mutate AgentTeams-native work.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


class ContractError(ValueError):
    """Raised when a native artifact does not satisfy its thin contract."""


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@-]*$")
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_SCHEMA_VERSIONS = {
    "context": "testweaver.context/v1",
    "claim": "testweaver.claim/v1",
    "evidence": "testweaver.evidence/v1",
    "provenance": "testweaver.provenance/v1",
    "handoff": "testweaver.handoff/v1",
}
_CLAIM_TYPES = {"ROOT_CAUSE", "IMPACT", "REPAIR", "ATTACK"}
_EPISTEMIC_STATUSES = {"FACT", "INFERENCE", "UNKNOWN"}
_EVIDENCE_KINDS = {"file", "message", "artifact"}
_TRANSPORT_CHANNELS = {"filesync", "message"}
_COMMON_FIELDS = {
    "schema_version",
    "version",
    "revision",
    "content_hash",
    "native_refs",
    "producer",
    "artifact",
}


def canonical_hash(value: Any) -> str:
    """Return the source-compatible hash of a JSON-compatible value."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def seal(document: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy sealed with the envelope hash used by this contract."""

    payload = dict(document)
    payload.pop("content_hash", None)
    payload["content_hash"] = canonical_hash(payload)
    return payload


def deduplicate_claims(documents: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Keep exact duplicate claims once and reject conflicting replacements."""

    merged: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for document in documents:
        if not isinstance(document, Mapping):
            raise ContractError("claim must be an object")
        validate("claim", document)
        candidate = dict(document)
        claim_id = candidate["claim_id"]
        existing = by_id.get(claim_id)
        if existing is None:
            by_id[claim_id] = candidate
            merged.append(candidate)
        elif existing["content_hash"] != candidate["content_hash"]:
            raise ContractError(
                f"conflicting claim {claim_id}; explicit resolution is required"
            )
    return tuple(merged)


def unique_source_hashes(documents: Iterable[Mapping[str, Any]]) -> tuple[tuple[str, str], ...]:
    """Return stable source/content pairs for read de-duplication only."""

    unique: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for document in documents:
        if not isinstance(document, Mapping):
            raise ContractError("claim must be an object")
        validate("claim", document)
        key = (document["source"], document["evidence_ref"]["content_hash"])
        if key not in seen:
            seen.add(key)
            unique.append(key)
    return tuple(unique)


def schema_path(kind: str) -> Path:
    """Return the checked-in JSON schema path for one artifact kind."""

    if kind not in _SCHEMA_VERSIONS:
        raise ContractError(f"unknown artifact kind: {kind}")
    return Path(__file__).with_name("schemas") / f"{kind}-v1.json"


def load_schema(kind: str) -> dict[str, Any]:
    """Load a checked-in schema for focused contract tests."""

    try:
        value = json.loads(schema_path(kind).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load schema for {kind}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"schema for {kind} must be an object")
    return value


def validate(kind: str, document: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate one artifact and return it unchanged when valid."""

    if kind not in _SCHEMA_VERSIONS:
        raise ContractError(f"unknown artifact kind: {kind}")
    if not isinstance(document, Mapping):
        raise ContractError("artifact must be an object")

    required = set(_COMMON_FIELDS)
    required.add(
        {
            "context": "context_id",
            "claim": "claim_id",
            "evidence": "evidence_id",
            "provenance": "provenance_id",
            "handoff": "handoff_id",
        }[kind]
    )
    if kind == "context":
        required.update(
            {"summary", "claim_refs", "evidence_refs", "provenance_ref", "unresolved_items"}
        )
    elif kind == "claim":
        required.update(
            {"claim", "source", "evidence_ref", "provenance", "confidence", "unresolved_items"}
        )
    elif kind == "evidence":
        required.update({"evidence_type", "evidence_ref", "provenance"})
    elif kind == "provenance":
        required.update({"source_refs", "method"})
    elif kind == "handoff":
        required.update(
            {
                "claim",
                "evidence_ref",
                "provenance",
                "confidence",
                "context_refs",
                "evidence_gaps",
                "unresolved_items",
            }
        )

    unknown = set(document) - required
    missing = required - set(document)
    if unknown:
        raise ContractError(f"unknown fields: {sorted(unknown)}")
    if missing:
        raise ContractError(f"missing fields: {sorted(missing)}")

    _check_common(kind, document)
    if kind == "context":
        _check_context(document)
    elif kind == "claim":
        _check_claim(document)
    elif kind == "evidence":
        _check_evidence(document)
    elif kind == "provenance":
        _check_provenance(document)
    elif kind == "handoff":
        _check_handoff(document)
    return document


def _check_common(kind: str, document: Mapping[str, Any]) -> None:
    if document["schema_version"] != _SCHEMA_VERSIONS[kind]:
        raise ContractError("schema_version does not match artifact kind")
    for field in ("version", "revision"):
        value = document[field]
        if type(value) is not int or value < 1:
            raise ContractError(f"{field} must be a positive integer")
    if not isinstance(document["content_hash"], str) or not _HASH.fullmatch(document["content_hash"]):
        raise ContractError("content_hash must be a sha256 digest")
    payload = {key: value for key, value in document.items() if key != "content_hash"}
    if document["content_hash"] != canonical_hash(payload):
        raise ContractError("content_hash mismatch")
    _check_native_refs(document["native_refs"])
    _check_producer(document["producer"])
    _check_artifact(document["artifact"])


def _check_identifier(value: Any, field: str) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= 200 or not _IDENTIFIER.fullmatch(value):
        raise ContractError(f"{field} must be a TestWeaver identifier")


def _check_reference(value: Any, field: str) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= 2000 or any(char.isspace() for char in value):
        raise ContractError(f"{field} must be a non-empty opaque reference")


def _check_reference_list(value: Any, field: str, *, minimum: int = 0) -> None:
    if not isinstance(value, list) or len(value) < minimum:
        raise ContractError(f"{field} must contain at least {minimum} references")
    for index, reference in enumerate(value):
        _check_reference(reference, f"{field}[{index}]")


def _check_native_refs(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != {"project_id", "task_id", "room_id", "read_only"}:
        raise ContractError("native_refs must contain only read-only project/task/room references")
    for field in ("project_id", "task_id", "room_id"):
        _check_reference(value[field], f"native_refs.{field}")
    if value["read_only"] is not True:
        raise ContractError("native_refs.read_only must be true")


def _check_producer(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != {"identity", "role"}:
        raise ContractError("producer must contain identity and role only")
    _check_reference(value["identity"], "producer.identity")
    _check_identifier(value["role"], "producer.role")


def _check_evidence_ref(value: Any, field: str = "evidence_ref") -> None:
    if not isinstance(value, Mapping) or set(value) != {"id", "kind", "artifact_ref", "content_hash"}:
        raise ContractError(f"{field} has an invalid shape")
    _check_identifier(value["id"], f"{field}.id")
    if value["kind"] not in _EVIDENCE_KINDS:
        raise ContractError(f"{field}.kind is not supported")
    _check_reference(value["artifact_ref"], f"{field}.artifact_ref")
    if not isinstance(value["content_hash"], str) or not _HASH.fullmatch(value["content_hash"]):
        raise ContractError(f"{field}.content_hash must be a sha256 digest")


def _check_provenance_value(value: Any, field: str = "provenance") -> None:
    if not isinstance(value, Mapping) or set(value) != {"source_refs", "method"}:
        raise ContractError(f"{field} has an invalid shape")
    refs = value["source_refs"]
    if not isinstance(refs, list) or not refs:
        raise ContractError(f"{field}.source_refs must be non-empty")
    for index, reference in enumerate(refs):
        _check_reference(reference, f"{field}.source_refs[{index}]")
    if not isinstance(value["method"], str) or not 1 <= len(value["method"]) <= 2000:
        raise ContractError(f"{field}.method must be non-empty")


def _check_artifact(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != {"channel", "artifact_ref"}:
        raise ContractError("artifact has an invalid shape")
    if value["channel"] not in _TRANSPORT_CHANNELS:
        raise ContractError("artifact.channel must use a native TeamHarness channel")
    _check_reference(value["artifact_ref"], "artifact.artifact_ref")


def _check_unresolved(value: Any) -> None:
    if not isinstance(value, list):
        raise ContractError("unresolved_items must be an array")
    for index, item in enumerate(value):
        if not isinstance(item, str) or not 1 <= len(item) <= 2000:
            raise ContractError(f"unresolved_items[{index}] must be non-empty")


def _check_confidence(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ContractError("confidence must be between zero and one")


def _check_claim_body(value: Any, field: str = "claim") -> None:
    if not isinstance(value, Mapping) or set(value) != {"statement", "claim_type", "epistemic_status"}:
        raise ContractError(f"{field} has an invalid shape")
    if not isinstance(value["statement"], str) or not 1 <= len(value["statement"]) <= 4000:
        raise ContractError(f"{field}.statement must be non-empty")
    if value["claim_type"] not in _CLAIM_TYPES:
        raise ContractError(f"{field}.claim_type is not supported")
    if value["epistemic_status"] not in _EPISTEMIC_STATUSES:
        raise ContractError(f"{field}.epistemic_status is not supported")


def _check_context(document: Mapping[str, Any]) -> None:
    _check_identifier(document["context_id"], "context_id")
    if not isinstance(document["summary"], str) or not 1 <= len(document["summary"]) <= 4000:
        raise ContractError("summary must be non-empty")
    for field in ("claim_refs", "provenance_ref"):
        value = document[field]
        if field.endswith("refs"):
            if not isinstance(value, list):
                raise ContractError(f"{field} must be an array")
            for index, reference in enumerate(value):
                _check_reference(reference, f"{field}[{index}]")
        else:
            _check_reference(value, field)
    if not isinstance(document["evidence_refs"], list):
        raise ContractError("evidence_refs must be an array")
    for index, reference in enumerate(document["evidence_refs"]):
        _check_evidence_ref(reference, f"evidence_refs[{index}]")
    _check_unresolved(document["unresolved_items"])


def _check_claim(document: Mapping[str, Any]) -> None:
    _check_identifier(document["claim_id"], "claim_id")
    _check_reference(document["source"], "source")
    _check_claim_body(document["claim"])
    _check_evidence_ref(document["evidence_ref"])
    _check_provenance_value(document["provenance"])
    _check_confidence(document["confidence"])
    _check_unresolved(document["unresolved_items"])


def _check_evidence(document: Mapping[str, Any]) -> None:
    _check_identifier(document["evidence_id"], "evidence_id")
    _check_identifier(document["evidence_type"], "evidence_type")
    _check_evidence_ref(document["evidence_ref"])
    _check_provenance_value(document["provenance"])


def _check_provenance_artifact(document: Mapping[str, Any]) -> None:
    _check_identifier(document["provenance_id"], "provenance_id")
    refs = document["source_refs"]
    if not isinstance(refs, list) or not refs:
        raise ContractError("source_refs must be non-empty")
    for index, reference in enumerate(refs):
        _check_reference(reference, f"source_refs[{index}]")
    if not isinstance(document["method"], str) or not 1 <= len(document["method"]) <= 2000:
        raise ContractError("method must be non-empty")


def _check_provenance(document: Mapping[str, Any]) -> None:
    _check_provenance_artifact(document)


def _check_handoff(document: Mapping[str, Any]) -> None:
    _check_identifier(document["handoff_id"], "handoff_id")
    _check_claim_body(document["claim"])
    _check_evidence_ref(document["evidence_ref"])
    _check_provenance_value(document["provenance"])
    _check_confidence(document["confidence"])
    _check_reference_list(document["context_refs"], "context_refs", minimum=1)
    _check_unresolved(document["evidence_gaps"])
    _check_unresolved(document["unresolved_items"])
