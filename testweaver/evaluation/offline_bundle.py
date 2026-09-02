"""Deterministic, allowlist-only offline acceptance bundles."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from testweaver.contracts.validator import canonical_hash


SCHEMA_VERSION = "testweaver.m4.offline-bundle/v1"
MANIFEST_NAME = "bundle-manifest.json"
ALLOWED_CLASSIFICATIONS = frozenset(
    {"ATTESTED_EXTERNAL_EXPORT", "PARTIAL", "FAIL", "BLOCKED", "NOT_OBSERVED", "NOT_AVAILABLE"}
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


class BundleError(ValueError):
    """Raised when a bundle or its inputs violate the offline contract."""


def _safe_name(name: str) -> str:
    if not isinstance(name, str) or not name or "\\" in name:
        raise BundleError("invalid bundle path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise BundleError("unsafe bundle path")
    return name


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_ref(data: bytes) -> str:
    return f"sha256:{_digest(data)}"


def _opaque(value: Any, field: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 2000 or any(char.isspace() for char in value):
        raise BundleError(f"{field} must be a non-empty opaque reference")
    return value


def _validate_attestation(
    value: Any,
    files: Mapping[str, Path] | None = None,
    *,
    archive_files: Mapping[str, bytes] | None = None,
) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != _ATTESTATION_FIELDS:
        raise BundleError("raw-source attestation has unsupported or missing fields")
    if value["source_kind"] != _SOURCE_KIND:
        raise BundleError("raw-source attestation is not an external native export")
    source_ref = _opaque(value["source_ref"], "raw-source source_ref")
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
        manifest_bytes = Path(files[manifest_ref]).read_bytes()
    elif archive_files is not None:
        if manifest_ref not in archive_files:
            raise BundleError("raw-source manifest_ref is missing from the archive")
        manifest_bytes = archive_files[manifest_ref]
    else:
        raise BundleError("raw-source attestation requires an archive manifest association")
    if manifest_hash != _hash_ref(manifest_bytes):
        raise BundleError("raw-source manifest_hash does not match the associated manifest")
    return {
        "source_ref": source_ref,
        "source_hash": source_hash,
        "attestation_ref": attestation_ref,
        "attestation_hash": attestation_hash,
        "source_kind": _SOURCE_KIND,
        "manifest_ref": manifest_ref,
        "manifest_hash": manifest_hash,
    }


def build_bundle(
    output: Path,
    files: Mapping[str, Path],
    *,
    classification: str,
    source_commit: str,
    raw_source_attestation: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a reproducible zip from an explicit allowlist only."""
    if classification not in ALLOWED_CLASSIFICATIONS:
        raise BundleError("offline bundle classification is unsupported or LIVE")
    if not source_commit or not isinstance(source_commit, str) or source_commit.split() != [source_commit]:
        raise BundleError("source commit is required")
    if MANIFEST_NAME in files:
        raise BundleError("reserved bundle manifest path")

    payload: dict[str, bytes] = {}
    for name, path in files.items():
        safe = _safe_name(name)
        source = Path(path)
        if source.is_symlink() or not source.is_file():
            raise BundleError(f"input is not a regular file: {name}")
        payload[safe] = source.read_bytes()

    attestation = _validate_attestation(raw_source_attestation, files=files)

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
    manifest_bytes = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()

    output = Path(output)
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
    }


def verify_bundle(
    bundle: Path, *, expected_files: Iterable[str], expected_source_commit: str
) -> dict[str, Any]:
    """Verify an offline bundle without extracting or discovering files."""
    expected = sorted(_safe_name(name) for name in expected_files)
    if len(expected) != len(set(expected)):
        raise BundleError("duplicate expected path")
    with zipfile.ZipFile(bundle) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)) or any(_safe_name(name) != name for name in names):
            raise BundleError("invalid or duplicate archive path")
        for info in infos:
            if ((info.external_attr >> 16) & 0o170000) == 0o120000:
                raise BundleError("symbolic links are not allowed")
        if MANIFEST_NAME not in names or sorted(n for n in names if n != MANIFEST_NAME) != expected:
            raise BundleError("archive does not match allowlist")
        try:
            manifest = json.loads(archive.read(MANIFEST_NAME))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BundleError("invalid bundle manifest") from exc
        if manifest.get("schema") != SCHEMA_VERSION or manifest.get("source_commit") != expected_source_commit:
            raise BundleError("manifest identity mismatch")
        if manifest.get("classification") not in ALLOWED_CLASSIFICATIONS:
            raise BundleError("manifest classification is unsupported or LIVE")
        entries = manifest.get("files")
        if not isinstance(entries, list) or [entry.get("path") for entry in entries] != expected:
            raise BundleError("manifest file list mismatch")
        for entry in entries:
            name = entry.get("path")
            data = archive.read(name)
            if entry.get("sha256") != _digest(data) or entry.get("size") != len(data):
                raise BundleError(f"hash mismatch: {name}")
        _validate_attestation(
            manifest.get("raw_source_attestation"),
            archive_files={name: archive.read(name) for name in names if name != MANIFEST_NAME},
        )
    return {
        "classification": manifest["classification"],
        "source_commit": manifest["source_commit"],
        "files": expected,
        "bundle_sha256": _digest(Path(bundle).read_bytes()),
    }
