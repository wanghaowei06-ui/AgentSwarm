"""Deterministic, allowlist-only offline acceptance bundles."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "testweaver.m4.offline-bundle/v1"
MANIFEST_NAME = "bundle-manifest.json"


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


def build_bundle(
    output: Path, files: Mapping[str, Path], *, classification: str, source_commit: str
) -> dict[str, Any]:
    """Build a reproducible zip from an explicit allowlist only."""
    if not classification or not isinstance(classification, str):
        raise BundleError("classification is required")
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

    entries = [
        {"path": name, "sha256": _digest(data), "size": len(data)}
        for name, data in sorted(payload.items())
    ]
    manifest = {
        "schema": SCHEMA_VERSION,
        "classification": classification,
        "source_commit": source_commit,
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
        if not isinstance(manifest.get("classification"), str) or not manifest["classification"]:
            raise BundleError("manifest classification missing")
        entries = manifest.get("files")
        if not isinstance(entries, list) or [entry.get("path") for entry in entries] != expected:
            raise BundleError("manifest file list mismatch")
        for entry in entries:
            name = entry.get("path")
            data = archive.read(name)
            if entry.get("sha256") != _digest(data) or entry.get("size") != len(data):
                raise BundleError(f"hash mismatch: {name}")
    return {
        "classification": manifest["classification"],
        "source_commit": manifest["source_commit"],
        "files": expected,
        "bundle_sha256": _digest(Path(bundle).read_bytes()),
    }
