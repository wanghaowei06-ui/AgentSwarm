"""Deterministic, allowlist-only offline acceptance bundles.

The builder verifies the bytes behind an explicit source path before recording
their hash.  It never creates a LIVE classification; a caller request for a
Hero without an externally sealed native proof is recorded as ``PARTIAL``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from testweaver.contracts.validator import canonical_hash


SCHEMA_VERSION = "testweaver.m4.offline-bundle/v1"
MANIFEST_NAME = "bundle-manifest.json"
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


def build_bundle(
    output: Path,
    files: Mapping[str, Path],
    *,
    classification: str,
    source_commit: str,
    raw_source_attestation: Mapping[str, Any],
    authority_tuple: Mapping[str, object] | None = None,
    raw_source_path: Path | None = None,
) -> dict[str, Any]:
    """Build a reproducible zip from an explicit allowlist only."""
    requested_classification = classification
    if classification == "LIVE_AGENTTEAMS_HERO":
        # A caller cannot self-seal a Hero.  Until an external sealed proof is
        # supplied by the native receipt owner this remains an ordinary
        # PARTIAL offline package.
        classification = "PARTIAL"
    if classification not in ALLOWED_CLASSIFICATIONS:
        raise BundleError("offline bundle classification is unsupported")
    if authority_tuple is not None and requested_classification != "LIVE_AGENTTEAMS_HERO":
        raise BundleError("authority tuple is only valid for a sealed Hero")
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
    if requested_classification == "LIVE_AGENTTEAMS_HERO":
        manifest["downgraded_from"] = requested_classification
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
        if classification not in ALLOWED_CLASSIFICATIONS:
            raise BundleError("manifest classification is unsupported")
        if "authority_tuple" in manifest:
            raise BundleError("non-LIVE bundle cannot carry an authority tuple")
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
    result = {
        "classification": classification,
        "source_commit": manifest["source_commit"],
        "files": expected,
        "bundle_sha256": _digest(bundle.read_bytes()),
    }
    return result
