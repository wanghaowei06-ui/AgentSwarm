#!/usr/bin/env python3
"""Build and replay a read-only bundle from a completed native Hero capture."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from testweaver.authority import AuthorityError, OracleResult, validate_oracle_pair
from testweaver.contracts.validator import canonical_hash
from testweaver.evaluation.offline_bundle import (
    BundleError,
    build_bundle,
    verify_bundle,
)


SCHEMA = "testweaver.hero-evidence-bundle/v1"
CAPTURE_SCHEMA = "testweaver.native-hero-capture.v1"
RECEIPT_SCHEMA = "testweaver/m2b/m2b-receipt.schema.json"
SOURCE_PREFIX = "source/"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCOPE_FIELDS = ("campaign_id", "run_id", "trace_id")
_OBSERVATION_STATUSES = frozenset({"OBSERVED", "PARTIAL", "NOT_OBSERVED", "BLOCKED"})
_NEGATIVE_STATUSES = frozenset({"NOT_OBSERVED", "NOT_AVAILABLE"})
_BLOCKED_STATUSES = frozenset({"BLOCKED", "NOT_VERIFIED", "INVALID", "ERROR"})
_PARTIAL_STATUSES = frozenset({"PARTIAL"})
_MAX_JSON_BYTES = 8 * 1024 * 1024

_FACT_DIRECTORIES = {
    "hitl": "facts/hitl",
    "recovery": "facts/recovery",
    "oracle_outcome": "facts/oracles/outcome.json",
    "oracle_boundary": "facts/oracles/boundary.json",
    "otel": "facts/otel",
    "agentloop": "facts/agentloop",
}
_REQUIRED_CATEGORIES = (
    "matrix_exact",
    "agentteams_task",
    "provider_facts",
    "pg_events",
    "hitl",
    "recovery",
    "oracle_outcome",
    "oracle_boundary",
    "skill",
    "otel",
    "agentloop",
)


class HeroBundleError(ValueError):
    """The source capture or bundle does not satisfy the offline contract."""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _safe_relative(value: str, *, field: str = "path") -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise HeroBundleError(f"unsafe {field}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise HeroBundleError(f"unsafe {field}")
    return value


def _read_bytes(path: Path, *, label: str, max_bytes: int | None = None) -> bytes:
    try:
        if path.is_symlink() or not path.is_file():
            raise HeroBundleError(f"{label} must be a regular file")
        if max_bytes is not None and path.stat().st_size > max_bytes:
            raise HeroBundleError(f"{label} exceeds the size limit")
        data = path.read_bytes()
    except HeroBundleError:
        raise
    except OSError as error:
        raise HeroBundleError(f"{label} is unavailable") from error
    if max_bytes is not None and len(data) > max_bytes:
        raise HeroBundleError(f"{label} exceeds the size limit")
    return data


def _load_json_bytes(data: bytes, *, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HeroBundleError(f"{label} is not valid JSON") from error
    if not isinstance(value, Mapping):
        raise HeroBundleError(f"{label} must be a JSON object")
    return value


def _load_json(path: Path, *, label: str) -> Mapping[str, Any]:
    return _load_json_bytes(_read_bytes(path, label=label, max_bytes=_MAX_JSON_BYTES), label=label)


def _source_path(root: Path, relative: str) -> Path:
    relative = _safe_relative(relative)
    candidate = root
    for part in PurePosixPath(relative).parts:
        candidate /= part
        if candidate.is_symlink():
            raise HeroBundleError("source path contains a symbolic link")
    try:
        candidate.resolve(strict=False).relative_to(root.resolve())
    except (OSError, ValueError) as error:
        raise HeroBundleError("source path escapes the evidence directory") from error
    return candidate


def _parse_source_sums(root: Path) -> tuple[dict[str, str], bytes]:
    sums_path = root / "SHA256SUMS"
    raw = _read_bytes(sums_path, label="source SHA256SUMS", max_bytes=_MAX_JSON_BYTES)
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise HeroBundleError("source SHA256SUMS is not UTF-8") from error
    checksums: dict[str, str] = {}
    for number, line in enumerate(lines, 1):
        if not line:
            continue
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as error:
            raise HeroBundleError(f"invalid source checksum line {number}") from error
        if relative.startswith("./"):
            relative = relative[2:]
        relative = _safe_relative(relative, field="checksum path")
        if not _SHA256.fullmatch(digest) or relative in checksums:
            raise HeroBundleError(f"invalid source checksum line {number}")
        checksums[relative] = digest
    if not checksums:
        raise HeroBundleError("source checksum manifest is empty")
    for relative, expected in sorted(checksums.items()):
        path = _source_path(root, relative)
        actual = hashlib.sha256()
        try:
            if path.is_symlink() or not path.is_file():
                raise HeroBundleError(f"source checksum target is not a regular file: {relative}")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    actual.update(chunk)
        except HeroBundleError:
            raise
        except OSError as error:
            raise HeroBundleError(f"source checksum target is unavailable: {relative}") from error
        if actual.hexdigest() != expected:
            raise HeroBundleError(f"source checksum mismatch: {relative}")
    return checksums, raw


def _capture_identity(root: Path) -> tuple[Mapping[str, Any], dict[str, str], str]:
    manifest = _load_json(root / "manifest.json", label="capture manifest")
    if manifest.get("schema") != CAPTURE_SCHEMA:
        raise HeroBundleError("capture manifest schema is unsupported")
    if manifest.get("status") != "STOPPED" or manifest.get("checksum_state") != "FINAL":
        raise HeroBundleError("Hero capture is not completed with STOPPED/FINAL state")
    scope = manifest.get("authority_scope")
    if not isinstance(scope, Mapping) or any(
        not isinstance(scope.get(field), str) or not scope[field] for field in _SCOPE_FIELDS
    ):
        raise HeroBundleError("capture authority scope is incomplete")
    authority = {field: str(scope[field]) for field in _SCOPE_FIELDS}
    latest = _safe_relative(manifest.get("latest_snapshot"), field="latest_snapshot")
    snapshot = _source_path(root, latest)
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise HeroBundleError("latest snapshot is unavailable")
    snapshot_manifest = _load_json(snapshot / "snapshot-manifest.json", label="snapshot manifest")
    if snapshot_manifest.get("schema") != CAPTURE_SCHEMA:
        raise HeroBundleError("snapshot manifest schema is unsupported")
    if snapshot_manifest.get("snapshot_ref") != latest:
        raise HeroBundleError("snapshot manifest reference mismatch")
    if not _scope_matches(snapshot_manifest, authority):
        raise HeroBundleError("snapshot manifest authority scope mismatch")
    return manifest, authority, latest


def _files_below(root: Path, relative: str) -> list[str]:
    base = _source_path(root, relative)
    if not base.exists():
        return []
    if base.is_symlink():
        raise HeroBundleError(f"allowlisted source is a symbolic link: {relative}")
    if base.is_file():
        return [relative]
    if not base.is_dir():
        raise HeroBundleError(f"allowlisted source is not a directory: {relative}")
    result: list[str] = []
    for path in sorted(base.rglob("*")):
        if path.is_symlink():
            raise HeroBundleError(f"allowlisted source is a symbolic link: {path.relative_to(root)}")
        if path.is_file():
            result.append(path.relative_to(root).as_posix())
    return result


def _select_files(root: Path, latest: str) -> dict[str, list[str]]:
    matrix = [
        path
        for path in _files_below(root, f"{latest}/matrix")
        if path.endswith("/event-index.jsonl") or "/events/" in path
    ]
    task_candidates = (
        f"{latest}/authority/projects.json",
        f"{latest}/authority/projects.json.raw.sha256",
        f"{latest}/authority/tasks.json",
        f"{latest}/authority/tasks.json.raw.sha256",
        f"{latest}/shared-fs/task-artifacts.jsonl",
        f"{latest}/shared-fs/task-metadata.jsonl",
    )
    provider = [f"{latest}/manager-choice-readback.json"]
    provider.extend(_files_below(root, f"{latest}/sessions"))
    skill = _files_below(root, f"{latest}/skills")
    # The capture stores the exact, body-free invocation ledger beside the
    # snapshot's skill inventory. Include it in the allowlist so a sealed
    # offline bundle can prove an actual runtime invocation rather than only
    # proving that a skill was installed.
    invocation = f"{latest}/skill-invocations.jsonl"
    if _source_path(root, invocation).is_file():
        skill.append(invocation)
    selected = {
        "matrix_exact": matrix,
        "agentteams_task": [item for item in task_candidates if _source_path(root, item).is_file()],
        "provider_facts": sorted(set(item for item in provider if _source_path(root, item).is_file())),
        "pg_events": [
            item
            for item in (f"{latest}/pg-tw-row-hashes.jsonl",)
            if _source_path(root, item).is_file()
        ],
        "skill": skill,
    }
    for category, relative in _FACT_DIRECTORIES.items():
        selected[category] = _files_below(root, relative)
    return {name: sorted(set(paths)) for name, paths in selected.items()}


def _json_records(data: bytes, *, label: str) -> list[Any]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HeroBundleError(f"{label} is not UTF-8") from error
    if label.endswith(".jsonl"):
        values: list[Any] = []
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                values.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise HeroBundleError(f"{label} has invalid JSON at line {number}") from error
        return values
    try:
        return [json.loads(text)]
    except json.JSONDecodeError as error:
        raise HeroBundleError(f"{label} is not valid JSON") from error


def _statuses(values: Iterable[Any]) -> set[str]:
    found: set[str] = set()
    for value in values:
        if isinstance(value, Mapping):
            status = value.get("status")
            if isinstance(status, str):
                found.add(status.upper())
            found.update(_statuses(value.values()))
        elif isinstance(value, list):
            found.update(_statuses(value))
    return found


def _scope_matches(value: Any, authority: Mapping[str, str]) -> bool:
    if not isinstance(value, Mapping):
        return True
    candidates = [value]
    child = value.get("authority_scope")
    if isinstance(child, Mapping):
        candidates.append(child)
    for candidate in candidates:
        present = [field for field in _SCOPE_FIELDS if field in candidate]
        if present and (len(present) != len(_SCOPE_FIELDS) or any(candidate[field] != authority[field] for field in present)):
            return False
    return True


def _has_complete_scope(value: Any, authority: Mapping[str, str]) -> bool:
    if not isinstance(value, Mapping):
        return False
    candidates = [value]
    child = value.get("authority_scope")
    if isinstance(child, Mapping):
        candidates.append(child)
    return any(all(candidate.get(field) == authority[field] for field in _SCOPE_FIELDS) for candidate in candidates)


def _ordinary_observation(
    root: Path,
    paths: list[str],
    authority: Mapping[str, str],
    *,
    require_scope: bool = False,
) -> dict[str, Any]:
    refs = [SOURCE_PREFIX + path for path in paths]
    if not paths:
        return {"status": "NOT_OBSERVED", "refs": [], "reason": "allowlisted evidence is absent"}
    statuses: set[str] = set()
    has_record = False
    scope_ok = True
    scoped_record = False
    for relative in paths:
        if not relative.endswith((".json", ".jsonl")):
            if _read_bytes(_source_path(root, relative), label=relative):
                has_record = True
            continue
        values = _json_records(_read_bytes(_source_path(root, relative), label=relative), label=relative)
        statuses.update(_statuses(values))
        has_record = has_record or bool(values)
        scope_ok = scope_ok and all(_scope_matches(value, authority) for value in values)
        scoped_record = scoped_record or any(_has_complete_scope(value, authority) for value in values)
    if not scope_ok:
        return {"status": "BLOCKED", "refs": refs, "reason": "authority scope mismatch"}
    if require_scope and not scoped_record:
        return {"status": "BLOCKED", "refs": refs, "reason": "same-run authority scope is absent"}
    if statuses.intersection(_BLOCKED_STATUSES):
        return {"status": "BLOCKED", "refs": refs, "reason": "source reports an unverified or blocked state"}
    if statuses.intersection(_PARTIAL_STATUSES):
        return {"status": "PARTIAL", "refs": refs, "reason": "source reports partial evidence"}
    if statuses and statuses.issubset(_NEGATIVE_STATUSES):
        return {"status": "NOT_OBSERVED", "refs": refs, "reason": "source reports no observation"}
    if statuses.intersection(_NEGATIVE_STATUSES):
        return {"status": "PARTIAL", "refs": refs, "reason": "source contains observed and missing facts"}
    if not has_record:
        return {"status": "NOT_OBSERVED", "refs": refs, "reason": "allowlisted evidence is empty"}
    return {"status": "OBSERVED", "refs": refs}


def _group_observation(
    root: Path,
    paths: list[str],
    authority: Mapping[str, str],
    *,
    required_groups: tuple[tuple[str, ...], ...],
) -> dict[str, Any]:
    observation = _ordinary_observation(root, paths, authority)
    if observation["status"] != "OBSERVED":
        return observation
    missing = [
        group
        for group in required_groups
        if not any(any(path.endswith(suffix) for suffix in group) for path in paths)
    ]
    if missing:
        return {
            **observation,
            "status": "PARTIAL",
            "reason": "one or more required readback groups are absent",
        }
    return observation


def _matrix_observation(
    root: Path,
    paths: list[str],
    authority: Mapping[str, str],
) -> dict[str, Any]:
    indexes = [path for path in paths if path.endswith("/event-index.jsonl")]
    refs = [SOURCE_PREFIX + path for path in paths]
    if not indexes:
        return {"status": "NOT_OBSERVED", "refs": refs, "reason": "exact Matrix event index is absent"}
    count = 0
    partial = False
    for index in indexes:
        records = _json_records(_read_bytes(_source_path(root, index), label=index), label=index)
        for record in records:
            if not isinstance(record, Mapping) or not _scope_matches(record, authority):
                return {"status": "BLOCKED", "refs": refs, "reason": "Matrix index scope or shape is invalid"}
            immutable = record.get("immutable_source")
            if not isinstance(immutable, Mapping):
                return {"status": "BLOCKED", "refs": refs, "reason": "Matrix immutable source is absent"}
            source_ref = immutable.get("ref")
            expected = immutable.get("raw_bytes_sha256")
            if not isinstance(source_ref, str) or not _SHA256.fullmatch(str(expected)):
                return {"status": "BLOCKED", "refs": refs, "reason": "Matrix raw hash binding is invalid"}
            source_ref = _safe_relative(source_ref, field="Matrix immutable source")
            if source_ref not in paths or not source_ref.endswith(".json"):
                return {"status": "BLOCKED", "refs": refs, "reason": "Matrix immutable source is outside the allowlist"}
            event_bytes = _read_bytes(_source_path(root, source_ref), label=source_ref)
            sidecar_ref = source_ref[:-5] + ".raw.sha256"
            if sidecar_ref not in paths:
                return {"status": "BLOCKED", "refs": refs, "reason": "Matrix raw checksum sidecar is absent"}
            sidecar = _read_bytes(_source_path(root, sidecar_ref), label=sidecar_ref).decode("ascii").strip()
            if sidecar != expected or _digest(event_bytes) != expected:
                return {"status": "BLOCKED", "refs": refs, "reason": "Matrix exact GET raw checksum mismatch"}
            if record.get("identity_binding") not in {"ACTOR_EXACT", "HUMAN_ALLOWLIST_EXACT"}:
                partial = True
            count += 1
    if count == 0:
        return {"status": "NOT_OBSERVED", "refs": refs, "reason": "no exact Matrix event was captured"}
    if partial:
        return {"status": "PARTIAL", "refs": refs, "reason": "one or more Matrix identities are unbound"}
    return {"status": "OBSERVED", "refs": refs, "exact_event_count": count}


def _oracle_from_file(root: Path, relative: str, authority: Mapping[str, str]) -> OracleResult:
    value = dict(_load_json(_source_path(root, relative), label=relative))
    try:
        result = OracleResult(**value)
    except (AuthorityError, TypeError, ValueError) as error:
        raise HeroBundleError(f"invalid Oracle result: {relative}") from error
    if any(getattr(result, field) != authority[field] for field in _SCOPE_FIELDS):
        raise HeroBundleError(f"Oracle authority scope mismatch: {relative}")
    return result


def _oracle_observations(
    root: Path,
    selected: Mapping[str, list[str]],
    authority: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    outcome_paths = selected["oracle_outcome"]
    boundary_paths = selected["oracle_boundary"]
    missing = {"status": "NOT_OBSERVED", "refs": [], "reason": "independent Oracle result is absent"}
    outcome_observation = dict(missing)
    boundary_observation = dict(missing)
    outcome: OracleResult | None = None
    boundary: OracleResult | None = None
    try:
        if outcome_paths:
            outcome = _oracle_from_file(root, outcome_paths[0], authority)
            outcome_observation = {
                "status": "NOT_OBSERVED" if outcome.status in _NEGATIVE_STATUSES else "OBSERVED",
                "refs": [SOURCE_PREFIX + item for item in outcome_paths],
                "oracle_status": outcome.status,
            }
    except HeroBundleError as error:
        outcome_observation = {
            "status": "BLOCKED",
            "refs": [SOURCE_PREFIX + item for item in outcome_paths],
            "reason": str(error),
        }
    try:
        if boundary_paths:
            boundary = _oracle_from_file(root, boundary_paths[0], authority)
            boundary_observation = {
                "status": "NOT_OBSERVED" if boundary.status in _NEGATIVE_STATUSES else "OBSERVED",
                "refs": [SOURCE_PREFIX + item for item in boundary_paths],
                "oracle_status": boundary.status,
            }
    except HeroBundleError as error:
        boundary_observation = {
            "status": "BLOCKED",
            "refs": [SOURCE_PREFIX + item for item in boundary_paths],
            "reason": str(error),
        }
    if outcome is None or boundary is None:
        return outcome_observation, boundary_observation
    try:
        validate_oracle_pair(outcome, boundary)
    except AuthorityError as error:
        reason = f"independent Oracle pair is invalid: {error}"
        return (
            {**outcome_observation, "status": "BLOCKED", "reason": reason},
            {**boundary_observation, "status": "BLOCKED", "reason": reason},
        )
    return outcome_observation, boundary_observation


def _validate_selected_checksums(
    root: Path,
    selected: Mapping[str, list[str]],
    checksums: Mapping[str, str],
    latest: str,
) -> dict[str, bytes]:
    relatives = {"manifest.json", "SHA256SUMS", f"{latest}/snapshot-manifest.json"}
    relatives.update(path for paths in selected.values() for path in paths)
    payload: dict[str, bytes] = {}
    for relative in sorted(relatives):
        data = _read_bytes(_source_path(root, relative), label=relative)
        if relative != "SHA256SUMS":
            if checksums.get(relative) != _digest(data):
                raise HeroBundleError(f"selected source checksum mismatch: {relative}")
        payload[SOURCE_PREFIX + relative] = data
    return payload


def _replay_program() -> bytes:
    program = r'''#!/usr/bin/env python3
import hashlib
import json
import sys
import zipfile

def digest(data):
    return hashlib.sha256(data).hexdigest()

def fail(message):
    print("hero bundle replay failed: " + message, file=sys.stderr)
    raise SystemExit(2)

def main():
    if len(sys.argv) != 2:
        fail("usage: replay.py BUNDLE.zip")
    target = sys.argv[1]
    try:
        raw_bundle = open(target, "rb").read()
        with zipfile.ZipFile(target) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or "bundle-manifest.json" not in names:
                fail("invalid archive members")
            outer = json.loads(archive.read("bundle-manifest.json"))
            expected = [item["path"] for item in outer["files"]]
            if sorted(name for name in names if name != "bundle-manifest.json") != expected:
                fail("archive allowlist mismatch")
            for item in outer["files"]:
                data = archive.read(item["path"])
                if digest(data) != item["sha256"] or len(data) != item["size"]:
                    fail("outer checksum mismatch: " + item["path"])
            inner = json.loads(archive.read("manifest.json"))
            sums = {}
            for line in archive.read("SHA256SUMS").decode("utf-8").splitlines():
                value, name = line.split("  ", 1)
                if name.startswith("./"):
                    name = name[2:]
                if name in sums:
                    fail("duplicate checksum path")
                sums[name] = value
            expected_sums = set(names) - {"SHA256SUMS", "bundle-manifest.json"}
            if set(sums) != expected_sums:
                fail("inner checksum allowlist mismatch")
            for name, value in sums.items():
                if digest(archive.read(name)) != value:
                    fail("inner checksum mismatch: " + name)
            if outer["classification"] != inner["classification"]:
                fail("classification mismatch")
            if "LIVE" in inner["classification"]:
                fail("unsealed LIVE classification")
            if any(item["status"] == "PASS" for item in inner["observations"].values()):
                fail("PASS is not an evidence observation")
    except (OSError, KeyError, TypeError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        fail(str(error))
    print(json.dumps({"bundle_sha256": digest(raw_bundle), "classification": inner["classification"], "replay_equal": True}, sort_keys=True, separators=(",", ":")))

if __name__ == "__main__":
    main()
'''
    return program.encode()


def _write_staged(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _inner_sums(files: Mapping[str, bytes]) -> bytes:
    return "".join(f"{_digest(data)}  ./{name}\n" for name, data in sorted(files.items())).encode()


def _attestation(source: bytes, sums: bytes) -> dict[str, str]:
    value = {
        "source_ref": "source/manifest.json",
        "source_hash": "sha256:" + _digest(source),
        "attestation_ref": "hero-evidence:SHA256SUMS",
        "source_kind": "agentteams-native-export",
        "manifest_ref": "source/SHA256SUMS",
        "manifest_hash": "sha256:" + _digest(sums),
    }
    value["attestation_hash"] = canonical_hash(value)
    return value


def build_hero_bundle(
    evidence_dir: Path,
    output: Path,
    *,
    source_commit: str,
) -> dict[str, Any]:
    """Seal an allowlisted, completed capture without mutating the source."""

    root = Path(evidence_dir)
    output = Path(output)
    if root.is_symlink():
        raise HeroBundleError("evidence directory must not be a symbolic link")
    if not root.is_absolute():
        root = root.resolve()
    if not root.is_dir():
        raise HeroBundleError("evidence directory must be a regular directory")
    if output.exists():
        raise HeroBundleError("bundle output already exists")
    manifest, authority, latest = _capture_identity(root)
    checksums, _ = _parse_source_sums(root)
    selected = _select_files(root, latest)
    payload = _validate_selected_checksums(root, selected, checksums, latest)

    observations: dict[str, dict[str, Any]] = {}
    observations["matrix_exact"] = _matrix_observation(root, selected["matrix_exact"], authority)
    observations["agentteams_task"] = _group_observation(
        root,
        selected["agentteams_task"],
        authority,
        required_groups=(("/authority/projects.json",), ("/authority/tasks.json", "/shared-fs/task-metadata.jsonl")),
    )
    observations["provider_facts"] = _group_observation(
        root,
        selected["provider_facts"],
        authority,
        required_groups=(("/manager-choice-readback.json",), ("/readback.jsonl",)),
    )
    observations["skill"] = _group_observation(
        root,
        selected["skill"],
        authority,
        required_groups=(("/list.json",), ("/hashes.txt",)),
    )
    observations["pg_events"] = _ordinary_observation(root, selected["pg_events"], authority)
    for category in ("hitl", "recovery", "otel", "agentloop"):
        observations[category] = _ordinary_observation(
            root,
            selected[category],
            authority,
            require_scope=True,
        )
    outcome, boundary = _oracle_observations(root, selected, authority)
    observations["oracle_outcome"] = outcome
    observations["oracle_boundary"] = boundary
    observations = {name: observations[name] for name in _REQUIRED_CATEGORIES}
    if any(item["status"] not in _OBSERVATION_STATUSES for item in observations.values()):
        raise HeroBundleError("internal observation status is unsupported")
    classification = (
        "ATTESTED_EXTERNAL_EXPORT"
        if all(item["status"] == "OBSERVED" for item in observations.values())
        else "PARTIAL"
    )

    source_files = [
        {"path": name, "sha256": _digest(data), "size": len(data)}
        for name, data in sorted(payload.items())
    ]
    inner_manifest = {
        "schema": SCHEMA,
        "classification": classification,
        "source_commit": source_commit,
        "authority_scope": authority,
        "capture": {
            "schema": manifest["schema"],
            "status": manifest["status"],
            "checksum_state": manifest["checksum_state"],
            "latest_snapshot": latest,
        },
        "receipt_contract": {
            "schema_ref": RECEIPT_SCHEMA,
            "observation_statuses": sorted(_OBSERVATION_STATUSES),
            "read_only": True,
            "generated_runtime_events": False,
        },
        "observations": observations,
        "source_files": source_files,
    }
    generated = {
        **payload,
        "manifest.json": _canonical_bytes(inner_manifest),
        "replay.py": _replay_program(),
    }
    generated["SHA256SUMS"] = _inner_sums(generated)

    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="testweaver-hero-bundle-") as directory:
            stage = Path(directory)
            staged_files: dict[str, Path] = {}
            for name, data in generated.items():
                path = stage.joinpath(*PurePosixPath(name).parts)
                _write_staged(path, data)
                staged_files[name] = path
            temporary_bundle = stage / "result.zip"
            result = build_bundle(
                temporary_bundle,
                staged_files,
                classification=classification,
                source_commit=source_commit,
                raw_source_attestation=_attestation(
                    generated["source/manifest.json"], generated["source/SHA256SUMS"]
                ),
                raw_source_path=staged_files["source/manifest.json"],
            )
            os.replace(temporary_bundle, output)
    except (BundleError, OSError) as error:
        if output.exists():
            try:
                output.unlink()
            except OSError:
                pass
        raise HeroBundleError(f"bundle build failed: {error}") from error
    return {**result, "observations": observations}


def _read_outer_identity(bundle: Path) -> tuple[list[str], str]:
    try:
        with zipfile.ZipFile(bundle) as archive:
            value = _load_json_bytes(archive.read("bundle-manifest.json"), label="bundle manifest")
    except (OSError, KeyError, zipfile.BadZipFile) as error:
        raise HeroBundleError("bundle archive is invalid") from error
    files = value.get("files")
    if not isinstance(files, list):
        raise HeroBundleError("bundle manifest file list is invalid")
    expected: list[str] = []
    for item in files:
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            raise HeroBundleError("bundle manifest file entry is invalid")
        expected.append(item["path"])
    source_commit = value.get("source_commit")
    if not isinstance(source_commit, str) or not source_commit:
        raise HeroBundleError("bundle source commit is absent")
    return expected, source_commit


def _verify_inner(bundle: Path) -> Mapping[str, Any]:
    try:
        with zipfile.ZipFile(bundle) as archive:
            names = set(archive.namelist())
            manifest = _load_json_bytes(archive.read("manifest.json"), label="Hero manifest")
            raw_sums = archive.read("SHA256SUMS").decode("utf-8")
            sums: dict[str, str] = {}
            for number, line in enumerate(raw_sums.splitlines(), 1):
                digest, name = line.split("  ", 1)
                if name.startswith("./"):
                    name = name[2:]
                name = _safe_relative(name, field="bundle checksum path")
                if not _SHA256.fullmatch(digest) or name in sums:
                    raise HeroBundleError(f"invalid bundle checksum line {number}")
                sums[name] = digest
            expected = names - {"SHA256SUMS", "bundle-manifest.json"}
            if set(sums) != expected:
                raise HeroBundleError("bundle checksum allowlist mismatch")
            for name, digest in sums.items():
                if _digest(archive.read(name)) != digest:
                    raise HeroBundleError(f"bundle checksum mismatch: {name}")
    except HeroBundleError:
        raise
    except (OSError, KeyError, UnicodeDecodeError, ValueError, zipfile.BadZipFile) as error:
        raise HeroBundleError("bundle inner receipt is invalid") from error
    if manifest.get("schema") != SCHEMA:
        raise HeroBundleError("Hero bundle schema is unsupported")
    classification = manifest.get("classification")
    if classification not in {"ATTESTED_EXTERNAL_EXPORT", "PARTIAL"} or "LIVE" in classification:
        raise HeroBundleError("Hero bundle classification is invalid")
    observations = manifest.get("observations")
    if not isinstance(observations, Mapping) or set(observations) != set(_REQUIRED_CATEGORIES):
        raise HeroBundleError("Hero bundle observations are incomplete")
    for item in observations.values():
        if not isinstance(item, Mapping) or item.get("status") not in _OBSERVATION_STATUSES:
            raise HeroBundleError("Hero bundle observation status is invalid")
    expected_classification = (
        "ATTESTED_EXTERNAL_EXPORT"
        if all(item["status"] == "OBSERVED" for item in observations.values())
        else "PARTIAL"
    )
    if classification != expected_classification:
        raise HeroBundleError("Hero bundle classification does not match observations")
    return manifest


def verify_hero_bundle(bundle: Path) -> dict[str, Any]:
    """Verify both the existing offline bundle receipt and Hero receipt."""

    target = Path(bundle)
    expected, source_commit = _read_outer_identity(target)
    try:
        result = verify_bundle(
            target,
            expected_files=expected,
            expected_source_commit=source_commit,
        )
    except (BundleError, OSError, ValueError, zipfile.BadZipFile) as error:
        raise HeroBundleError(f"bundle verification failed: {error}") from error
    manifest = _verify_inner(target)
    if result["classification"] != manifest["classification"]:
        raise HeroBundleError("outer and Hero classifications differ")
    return {**result, "observations": manifest["observations"]}


def replay_hero_bundle(bundle: Path) -> dict[str, Any]:
    """Independently repeat offline verification and compare canonical results."""

    first = verify_hero_bundle(bundle)
    second = verify_hero_bundle(bundle)
    replay_equal = canonical_hash(first) == canonical_hash(second)
    if not replay_equal:
        raise HeroBundleError("offline replay is not deterministic")
    return {**first, "replay_equal": True, "replay_hash": canonical_hash(second)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only completed-Hero evidence bundle and replay")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="bundle a completed native Hero evidence directory")
    build.add_argument("evidence_dir", type=Path)
    build.add_argument("output", type=Path)
    build.add_argument("--source-commit", required=True)
    for name in ("verify", "replay"):
        command = commands.add_parser(name, help=f"{name} an offline Hero bundle")
        command.add_argument("bundle", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_hero_bundle(args.evidence_dir, args.output, source_commit=args.source_commit)
        elif args.command == "verify":
            result = verify_hero_bundle(args.bundle)
        else:
            result = replay_hero_bundle(args.bundle)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (HeroBundleError, OSError, ValueError) as error:
        print(f"hero bundle failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
