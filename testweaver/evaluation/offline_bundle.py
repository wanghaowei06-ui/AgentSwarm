"""Deterministic, allowlist-only offline acceptance bundles.

The builder verifies the bytes behind an explicit source path before recording
their hash.  It never creates a LIVE classification; a caller request for a
Hero without an externally sealed native proof is recorded as ``PARTIAL``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from testweaver.contracts.validator import canonical_hash


SCHEMA_VERSION = "testweaver.m4.offline-bundle/v1"
MANIFEST_NAME = "bundle-manifest.json"
LIVE_CLASSIFICATION = "LIVE_AGENTTEAMS_HERO"
SEALED_AUTHORITY_SCHEMA = "testweaver.m4.external-sealed-authority/v1"
_SEALED_SOURCE_KIND = "agentteams-native-sealed-authority"
ALLOWED_CLASSIFICATIONS = frozenset(
    {
        "ATTESTED_EXTERNAL_EXPORT",
        "PARTIAL",
        "FAIL",
        "BLOCKED",
        "NOT_OBSERVED",
        "NOT_AVAILABLE",
    }
)
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_SOURCE_KIND = "agentteams-native-export"
_ATTESTATION_FIELDS = frozenset(
    {
        "source_ref",
        "source_hash",
        "attestation_ref",
        "attestation_hash",
        "source_kind",
        "manifest_ref",
        "manifest_hash",
    }
)
# ``source_ref`` is an allowlisted archive member name, not a free-form URI.
# The caller supplies its absolute path separately at build time.
_MAX_MEMBER_BYTES = 8 * 1024 * 1024
_MAX_TOTAL_BYTES = 32 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 1000
_AUTHORITY_TUPLE_FIELDS = ("campaign_id", "run_id", "trace_id", "pg_revision")
_PROOF_COMPONENTS = (
    "matrix_hitl_readback",
    "dsh_skill",
    "recovery",
    "agentloop_readback",
)
_PROOF_COMPONENT_ALIASES = {
    "matrix_hitl_readback": ("matrix_hitl_readback", "hitl_readback", "hitl"),
    "dsh_skill": ("dsh_skill", "dsh_skill_readback", "skill_readback"),
    "recovery": ("recovery", "recovery_readback"),
    "agentloop_readback": (
        "agentloop_readback",
        "agent_loop_readback",
        "agentloop",
    ),
}
_PROOF_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "proof_id",
        *_AUTHORITY_TUPLE_FIELDS,
        "evidence_root_ref",
        "evidence_root_hash",
        *_PROOF_COMPONENTS,
        "oracles",
        "sealed_source",
    }
)
_PROOF_HASH_FIELDS = frozenset({"content_hash", "proof_hash"})
_PROOF_COMPONENT_ALIAS_FIELDS = frozenset(
    alias for aliases in _PROOF_COMPONENT_ALIASES.values() for alias in aliases
)


class BundleError(ValueError):
    """Raised when a bundle or its inputs violate the offline contract."""


def _safe_name(name: str) -> str:
    if (
        not isinstance(name, str)
        or not name
        or name.endswith("/")
        or "\\" in name
        or "//" in name
        or any(ord(character) < 0x20 for character in name)
    ):
        raise BundleError("invalid bundle path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise BundleError("unsafe bundle path")
    return name


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_ref(data: bytes) -> str:
    return f"sha256:{_digest(data)}"


def _read_regular_file(path: Path, *, max_bytes: int = _MAX_MEMBER_BYTES) -> bytes:
    """Read a bounded regular file without following a symlink or FIFO."""

    if not path.is_absolute():
        raise BundleError("raw source path must be absolute")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise BundleError("raw source must be a regular file")
        if metadata.st_size < 0 or metadata.st_size > max_bytes:
            raise BundleError("raw source exceeds the size limit")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = None
            data = stream.read(max_bytes + 1)
    except BundleError:
        raise
    except (OSError, ValueError) as error:
        raise BundleError("raw source is unavailable") from error
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
    if len(data) > max_bytes:
        raise BundleError("raw source exceeds the size limit")
    return data


def _opaque(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 2000
        or any(char.isspace() or ord(char) < 0x20 for char in value)
    ):
        raise BundleError(f"{field} must be a non-empty opaque reference")
    return value


def _validate_attestation(
    value: Any,
    files: Mapping[str, Path] | None = None,
    *,
    archive_files: Mapping[str, bytes] | None = None,
    raw_source_path: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _ATTESTATION_FIELDS:
        raise BundleError("raw-source attestation has unsupported or missing fields")
    if value["source_kind"] != _SOURCE_KIND:
        raise BundleError("raw-source attestation is not an external native export")
    source_ref = _safe_name(value["source_ref"])
    attestation_ref = _opaque(value["attestation_ref"], "raw-source attestation_ref")
    source_hash = value["source_hash"]
    attestation_hash = value["attestation_hash"]
    if not isinstance(source_hash, str) or not _HASH.fullmatch(source_hash):
        raise BundleError("raw-source source_hash must be a sha256 digest")
    if not isinstance(attestation_hash, str) or not _HASH.fullmatch(attestation_hash):
        raise BundleError("raw-source attestation_hash must be a sha256 digest")
    expected_attestation_hash = canonical_hash(
        {key: child for key, child in value.items() if key != "attestation_hash"}
    )
    if attestation_hash != expected_attestation_hash:
        raise BundleError("raw-source attestation_hash mismatch")
    manifest_ref = _safe_name(value["manifest_ref"])
    manifest_hash = value["manifest_hash"]
    if not isinstance(manifest_hash, str) or not _HASH.fullmatch(manifest_hash):
        raise BundleError("raw-source manifest_hash must be a sha256 digest")
    if files is not None and archive_files is not None:
        raise BundleError("raw-source attestation received two manifest sources")
    if files is not None:
        if manifest_ref not in files:
            raise BundleError("raw-source manifest_ref is outside the allowlist")
        manifest_bytes = _read_regular_file(Path(files[manifest_ref]))
        if raw_source_path is None:
            raise BundleError("raw-source path is required")
        source_path = Path(raw_source_path)
        source_bytes = _read_regular_file(source_path)
        if not source_bytes:
            raise BundleError("raw-source bytes are empty")
        try:
            matches = [
                name
                for name, candidate in files.items()
                if Path(candidate).resolve() == source_path.resolve()
            ]
        except OSError as error:
            raise BundleError("raw-source path is unavailable") from error
        if matches != [source_ref]:
            raise BundleError("raw-source path is outside the allowlist")
        if source_hash != _hash_ref(source_bytes):
            raise BundleError("raw-source source_hash does not match source bytes")
    elif archive_files is not None:
        if manifest_ref not in archive_files:
            raise BundleError("raw-source manifest_ref is missing from the archive")
        manifest_bytes = archive_files[manifest_ref]
        if source_ref not in archive_files:
            raise BundleError("raw-source source_ref is missing from the archive")
        if not archive_files[source_ref]:
            raise BundleError("raw-source bytes are empty")
        if source_hash != _hash_ref(archive_files[source_ref]):
            raise BundleError("raw-source source_hash does not match source bytes")
    else:
        raise BundleError("raw-source attestation requires an archive manifest association")
    if manifest_hash != _hash_ref(manifest_bytes):
        raise BundleError("raw-source manifest_hash does not match the associated manifest")
    result: dict[str, Any] = {
        "source_ref": source_ref,
        "source_hash": source_hash,
        "attestation_ref": attestation_ref,
        "attestation_hash": attestation_hash,
        "source_kind": _SOURCE_KIND,
        "manifest_ref": manifest_ref,
        "manifest_hash": manifest_hash,
    }
    return result


def verify_external_sealed_proof(
    proof: Mapping[str, Any],
    *,
    expected_authority_tuple: Mapping[str, object] | None = None,
    bundle_files: Mapping[str, Path | bytes] | None = None,
    raw_source_attestation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify an externally supplied, hash-bound Hero authority proof.

    This is a pure read-only check.  It does not trust a classification field,
    an ``attested`` boolean, or a caller-supplied authority tuple.  Every
    required fact has to carry the same authority tuple and a sealed content
    hash; the sealed source must also resolve to the bytes in ``bundle_files``
    when a bundle is being verified.
    """

    if not isinstance(proof, Mapping):
        raise BundleError("external authority proof must be an object")
    _reject_untrusted_proof_markers(proof)
    allowed = _PROOF_REQUIRED_FIELDS | _PROOF_HASH_FIELDS | _PROOF_COMPONENT_ALIAS_FIELDS
    missing = {
        name
        for name in _PROOF_REQUIRED_FIELDS
        if name not in _PROOF_COMPONENTS
        and name not in proof
    }
    missing.update(
        name
        for name in _PROOF_COMPONENTS
        if not any(alias in proof for alias in _PROOF_COMPONENT_ALIASES[name])
    )
    if missing:
        raise BundleError(f"external authority proof is missing fields: {sorted(missing)}")
    unknown = set(proof) - allowed
    if unknown:
        raise BundleError(f"external authority proof has unknown fields: {sorted(unknown)}")
    hash_fields = _PROOF_HASH_FIELDS.intersection(proof)
    if len(hash_fields) != 1:
        raise BundleError("external authority proof requires one content hash")
    proof_hash_field = next(iter(hash_fields))
    proof_hash = proof[proof_hash_field]
    _validate_hash_ref(proof_hash, "external authority proof content_hash")
    expected_proof_hash = canonical_hash(
        {key: value for key, value in proof.items() if key != proof_hash_field}
    )
    if proof_hash != expected_proof_hash:
        raise BundleError("external authority proof content_hash mismatch")

    if proof.get("schema_version") != SEALED_AUTHORITY_SCHEMA:
        raise BundleError("external authority proof schema is unsupported")
    proof_id = _opaque(proof.get("proof_id"), "proof_id")
    authority_tuple = _validate_authority_tuple(proof)
    if expected_authority_tuple is not None:
        for field in _AUTHORITY_TUPLE_FIELDS:
            if field in expected_authority_tuple and expected_authority_tuple[field] != authority_tuple[field]:
                raise BundleError(f"external authority proof {field} mismatch")
    evidence_root_ref = _opaque(proof.get("evidence_root_ref"), "evidence_root_ref")
    evidence_root_hash = _validate_hash_ref(
        proof.get("evidence_root_hash"), "evidence_root_hash"
    )

    sealed_source = _validate_sealed_source(
        proof["sealed_source"],
        bundle_files=bundle_files,
        raw_source_attestation=raw_source_attestation,
    )
    components: dict[str, dict[str, Any]] = {}
    for name in _PROOF_COMPONENTS:
        component = _component_value(proof, name)
        components[name] = _validate_proof_component(
            component,
            name=name,
            authority_tuple=authority_tuple,
            source_hash=sealed_source["source_hash"],
        )
    outcome, boundary = _validate_proof_oracles(
        proof["oracles"],
        authority_tuple=authority_tuple,
        evidence_root_ref=evidence_root_ref,
        evidence_root_hash=evidence_root_hash,
        source_hash=sealed_source["source_hash"],
    )
    source_verified = bundle_files is not None
    return {
        "classification": LIVE_CLASSIFICATION if source_verified else "NOT_VERIFIED",
        "verification_status": "VERIFIED" if source_verified else "NOT_VERIFIED",
        "proof_id": proof_id,
        "proof_hash": proof_hash,
        "authority_tuple": authority_tuple,
        "evidence_root_ref": evidence_root_ref,
        "evidence_root_hash": evidence_root_hash,
        "verified_components": [*components, "outcome_oracle", "boundary_oracle"],
        "oracle_identities": [outcome["identity_ref"], boundary["identity_ref"]],
        "sealed_source": sealed_source,
    }


def verify_sealed_authority_proof(
    proof: Mapping[str, Any],
    *,
    expected_authority_tuple: Mapping[str, object] | None = None,
    bundle_files: Mapping[str, Path | bytes] | None = None,
    raw_source_attestation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility spelling for the external proof verifier."""

    return verify_external_sealed_proof(
        proof,
        expected_authority_tuple=expected_authority_tuple,
        bundle_files=bundle_files,
        raw_source_attestation=raw_source_attestation,
    )


verify_external_authority_proof = verify_external_sealed_proof


def _validate_authority_tuple(value: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for field in _AUTHORITY_TUPLE_FIELDS:
        result[field] = _opaque(value.get(field), field)
    return result


def _component_value(proof: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    present = [key for key in _PROOF_COMPONENT_ALIASES[name] if key in proof]
    if len(present) != 1:
        raise BundleError(f"external authority proof requires one {name} component")
    value = proof[present[0]]
    if not isinstance(value, Mapping):
        raise BundleError(f"external authority proof {name} must be an object")
    return value


def _validate_proof_component(
    value: Mapping[str, Any],
    *,
    name: str,
    authority_tuple: Mapping[str, str],
    source_hash: str,
    allow_gold_ref: bool = False,
) -> dict[str, Any]:
    _reject_private_proof_fields(value, allow_gold_ref=allow_gold_ref)
    required = {
        "status",
        "ref",
        "source_ref",
        "source_hash",
        "content_hash",
        *_AUTHORITY_TUPLE_FIELDS,
    }
    missing = required - set(value)
    if missing:
        raise BundleError(f"external authority proof {name} is missing fields: {sorted(missing)}")
    status = value["status"]
    if status not in {"VERIFIED", "PASS", "ACCEPTED"}:
        raise BundleError(f"external authority proof {name} is not verified")
    for field in _AUTHORITY_TUPLE_FIELDS:
        if value[field] != authority_tuple[field]:
            raise BundleError(f"external authority proof {name} {field} mismatch")
    _opaque(value["ref"], f"{name}.ref")
    _opaque(value["source_ref"], f"{name}.source_ref")
    if _validate_hash_ref(value["source_hash"], f"{name}.source_hash") != source_hash:
        raise BundleError(f"external authority proof {name} source_hash mismatch")
    content_hash = _validate_hash_ref(value["content_hash"], f"{name}.content_hash")
    expected_hash = canonical_hash(
        {key: child for key, child in value.items() if key != "content_hash"}
    )
    if content_hash != expected_hash:
        raise BundleError(f"external authority proof {name} content_hash mismatch")
    return dict(value)


def _validate_proof_oracles(
    value: Any,
    *,
    authority_tuple: Mapping[str, str],
    evidence_root_ref: str,
    evidence_root_hash: str,
    source_hash: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if isinstance(value, Mapping):
        if set(value) != {"outcome", "boundary"}:
            raise BundleError("external authority proof oracle pair is malformed")
        values = [value["outcome"], value["boundary"]]
    elif isinstance(value, list):
        values = value
    else:
        raise BundleError("external authority proof oracles must be a pair")
    if len(values) != 2 or not all(isinstance(item, Mapping) for item in values):
        raise BundleError("external authority proof requires exactly two Oracles")

    validated: list[dict[str, Any]] = []
    for index, item in enumerate(values):
        if not isinstance(item, Mapping):
            raise BundleError(f"oracle[{index}] must be an object")
        oracle_kind = item.get("oracle_kind")
        _reject_private_proof_fields(item, allow_gold_ref=oracle_kind == "outcome")
        oracle = _validate_proof_component(
            item,
            name=f"oracle[{index}]",
            authority_tuple=authority_tuple,
            source_hash=source_hash,
            allow_gold_ref=oracle_kind == "outcome",
        )
        for field in (
            "oracle_kind",
            "identity_ref",
            "process_ref",
            "result_ref",
            "result_hash",
            "evidence_root_ref",
            "evidence_root_hash",
        ):
            if field not in item:
                raise BundleError(f"oracle[{index}] is missing {field}")
        if item["oracle_kind"] not in {"outcome", "boundary"}:
            raise BundleError("oracle kind is unsupported")
        if item["evidence_root_ref"] != evidence_root_ref or item["evidence_root_hash"] != evidence_root_hash:
            raise BundleError("Oracle evidence root does not match proof")
        for field in ("identity_ref", "process_ref", "result_ref"):
            _opaque(item[field], f"oracle[{index}].{field}")
        _validate_hash_ref(item["result_hash"], f"oracle[{index}].result_hash")
        if item.get("read_result_refs"):
            raise BundleError("Oracle may not reference another Oracle result")
        if item["oracle_kind"] == "boundary":
            if "gold_ref" not in item or item["gold_ref"] is not None:
                raise BundleError("Boundary Oracle gold_ref must be null")
        elif item.get("gold_ref") is not None:
            _opaque(item["gold_ref"], "outcome.gold_ref")
        validated.append(oracle)

    kinds = {item["oracle_kind"] for item in validated}
    if kinds != {"outcome", "boundary"}:
        raise BundleError("oracle pair must contain Outcome and Boundary")
    outcome = next(item for item in validated if item["oracle_kind"] == "outcome")
    boundary = next(item for item in validated if item["oracle_kind"] == "boundary")
    for field in ("identity_ref", "process_ref", "result_ref", "result_hash"):
        if outcome[field] == boundary[field]:
            raise BundleError(f"Oracle {field} values must be distinct")
    return outcome, boundary


def _validate_sealed_source(
    value: Any,
    *,
    bundle_files: Mapping[str, Path | bytes] | None,
    raw_source_attestation: Mapping[str, Any] | None,
) -> dict[str, str]:
    fields = {
        "source_ref",
        "source_hash",
        "manifest_ref",
        "manifest_hash",
        "seal_ref",
        "seal_hash",
        "source_kind",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise BundleError("sealed authority source has unsupported or missing fields")
    if value["source_kind"] != _SEALED_SOURCE_KIND:
        raise BundleError("sealed authority source is not external")
    source_ref = _safe_name(value["source_ref"])
    manifest_ref = _safe_name(value["manifest_ref"])
    source_hash = _validate_hash_ref(value["source_hash"], "sealed_source.source_hash")
    manifest_hash = _validate_hash_ref(value["manifest_hash"], "sealed_source.manifest_hash")
    _opaque(value["seal_ref"], "sealed_source.seal_ref")
    seal_hash = _validate_hash_ref(value["seal_hash"], "sealed_source.seal_hash")
    expected_seal_hash = canonical_hash(
        {key: child for key, child in value.items() if key != "seal_hash"}
    )
    if seal_hash != expected_seal_hash:
        raise BundleError("sealed authority source seal_hash mismatch")
    if raw_source_attestation is not None:
        if (
            raw_source_attestation.get("source_ref") != source_ref
            or raw_source_attestation.get("source_hash") != source_hash
            or raw_source_attestation.get("manifest_ref") != manifest_ref
            or raw_source_attestation.get("manifest_hash") != manifest_hash
        ):
            raise BundleError("sealed source does not match raw-source attestation")
    if bundle_files is not None:
        source_bytes = _bundle_bytes(bundle_files, source_ref)
        manifest_bytes = _bundle_bytes(bundle_files, manifest_ref)
        if not source_bytes:
            raise BundleError("sealed authority source bytes are empty")
        if _hash_ref(source_bytes) != source_hash:
            raise BundleError("sealed authority source_hash does not match source bytes")
        if _hash_ref(manifest_bytes) != manifest_hash:
            raise BundleError("sealed authority manifest_hash does not match bytes")
    return {
        "source_ref": source_ref,
        "source_hash": source_hash,
        "manifest_ref": manifest_ref,
        "manifest_hash": manifest_hash,
        "seal_ref": value["seal_ref"],
        "seal_hash": seal_hash,
        "source_kind": _SEALED_SOURCE_KIND,
    }


def _bundle_bytes(value: Mapping[str, Path | bytes], name: str) -> bytes:
    if name not in value:
        raise BundleError(f"sealed authority source file is missing: {name}")
    child = value[name]
    if isinstance(child, bytes):
        if len(child) > _MAX_MEMBER_BYTES:
            raise BundleError("sealed authority source exceeds the size limit")
        return child
    try:
        return _read_regular_file(Path(child))
    except BundleError as error:
        raise BundleError("sealed authority source file is unavailable") from error


def _validate_hash_ref(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise BundleError(f"{field} must be a sha256 digest")
    return value


def _reject_untrusted_proof_markers(value: Any, path: str = "proof") -> None:
    if isinstance(value, Mapping):
        forbidden = {
            key
            for key in value
            if isinstance(key, str)
            and key.lower() in {"attested", "self_attested", "caller_classification", "fixture", "synthetic", "mock", "replay"}
        }
        if forbidden:
            raise BundleError(f"external authority proof contains untrusted fields at {path}")
        for key, child in value.items():
            if isinstance(key, str) and key.lower() in {"source_kind", "provenance"}:
                if isinstance(child, str) and child.lower() in {"fixture", "synthetic", "mock", "replay"}:
                    raise BundleError(f"external authority proof contains untrusted values at {path}.{key}")
            _reject_untrusted_proof_markers(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_untrusted_proof_markers(child, f"{path}[{index}]")


def _reject_private_proof_fields(value: Mapping[str, Any], *, allow_gold_ref: bool = False) -> None:
    private = {
        "gold",
        "gold_id",
        "gold_boundary",
        "hidden_gold",
        "gold_suite_hash",
        "expected_intent",
    }
    for key, child in value.items():
        if not isinstance(key, str):
            raise BundleError("external authority proof field names must be strings")
        lowered = key.lower()
        if lowered in private or (
            lowered == "gold_ref" and not allow_gold_ref and child is not None
        ):
            raise BundleError(f"external authority proof contains private Gold field: {key}")
        if isinstance(child, Mapping):
            _reject_private_proof_fields(child, allow_gold_ref=allow_gold_ref)
        elif isinstance(child, list):
            for item in child:
                if isinstance(item, Mapping):
                    _reject_private_proof_fields(item, allow_gold_ref=allow_gold_ref)


def build_bundle(
    output: Path,
    files: Mapping[str, Path],
    *,
    classification: str,
    source_commit: str,
    raw_source_attestation: Mapping[str, Any],
    authority_tuple: Mapping[str, object] | None = None,
    raw_source_path: Path | None = None,
    external_authority_proof: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a reproducible zip from an explicit allowlist only."""
    requested_classification = classification
    if classification == LIVE_CLASSIFICATION and external_authority_proof is None:
        # A caller cannot self-seal a Hero.  Until an external sealed proof is
        # supplied by the native receipt owner this remains an ordinary
        # PARTIAL offline package.
        classification = "PARTIAL"
    if classification != LIVE_CLASSIFICATION and classification not in ALLOWED_CLASSIFICATIONS:
        raise BundleError("offline bundle classification is unsupported")
    if authority_tuple is not None and requested_classification != LIVE_CLASSIFICATION:
        raise BundleError("authority tuple is only valid for a sealed Hero")
    if external_authority_proof is not None and requested_classification != LIVE_CLASSIFICATION:
        raise BundleError("external authority proof is only valid for a sealed Hero")
    if not source_commit or not isinstance(source_commit, str) or source_commit.split() != [source_commit]:
        raise BundleError("source commit is required")
    if MANIFEST_NAME in files:
        raise BundleError("reserved bundle manifest path")

    payload: dict[str, bytes] = {}
    for name, path in files.items():
        safe = _safe_name(name)
        source = Path(path)
        try:
            payload[safe] = _read_regular_file(source)
        except BundleError as error:
            raise BundleError(f"input is not a regular file: {name}") from error
    if sum(len(data) for data in payload.values()) > _MAX_TOTAL_BYTES:
        raise BundleError("bundle exceeds the total size limit")

    attestation = _validate_attestation(
        raw_source_attestation,
        files=files,
        raw_source_path=raw_source_path,
    )
    sealed_proof: dict[str, Any] | None = None
    if requested_classification == LIVE_CLASSIFICATION and external_authority_proof is not None:
        sealed_proof = verify_external_sealed_proof(
            external_authority_proof,
            expected_authority_tuple=authority_tuple,
            bundle_files=files,
            raw_source_attestation=attestation,
        )

    entries = [
        {"path": name, "sha256": _digest(data), "size": len(data)}
        for name, data in sorted(payload.items())
    ]
    manifest = {
        "schema": SCHEMA_VERSION,
        "classification": classification,
        "source_commit": source_commit,
        "raw_source_attestation": attestation,
        "files": entries,
    }
    if requested_classification == LIVE_CLASSIFICATION:
        if sealed_proof is None:
            manifest["downgraded_from"] = requested_classification
        else:
            manifest["external_sealed_authority"] = external_authority_proof
    manifest_bytes = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()

    output = Path(output)
    if output.exists() and output.is_symlink():
        raise BundleError("bundle output cannot be a symbolic link")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(payload.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
        info = zipfile.ZipInfo(MANIFEST_NAME, date_time=(1980, 1, 1, 0, 0, 0))
        info.create_system = 3
        info.external_attr = 0o100644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, manifest_bytes)
    return {
        "classification": classification,
        "source_commit": source_commit,
        "files": sorted(payload),
        "bundle_sha256": _digest(output.read_bytes()),
        **(
            {
                "proof_id": sealed_proof["proof_id"],
                "proof_hash": sealed_proof["proof_hash"],
            }
            if sealed_proof is not None
            else {}
        ),
    }


def verify_bundle(
    bundle: Path,
    *,
    expected_files: Iterable[str],
    expected_source_commit: str,
    expected_authority_tuple: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Verify an offline bundle without extracting or discovering files."""
    bundle = Path(bundle)
    if bundle.is_symlink() or not bundle.is_file():
        raise BundleError("bundle must be a regular file")
    expected = sorted(_safe_name(name) for name in expected_files)
    if len(expected) != len(set(expected)):
        raise BundleError("duplicate expected path")
    with zipfile.ZipFile(bundle) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)) or any(_safe_name(name) != name for name in names):
            raise BundleError("invalid or duplicate archive path")
        total_size = 0
        for info in infos:
            if info.file_size > _MAX_MEMBER_BYTES:
                raise BundleError("archive member exceeds the size limit")
            total_size += info.file_size
            if total_size > _MAX_TOTAL_BYTES:
                raise BundleError("archive exceeds the total size limit")
            if info.file_size and info.compress_size == 0:
                raise BundleError("archive member has invalid compression metadata")
            if info.file_size > _MAX_COMPRESSION_RATIO * max(1, info.compress_size):
                raise BundleError("archive member compression ratio is excessive")
            if ((info.external_attr >> 16) & 0o170000) == 0o120000:
                raise BundleError("symbolic links are not allowed")
        if MANIFEST_NAME not in names or sorted(n for n in names if n != MANIFEST_NAME) != expected:
            raise BundleError("archive does not match allowlist")
        try:
            manifest = json.loads(archive.read(MANIFEST_NAME))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BundleError("invalid bundle manifest") from exc
        if not isinstance(manifest, Mapping):
            raise BundleError("bundle manifest is not an object")
        if manifest.get("schema") != SCHEMA_VERSION or manifest.get("source_commit") != expected_source_commit:
            raise BundleError("manifest identity mismatch")
        classification = manifest.get("classification")
        if classification != LIVE_CLASSIFICATION and classification not in ALLOWED_CLASSIFICATIONS:
            raise BundleError("manifest classification is unsupported")
        if "authority_tuple" in manifest:
            raise BundleError("bundle cannot carry an unsealed authority tuple")
        entries = manifest.get("files")
        if not isinstance(entries, list) or [entry.get("path") for entry in entries] != expected:
            raise BundleError("manifest file list mismatch")
        for entry in entries:
            name = entry.get("path")
            data = archive.read(name)
            if entry.get("sha256") != _digest(data) or entry.get("size") != len(data):
                raise BundleError(f"hash mismatch: {name}")
        archive_files = {name: archive.read(name) for name in names}
        attestation = _validate_attestation(
            manifest.get("raw_source_attestation"),
            archive_files=archive_files,
        )
        proof = manifest.get("external_sealed_authority")
        if classification == LIVE_CLASSIFICATION:
            if not isinstance(proof, Mapping):
                raise BundleError("LIVE bundle requires an external sealed authority proof")
            verified_proof = verify_external_sealed_proof(
                proof,
                expected_authority_tuple=expected_authority_tuple,
                bundle_files=archive_files,
                raw_source_attestation=attestation,
            )
        else:
            if proof is not None:
                raise BundleError("non-LIVE bundle cannot carry an external authority proof")
            verified_proof = None
    result = {
        "classification": classification,
        "source_commit": manifest["source_commit"],
        "files": expected,
        "bundle_sha256": _digest(bundle.read_bytes()),
    }
    if verified_proof is not None:
        result.update(
            {
                "proof_id": verified_proof["proof_id"],
                "proof_hash": verified_proof["proof_hash"],
                "authority_tuple": verified_proof["authority_tuple"],
            }
        )
    return result


def _load_json_file(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(_read_regular_file(Path(path)))
    except (BundleError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise BundleError("JSON input is unavailable or invalid") from error
    if not isinstance(value, Mapping):
        raise BundleError("JSON input must be an object")
    return value


def _cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m testweaver.evaluation.offline_bundle",
        description="Read-only offline bundle verification",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("verify", "replay"):
        subparser = commands.add_parser(command)
        subparser.add_argument("bundle", type=Path)
        subparser.add_argument("--expected-file", action="append", dest="expected_files", required=True)
        subparser.add_argument("--source-commit", required=True)
        subparser.add_argument("--authority-tuple", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Verify or deterministically replay a local bundle without side effects."""

    args = _cli_parser().parse_args(argv)
    try:
        expected_tuple = None
        if args.authority_tuple is not None:
            expected_tuple = _load_json_file(args.authority_tuple)
        result = verify_bundle(
            args.bundle,
            expected_files=args.expected_files,
            expected_source_commit=args.source_commit,
            expected_authority_tuple=expected_tuple,
        )
        if args.command == "replay":
            replay = verify_bundle(
                args.bundle,
                expected_files=args.expected_files,
                expected_source_commit=args.source_commit,
                expected_authority_tuple=expected_tuple,
            )
            result = {
                **result,
                "replay_equal": result["classification"] == replay["classification"]
                and result["bundle_sha256"] == replay["bundle_sha256"],
                "replay_hash": canonical_hash(replay),
            }
            if not result["replay_equal"]:
                raise BundleError("bundle replay is not deterministic")
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (BundleError, OSError, ValueError) as error:
        print(f"offline bundle verification failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ALLOWED_CLASSIFICATIONS",
    "BundleError",
    "LIVE_CLASSIFICATION",
    "MANIFEST_NAME",
    "SCHEMA_VERSION",
    "SEALED_AUTHORITY_SCHEMA",
    "build_bundle",
    "main",
    "verify_bundle",
    "verify_external_authority_proof",
    "verify_external_sealed_proof",
    "verify_sealed_authority_proof",
]
