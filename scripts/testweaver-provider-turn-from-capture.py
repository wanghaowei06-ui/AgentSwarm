#!/usr/bin/env python3
"""Build one bridge input from hash-closed, read-only Hero capture evidence.

This program only reads an already STOPPED capture and writes a local provider
turn plus a build receipt.  It neither emits telemetry nor contacts Matrix,
AgentTeams, providers, databases, or cloud APIs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from testweaver.authority import validate_ref
from testweaver.contracts.validator import canonical_hash


_CAPTURE_SCHEMA = "testweaver.native-hero-capture.v1"
_OUTPUT_SCHEMA = "testweaver.provider-turn/v1"
_RECEIPT_SCHEMA = "testweaver.provider-turn-build-receipt/v1"
_PG_SCHEMA = "testweaver.pg-exact-readback/v1"
_SKILL_SCHEMA = "testweaver.skill-invocation-capture/v1"
_HEX = re.compile(r"^[0-9a-f]{64}$")
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_SUM = re.compile(r"^([0-9a-f]{64})  ([^\x00\r\n]+)$")
_MAX_JSON_BYTES = 16 * 1024 * 1024
_PROHIBITED_CAPTURE_ACTIONS = {
    "matrix_send",
    "resource_mutation",
    "fault_injection",
    "provider_call",
    "gold_read",
    "event_injection",
}


class BuildBlocked(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError:
        raise BuildBlocked("CAPTURE_SOURCE_UNREADABLE") from None
    return digest.hexdigest()


def _prefixed_hash(value: Any, reason: str = "EVIDENCE_FORMAT_INVALID") -> str:
    if isinstance(value, str) and _HASH.fullmatch(value):
        return value
    if isinstance(value, str) and _HEX.fullmatch(value):
        return f"sha256:{value}"
    raise BuildBlocked(reason)


def _safe_relative(value: str) -> str:
    if not isinstance(value, str) or "\\" in value or value.startswith("/"):
        raise BuildBlocked("EVIDENCE_REF_INVALID")
    pure = PurePosixPath(value)
    if not value or value != pure.as_posix() or any(part in {"", ".", ".."} for part in pure.parts):
        raise BuildBlocked("EVIDENCE_REF_INVALID")
    return value


def _source_path(root: Path, relative: str) -> Path:
    relative = _safe_relative(relative)
    path = root.joinpath(*PurePosixPath(relative).parts)
    try:
        path.relative_to(root)
    except ValueError:
        raise BuildBlocked("EVIDENCE_REF_INVALID") from None
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            raise BuildBlocked("EVIDENCE_REF_INVALID")
    if not path.is_file():
        raise BuildBlocked("EVIDENCE_MISSING")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        if not raw or len(raw) > _MAX_JSON_BYTES:
            raise BuildBlocked("EVIDENCE_FORMAT_INVALID")
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise BuildBlocked("EVIDENCE_FORMAT_INVALID") from None
    if not isinstance(value, dict):
        raise BuildBlocked("EVIDENCE_FORMAT_INVALID")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        raw = path.read_bytes()
        if not raw or len(raw) > _MAX_JSON_BYTES:
            raise BuildBlocked("EVIDENCE_FORMAT_INVALID")
        result = [json.loads(line) for line in raw.splitlines() if line.strip()]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise BuildBlocked("EVIDENCE_FORMAT_INVALID") from None
    if not result or any(not isinstance(item, dict) for item in result):
        raise BuildBlocked("EVIDENCE_FORMAT_INVALID")
    return result


def _load_checksums(root: Path) -> dict[str, str]:
    sums_path = _source_path(root, "SHA256SUMS")
    try:
        lines = sums_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        raise BuildBlocked("CAPTURE_CHECKSUM_INVALID") from None
    if not lines:
        raise BuildBlocked("CAPTURE_CHECKSUM_INVALID")
    sums: dict[str, str] = {}
    for line in lines:
        match = _SUM.fullmatch(line)
        if match is None:
            raise BuildBlocked("CAPTURE_CHECKSUM_INVALID")
        digest, relative = match.groups()
        relative = relative.removeprefix("./")
        relative = _safe_relative(relative)
        if relative == "SHA256SUMS" or relative in sums:
            raise BuildBlocked("CAPTURE_CHECKSUM_INVALID")
        sums[relative] = digest
    if "manifest.json" not in sums:
        raise BuildBlocked("CAPTURE_CHECKSUM_INVALID")
    for relative, expected in sums.items():
        if _sha256(_source_path(root, relative)) != expected:
            raise BuildBlocked("CAPTURE_CHECKSUM_MISMATCH")
    return sums


def _checked_ref(root: Path, sums: Mapping[str, str], relative: str) -> tuple[Path, str]:
    relative = _safe_relative(relative)
    expected = sums.get(relative)
    if expected is None:
        raise BuildBlocked("EVIDENCE_NOT_SEALED")
    path = _source_path(root, relative)
    if _sha256(path) != expected:
        raise BuildBlocked("CAPTURE_CHECKSUM_MISMATCH")
    return path, f"sha256:{expected}"


def _scope(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"campaign_id", "run_id", "trace_id"}:
        raise BuildBlocked("AUTHORITY_SCOPE_INVALID")
    for field in ("campaign_id", "run_id"):
        try:
            validate_ref(value[field], field)
        except Exception:
            raise BuildBlocked("AUTHORITY_SCOPE_INVALID") from None
    if not isinstance(value["trace_id"], str) or _TRACE_ID.fullmatch(value["trace_id"]) is None:
        raise BuildBlocked("AUTHORITY_SCOPE_INVALID")
    return value


def _sealed(value: Mapping[str, Any], schema: str, fields: set[str]) -> None:
    if set(value) != fields or value.get("schema_version") != schema:
        raise BuildBlocked("EVIDENCE_FORMAT_INVALID")
    record_hash = value.get("record_hash")
    if not isinstance(record_hash, str) or record_hash != canonical_hash(
        {key: child for key, child in value.items() if key != "record_hash"}
    ):
        raise BuildBlocked("EVIDENCE_NOT_SEALED")


def _usage(value: Any) -> dict[str, int]:
    if not isinstance(value, dict) or not value:
        raise BuildBlocked("EVIDENCE_FORMAT_INVALID")
    aliases = {
        "input": "input_tokens",
        "output": "output_tokens",
        "total": "total_tokens",
        "input_tokens": "input_tokens",
        "output_tokens": "output_tokens",
        "total_tokens": "total_tokens",
    }
    if set(value) - set(aliases):
        raise BuildBlocked("EVIDENCE_FORMAT_INVALID")
    result: dict[str, int] = {}
    for key, number in value.items():
        target = aliases[key]
        if target in result or isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise BuildBlocked("EVIDENCE_FORMAT_INVALID")
        result[target] = number
    return result


def _exact_raw_source(
    root: Path,
    sums: Mapping[str, str],
    ref: Any,
    claimed_hash: Any,
) -> tuple[Path, dict[str, Any]]:
    if not isinstance(ref, str):
        raise BuildBlocked("EVIDENCE_REF_INVALID")
    path, actual = _checked_ref(root, sums, ref)
    if _prefixed_hash(claimed_hash) != actual:
        raise BuildBlocked("SOURCE_HASH_MISMATCH")
    return path, _read_json(path)


def build(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    capture_arg = Path(args.capture_dir)
    if not capture_arg.is_absolute() or capture_arg.is_symlink() or not capture_arg.is_dir():
        raise BuildBlocked("CAPTURE_DIR_INVALID")
    capture = capture_arg.resolve(strict=True)
    sums = _load_checksums(capture)
    manifest_path, manifest_hash = _checked_ref(capture, sums, "manifest.json")
    manifest = _read_json(manifest_path)
    if (
        manifest.get("schema") != _CAPTURE_SCHEMA
        or manifest.get("status") != "STOPPED"
        or manifest.get("checksum_state") != "FINAL"
        or manifest.get("live_claimed") is not False
        or manifest.get("classification") != "NOT_ASSESSED"
        or not isinstance(manifest.get("prohibited_actions_performed"), dict)
        or set(manifest["prohibited_actions_performed"]) != _PROHIBITED_CAPTURE_ACTIONS
        or any(value is not False for value in manifest["prohibited_actions_performed"].values())
    ):
        raise BuildBlocked("CAPTURE_NOT_FINAL")
    scope = _scope(manifest.get("authority_scope"))
    snapshot_ref = _safe_relative(manifest.get("latest_snapshot", ""))
    snapshot_prefix = snapshot_ref + "/"
    pg_ref = f"{snapshot_ref}/pg-exact-readback.jsonl"
    skill_ref = f"{snapshot_ref}/skill-invocations.jsonl"
    requested_refs = {
        "provider": args.provider_session_ref,
        "task": args.task_ref,
        "pg": pg_ref,
        "skill": skill_ref,
    }
    if any(not ref.startswith(snapshot_prefix) for ref in requested_refs.values()):
        raise BuildBlocked("EVIDENCE_OUTSIDE_FINAL_SNAPSHOT")

    provider_path, provider_file_hash = _checked_ref(capture, sums, args.provider_session_ref)
    wanted_record_hash = _prefixed_hash(args.provider_record_hash)
    session_records = _read_jsonl(provider_path)
    provider_matches = [
        item
        for item in session_records
        if _prefixed_hash(item.get("record_hash")) == wanted_record_hash
    ]
    if len(provider_matches) != 1:
        raise BuildBlocked("EVIDENCE_AMBIGUOUS" if provider_matches else "EVIDENCE_MISSING")
    provider = provider_matches[0]
    provider_required = {
        "record_hash", "role", "actor", "provider", "model", "usage", "latency_ms",
        "scope_mentions", "session_ref", "session_file_sha256", "container",
    }
    if (
        not provider_required.issubset(provider)
        or provider.get("role") != "assistant"
        or not isinstance(provider.get("scope_mentions"), dict)
        or set(provider["scope_mentions"]) != {"campaign_id", "run_id", "trace_id"}
        or any(not isinstance(value, bool) for value in provider["scope_mentions"].values())
    ):
        raise BuildBlocked("EVIDENCE_FORMAT_INVALID")
    _prefixed_hash(provider.get("session_file_sha256"))
    try:
        agent_id = validate_ref(provider.get("actor"), "agent_id")
        provider_name = validate_ref(provider.get("provider"), "provider")
        model = validate_ref(provider.get("model"), "model")
        validate_ref(provider.get("session_ref"), "session_ref")
        validate_ref(provider.get("container"), "container")
    except Exception:
        raise BuildBlocked("EVIDENCE_FORMAT_INVALID") from None
    usage = _usage(provider.get("usage"))
    latency = provider.get("latency_ms")
    if (
        isinstance(latency, bool)
        or not isinstance(latency, (int, float))
        or not math.isfinite(float(latency))
        or latency < 0
    ):
        raise BuildBlocked("EVIDENCE_FORMAT_INVALID")

    task_path, task_file_hash = _checked_ref(capture, sums, args.task_ref)
    task_matches = [item for item in _read_jsonl(task_path) if item.get("task_id") == args.task_id]
    if len(task_matches) != 1:
        raise BuildBlocked("EVIDENCE_AMBIGUOUS" if task_matches else "EVIDENCE_MISSING")
    task = task_matches[0]
    try:
        task_id = validate_ref(task.get("task_id"), "task_id")
    except Exception:
        raise BuildBlocked("EVIDENCE_FORMAT_INVALID") from None
    if (
        task.get("status") not in {"submitted", "completed"}
        or task.get("result_status") not in {"SUCCESS", "PASS"}
        or task.get("submitted_by_role") != "worker"
    ):
        raise BuildBlocked("TASK_NOT_COMPLETED")
    task_raw_hash = _prefixed_hash(task.get("raw_bytes_sha256"))
    task_source_ref = task.get("source_ref")
    try:
        validate_ref(task_source_ref, "task.source_ref")
    except Exception:
        raise BuildBlocked("EVIDENCE_FORMAT_INVALID") from None
    artifacts_ref = str(PurePosixPath(args.task_ref).parent / "task-artifacts.jsonl")
    artifacts_path, artifacts_hash = _checked_ref(capture, sums, artifacts_ref)
    artifact_matches = [
        item
        for item in _read_jsonl(artifacts_path)
        if item.get("kind") == "metadata"
        and item.get("source_ref") == task_source_ref
        and _prefixed_hash(item.get("raw_bytes_sha256")) == task_raw_hash
    ]
    if len(artifact_matches) != 1:
        raise BuildBlocked("SOURCE_HASH_MISMATCH")

    roster_path, _ = _checked_ref(capture, sums, f"{snapshot_ref}/roster.json")
    roster = _read_json(roster_path)
    actors = roster.get("actors")
    actor_matches = [item for item in actors or [] if isinstance(item, dict) and item.get("name") == agent_id]
    if len(actor_matches) != 1 or task.get("assigned_to") not in {
        agent_id,
        actor_matches[0].get("matrix_user_id"),
    }:
        raise BuildBlocked("EVIDENCE_BINDING_MISMATCH")

    pg_path, pg_file_hash = _checked_ref(capture, sums, pg_ref)
    pg_fields = {
        "schema_version", "authority_scope", "table", "pg_revision", "content_hash",
        "agent_id", "task_id", "provider_session_record_hash", "source_ref",
        "source_hash", "record_hash",
    }
    pg_records = _read_jsonl(pg_path)
    for record in pg_records:
        _sealed(record, _PG_SCHEMA, pg_fields)
    pg_matches = [
        record
        for record in pg_records
        if record.get("authority_scope") == scope
        and record.get("agent_id") == agent_id
        and record.get("task_id") == task_id
        and record.get("provider_session_record_hash") == wanted_record_hash
    ]
    if len(pg_matches) != 1:
        raise BuildBlocked("EVIDENCE_AMBIGUOUS" if pg_matches else "EVIDENCE_MISSING")
    pg = pg_matches[0]
    try:
        validate_ref(pg.get("table"), "pg.table")
    except Exception:
        raise BuildBlocked("EVIDENCE_FORMAT_INVALID") from None
    pg_raw_prefix = f"{snapshot_ref}/pg-exact-raw/"
    if not isinstance(pg.get("source_ref"), str) or not pg["source_ref"].startswith(pg_raw_prefix):
        raise BuildBlocked("EVIDENCE_OUTSIDE_FINAL_SNAPSHOT")
    pg_raw_path, pg_raw = _exact_raw_source(capture, sums, pg["source_ref"], pg["source_hash"])
    del pg_raw_path
    pg_expected_raw = {
        **scope,
        "pg_revision": pg["pg_revision"],
        "content_hash": pg["content_hash"],
        "agent_id": pg["agent_id"],
        "task_id": pg["task_id"],
        "provider_session_record_hash": pg["provider_session_record_hash"],
    }
    if any(pg_raw.get(key) != expected for key, expected in pg_expected_raw.items()):
        raise BuildBlocked("SOURCE_READBACK_MISMATCH")
    if (
        pg.get("authority_scope") != scope
        or pg.get("agent_id") != agent_id
        or pg.get("task_id") != task_id
        or pg.get("provider_session_record_hash") != wanted_record_hash
        or isinstance(pg.get("pg_revision"), bool)
        or not isinstance(pg.get("pg_revision"), int)
        or pg["pg_revision"] < 1
        or not isinstance(pg.get("content_hash"), str)
        or _HASH.fullmatch(pg["content_hash"]) is None
    ):
        raise BuildBlocked("EVIDENCE_BINDING_MISMATCH")

    skill_path, skill_file_hash = _checked_ref(capture, sums, skill_ref)
    skill_fields = {
        "schema_version", "authority_scope", "agent_id", "task_id",
        "provider_session_record_hash", "skill", "invoke_ref", "source_ref", "source_hash",
        "source_kind", "task_event_ref", "task_event_source_ref",
        "task_event_source_hash", "session_ref", "session_hash",
        "turn_input_record_hash", "event_timestamp_ms", "record_hash",
    }
    skill_records = _read_jsonl(skill_path)
    for record in skill_records:
        _sealed(record, _SKILL_SCHEMA, skill_fields)
    skill_matches = [
        record
        for record in skill_records
        if record.get("authority_scope") == scope
        and record.get("agent_id") == agent_id
        and record.get("task_id") == task_id
        and record.get("provider_session_record_hash") == wanted_record_hash
    ]
    if len(skill_matches) != 1:
        raise BuildBlocked("EVIDENCE_AMBIGUOUS" if skill_matches else "EVIDENCE_MISSING")
    skill = skill_matches[0]
    skill_data = skill.get("skill")
    if not isinstance(skill_data, dict) or set(skill_data) != {
        "name", "version", "source_ref", "source_hash"
    }:
        raise BuildBlocked("EVIDENCE_FORMAT_INVALID")
    safe_actor = re.sub(r"[^A-Za-z0-9._-]", "_", agent_id)
    skill_event_prefix = f"{snapshot_ref}/matrix/{safe_actor}/events/"
    if not isinstance(skill.get("source_ref"), str) or not skill["source_ref"].startswith(skill_event_prefix):
        raise BuildBlocked("EVIDENCE_OUTSIDE_FINAL_SNAPSHOT")
    _, invocation_event = _exact_raw_source(
        capture, sums, skill["source_ref"], skill["source_hash"]
    )
    if (
        skill.get("authority_scope") != scope
        or skill.get("agent_id") != agent_id
        or skill.get("task_id") != task_id
        or skill.get("provider_session_record_hash") != wanted_record_hash
        or skill.get("source_kind") != "runtime_matrix_skill_event"
        or skill.get("session_ref") != args.provider_session_ref
        or skill.get("session_hash") != provider_file_hash
    ):
        raise BuildBlocked("EVIDENCE_BINDING_MISMATCH")
    try:
        skill_name = validate_ref(skill_data.get("name"), "skill.name")
        skill_version = validate_ref(skill_data.get("version"), "skill.version")
        skill_source_ref = validate_ref(skill_data.get("source_ref"), "skill.source_ref")
        invoke_ref = validate_ref(skill.get("invoke_ref"), "skill.invoke_ref")
        task_event_ref = validate_ref(skill.get("task_event_ref"), "skill.task_event_ref")
    except Exception:
        raise BuildBlocked("EVIDENCE_FORMAT_INVALID") from None
    skill_source_hash = _prefixed_hash(skill_data.get("source_hash"))
    if skill_version != skill_source_hash:
        raise BuildBlocked("EVIDENCE_BINDING_MISMATCH")
    event_timestamp_ms = skill.get("event_timestamp_ms")
    actor_matrix_id = actor_matches[0].get("matrix_user_id")
    event_index_ref = f"{snapshot_ref}/matrix/{safe_actor}/event-index.jsonl"
    event_index_path, event_index_hash = _checked_ref(capture, sums, event_index_ref)
    event_indexes = _read_jsonl(event_index_path)
    invocation_indexes = [
        item for item in event_indexes if item.get("event_id") == invoke_ref
    ]
    if len(invocation_indexes) != 1:
        raise BuildBlocked("EVIDENCE_BINDING_MISMATCH")
    invocation_index = invocation_indexes[0]
    immutable = invocation_index.get("immutable_source")
    if (
        invocation_index.get("actor") != agent_id
        or invocation_index.get("actor_matrix_id") != actor_matrix_id
        or invocation_index.get("sender") != actor_matrix_id
        or invocation_index.get("identity_binding") != "ACTOR_EXACT"
        or invocation_index.get("authority_scope") != scope
        or invocation_index.get("origin_server_ts") != event_timestamp_ms
        or not isinstance(immutable, dict)
        or immutable.get("ref") != skill.get("source_ref")
        or _prefixed_hash(immutable.get("raw_bytes_sha256"))
        != _prefixed_hash(skill.get("source_hash"))
    ):
        raise BuildBlocked("EVIDENCE_BINDING_MISMATCH")
    inventory_ref = f"{snapshot_ref}/skills/{safe_actor}/hashes.txt"
    inventory_path, inventory_hash = _checked_ref(capture, sums, inventory_ref)
    inventory_matches = []
    try:
        for line in inventory_path.read_text(encoding="utf-8").splitlines():
            parts = line.split(maxsplit=1)
            if len(parts) == 2 and parts[1].strip() == skill_source_ref:
                inventory_matches.append(_prefixed_hash(parts[0]))
    except (OSError, UnicodeDecodeError):
        raise BuildBlocked("EVIDENCE_FORMAT_INVALID") from None
    if inventory_matches != [skill_source_hash]:
        raise BuildBlocked("SOURCE_HASH_MISMATCH")
    enabled_ref = f"{snapshot_ref}/skills/{safe_actor}/list.json"
    enabled_path, enabled_hash = _checked_ref(capture, sums, enabled_ref)
    try:
        enabled = json.loads(enabled_path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise BuildBlocked("EVIDENCE_FORMAT_INVALID") from None
    if not isinstance(enabled, list) or len(
        [
            item
            for item in enabled
            if isinstance(item, dict)
            and item.get("name") == skill_name
            and item.get("enabled") is True
        ]
    ) != 1:
        raise BuildBlocked("SKILL_NOT_ENABLED")

    content = invocation_event.get("content")
    body = content.get("body") if isinstance(content, dict) else None
    read_file_match = re.fullmatch(
        r'^🔧 \*\*read_file\*\*\n```(?:json)?\n(\{[^\n]+\})\n```\s*$',
        body or "",
    )
    skill_match = re.fullmatch(
        r'^🔧 \*\*Skill\*\*\n```(?:json)?\n(\{[^\n]+\})\n```\s*$',
        body or "",
    )
    try:
        tool_input = json.loads(read_file_match.group(1)) if read_file_match is not None else None
        skill_input = json.loads(skill_match.group(1)) if skill_match is not None else None
    except json.JSONDecodeError:
        tool_input = None
        skill_input = None
    relation = content.get("m.relates_to") if isinstance(content, dict) else None
    if (
        not (
            isinstance(tool_input, dict)
            and set(tool_input) == {"file_path"}
            and tool_input.get("file_path") == skill_source_ref
            or isinstance(skill_input, dict)
            and set(skill_input) == {"skill"}
            and skill_input.get("skill") in {
                f"teamharness-{skill_name}",
                f"workerflow-{skill_name}",
            }
        )
        or invocation_event.get("event_id") != invoke_ref
        or invocation_event.get("sender") != actor_matrix_id
        or invocation_event.get("origin_server_ts") != event_timestamp_ms
        or not isinstance(relation, dict)
        or relation.get("rel_type") != "m.thread"
        or relation.get("event_id") != task_event_ref
        or isinstance(event_timestamp_ms, bool)
        or not isinstance(event_timestamp_ms, int)
    ):
        raise BuildBlocked("SOURCE_READBACK_MISMATCH")

    task_event_source_ref = skill.get("task_event_source_ref")
    if not isinstance(task_event_source_ref, str) or not task_event_source_ref.startswith(
        skill_event_prefix
    ):
        raise BuildBlocked("EVIDENCE_OUTSIDE_FINAL_SNAPSHOT")
    _, task_event = _exact_raw_source(
        capture,
        sums,
        task_event_source_ref,
        skill.get("task_event_source_hash"),
    )
    task_indexes = [
        item for item in event_indexes if item.get("event_id") == task_event_ref
    ]
    if len(task_indexes) != 1:
        raise BuildBlocked("EVIDENCE_BINDING_MISMATCH")
    task_index = task_indexes[0]
    task_immutable = task_index.get("immutable_source")
    task_content = task_event.get("content")
    task_body = task_content.get("body") if isinstance(task_content, dict) else None
    if (
        task_index.get("actor") != agent_id
        or task_index.get("actor_matrix_id") != actor_matrix_id
        or task_index.get("authority_scope") != scope
        or task_index.get("room_id") != invocation_index.get("room_id")
        or task_index.get("sender") != task_event.get("sender")
        or task_index.get("origin_server_ts") != task_event.get("origin_server_ts")
        or not isinstance(task_immutable, dict)
        or task_immutable.get("ref") != task_event_source_ref
        or _prefixed_hash(task_immutable.get("raw_bytes_sha256"))
        != _prefixed_hash(skill.get("task_event_source_hash"))
        or task_event.get("event_id") != task_event_ref
        or task_event.get("room_id") != invocation_event.get("room_id")
        or not isinstance(task_body, str)
        or not (
            task_id in re.findall(r"task-[A-Za-z0-9._:-]+", task_body)
            or (
                task.get("task_id") == task_id
                and task.get("assigned_to") in {agent_id, actor_matrix_id}
                and str(task.get("room_id", "")).removeprefix("room:")
                == invocation_event.get("room_id")
            )
        )
    ):
        raise BuildBlocked("EVIDENCE_BINDING_MISMATCH")

    turn_input_hash = _prefixed_hash(skill.get("turn_input_record_hash"))
    turn_inputs = [
        item
        for item in session_records
        if item.get("role") == "user"
        and _prefixed_hash(item.get("record_hash")) == turn_input_hash
    ]
    if len(turn_inputs) != 1:
        raise BuildBlocked("EVIDENCE_BINDING_MISMATCH")
    turn_input = turn_inputs[0]
    root_seen_in_session = any(
        item.get("session_ref") == provider.get("session_ref")
        and task_event_ref in (item.get("matrix_event_refs") or [])
        for item in session_records
    )
    if (
        turn_input.get("session_ref") != provider.get("session_ref")
        or task_id not in (turn_input.get("task_refs") or [])
        or not (
            task_event_ref in (turn_input.get("matrix_event_refs") or [])
            or root_seen_in_session
        )
        or isinstance(turn_input.get("sequence"), bool)
        or not isinstance(turn_input.get("sequence"), int)
        or isinstance(provider.get("sequence"), bool)
        or not isinstance(provider.get("sequence"), int)
        or provider["sequence"] <= turn_input["sequence"]
        or isinstance(turn_input.get("timestamp_ms"), bool)
        or not isinstance(turn_input.get("timestamp_ms"), int)
        or isinstance(provider.get("timestamp_ms"), bool)
        or not isinstance(provider.get("timestamp_ms"), int)
        or not turn_input["timestamp_ms"] <= provider["timestamp_ms"]
        or not event_timestamp_ms >= turn_input["timestamp_ms"]
    ):
        raise BuildBlocked("EVIDENCE_BINDING_MISMATCH")

    turn: dict[str, Any] = {
        "schema_version": _OUTPUT_SCHEMA,
        "campaign_id": scope["campaign_id"],
        "run_id": scope["run_id"],
        "trace_id": scope["trace_id"],
        "pg_revision": pg["pg_revision"],
        "content_hash": pg["content_hash"],
        "agent": {"id": agent_id},
        "task": {"id": task_id},
        "skill": {
            "name": skill_name,
            "version": skill_version,
            "hash": skill_source_hash,
            "invoke_ref": invoke_ref,
        },
        "provider": provider_name,
        "model": model,
        "usage": usage,
        "latency_ms": latency,
        "source_ref": args.provider_session_ref,
        "source_hash": provider_file_hash,
        "attestation_ref": skill_ref,
        "attestation_hash": skill_file_hash,
        "synthetic": False,
    }
    turn["record_hash"] = canonical_hash(turn)
    receipt = {
        "schema_version": _RECEIPT_SCHEMA,
        "status": "PASS",
        "synthetic": False,
        "provider_turn_written": True,
        "capture_manifest_hash": manifest_hash,
        "provider_turn_record_hash": turn["record_hash"],
        "sources": {
            "provider_session": provider_file_hash,
            "task": task_file_hash,
            "task_artifacts": artifacts_hash,
            "pg": pg_file_hash,
            "pg_raw": _prefixed_hash(pg["source_hash"]),
            "skill_invocation": skill_file_hash,
            "skill_runtime_event": _prefixed_hash(skill["source_hash"]),
            "skill_event_index": event_index_hash,
            "skill_inventory": inventory_hash,
            "skill_enabled_inventory": enabled_hash,
            "skill_task_event": _prefixed_hash(skill["task_event_source_hash"]),
            "skill_session": _prefixed_hash(skill["session_hash"]),
        },
    }
    return turn, receipt


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    if not path.is_absolute() or path.exists() or not path.parent.is_dir():
        raise BuildBlocked("OUTPUT_PATH_INVALID")
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(handle, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _receipt(status: str, reason: str | None, **extra: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": _RECEIPT_SCHEMA,
        "status": status,
        "synthetic": False,
        "provider_turn_written": status == "PASS",
        **extra,
    }
    if reason is not None:
        value["reason"] = reason
    value["record_hash"] = canonical_hash(value)
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dir", required=True)
    parser.add_argument("--provider-session-ref", required=True)
    parser.add_argument("--provider-record-hash", required=True)
    parser.add_argument("--task-ref", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--receipt", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = Path(args.output)
    receipt_path = Path(args.receipt)
    if output == receipt_path:
        print("BLOCKED:OUTPUT_PATH_INVALID", file=sys.stderr)
        return 2
    try:
        if not output.is_absolute() or output.exists() or not receipt_path.is_absolute() or receipt_path.exists():
            raise BuildBlocked("OUTPUT_PATH_INVALID")
        capture_resolved = Path(args.capture_dir).resolve(strict=False)
        for destination in (output.resolve(strict=False), receipt_path.resolve(strict=False)):
            try:
                destination.relative_to(capture_resolved)
            except ValueError:
                continue
            raise BuildBlocked("OUTPUT_INSIDE_CAPTURE")
        turn, success = build(args)
        _write_json(output, turn)
        success_receipt = _receipt(
            "PASS",
            None,
            **{key: value for key, value in success.items() if key not in {"schema_version", "status", "synthetic", "provider_turn_written"}},
        )
        _write_json(receipt_path, success_receipt)
        return 0
    except BuildBlocked as exc:
        blocked = _receipt("BLOCKED", exc.reason)
        try:
            _write_json(receipt_path, blocked)
        except (BuildBlocked, OSError):
            pass
        print(f"BLOCKED:{exc.reason}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
