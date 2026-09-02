"""Normalize already-finished native evaluation exports.

The module accepts data supplied by an external collector and returns a strict
row suitable for :mod:`paired_metrics` plus a sealed, non-secret manifest.  It
does not read files, invoke transports, or change native execution state.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

from testweaver.contracts.validator import canonical_hash
from testweaver.evaluation.paired_metrics import (
    METRIC_NAMES,
    NOT_AVAILABLE,
    PAIRING_FIELDS,
    PairingError,
    compare_pair,
)


SCHEMA_VERSION = "testweaver.m3.native-run-export/v1"
NORMALIZED_SCHEMA_VERSION = "testweaver.m3.native-run-receipt/v1"
PROFILE_NAMES = frozenset({"E0", "E1", "E2", "E3"})
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^\S{1,512}$")

_TOP_FIELDS = frozenset(
    {
        "schema_version",
        "run_id",
        "case_id",
        "input_hash",
        "golden_revision",
        "budget_hash",
        "environment_hash",
        "profile",
        "repetition",
        "run_state",
        "fresh",
        "native",
        "actor",
        "oracle_result_refs",
        "receipt_ref",
        "manifest_ref",
        "evidence_refs",
        "usage",
        "latency_ms",
        "cost",
        "metrics",
    }
)
_REQUIRED_TOP_FIELDS = _TOP_FIELDS - {"usage", "latency_ms", "cost", "metrics"}
_NATIVE_FIELDS = frozenset(
    {
        "project_id",
        "task_id",
        "room_id",
        "project_state",
        "task_state",
        "fresh_ids",
    }
)
_ACTOR_FIELDS = frozenset({"provider", "model", "runtime"})
_REF_FIELDS = frozenset({"ref", "content_hash"})
_USAGE_FIELDS = frozenset(
    {
        "call_count",
        "prompt_tokens",
        "completion_tokens",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cost",
        "model_name",
        "provider_id",
    }
)
_TOKEN_METRICS = frozenset({"input_tokens", "output_tokens", "total_tokens"})
_RATIO_METRICS = frozenset(
    {
        "quality",
        "duplicate_work_rate",
        "hallucination_or_unsupported_claim_block_rate",
        "evidence_completeness",
    }
)
_INTEGER_METRICS = _TOKEN_METRICS
_FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "gold",
        "fixture",
        "synthetic",
        "runner",
        "scheduler",
        "observer",
        "taskrun",
        "prompt",
        "prompt_text",
        "body",
        "content",
        "secret",
        "api_key",
        "apikey",
        "password",
        "authorization",
        "access_token",
    }
)
_MISSING = object()


class LiveReceiptError(ValueError):
    """Raised when an external native export cannot be safely normalized."""


def normalize_native_run_export(
    export: Mapping[str, Any],
    *,
    expected_input_hash: str,
    expected_budget_hash: str,
) -> dict[str, Any]:
    """Validate one completed export and return a paired-metrics projection.

    The expected hashes are supplied by the caller that froze the public input
    and budget.  No default case, identity, result, or run count is invented.
    """

    if not isinstance(export, Mapping):
        raise LiveReceiptError("export must be an object")
    _reject_forbidden_fields(export)
    _check_keys(export, _TOP_FIELDS, _REQUIRED_TOP_FIELDS, "export")
    _require_hash(expected_input_hash, "expected_input_hash")
    _require_hash(expected_budget_hash, "expected_budget_hash")
    if export["schema_version"] != SCHEMA_VERSION:
        raise LiveReceiptError("schema_version is unsupported")

    run_id = _identifier(export["run_id"], "run_id")
    case_id = _identifier(export["case_id"], "case_id")
    input_hash = _hash_value(export["input_hash"], "input_hash")
    golden_revision = _identifier(export["golden_revision"], "golden_revision")
    budget_hash = _hash_value(export["budget_hash"], "budget_hash")
    environment_hash = _hash_value(export["environment_hash"], "environment_hash")
    if input_hash != expected_input_hash:
        raise LiveReceiptError("input_hash does not match expected public input")
    if budget_hash != expected_budget_hash:
        raise LiveReceiptError("budget_hash does not match expected budget")

    profile = export["profile"]
    if profile not in PROFILE_NAMES:
        raise LiveReceiptError("profile must be one of E0, E1, E2, E3")
    repetition = export["repetition"]
    if type(repetition) is not int or repetition < 1:
        raise LiveReceiptError("repetition must be a positive integer")
    if export["run_state"] != "completed":
        raise LiveReceiptError("run_state must be completed")
    if export["fresh"] is not True:
        raise LiveReceiptError("fresh must be true")

    native = _validate_native(export["native"], run_id)
    actor = _validate_actor(export["actor"])
    oracle_refs = _validate_refs(export["oracle_result_refs"], "oracle_result_refs")
    evidence_refs = _validate_refs(export["evidence_refs"], "evidence_refs")
    receipt_ref = _validate_ref(export["receipt_ref"], "receipt_ref")
    manifest_ref = _validate_ref(export["manifest_ref"], "manifest_ref")

    usage = _normalize_usage(export.get("usage"))
    usage_present = any(
        usage[field] != NOT_AVAILABLE
        for field in ("call_count", "input_tokens", "output_tokens", "total_tokens", "cost")
    )
    explicit_cost = _normalize_number(export.get("cost"), "cost")
    cost = _coalesce_observation(
        explicit_cost,
        usage["cost"],
        "cost",
    )
    latency_ms = _normalize_number(export.get("latency_ms"), "latency_ms")

    supplied_metrics = export.get("metrics", {})
    if not isinstance(supplied_metrics, Mapping):
        raise LiveReceiptError("metrics must be an object")
    unknown_metrics = set(supplied_metrics) - set(METRIC_NAMES)
    if unknown_metrics:
        raise LiveReceiptError("metrics has unknown fields")
    metric_values = {
        name: _metric_value(supplied_metrics.get(name, NOT_AVAILABLE), name)
        for name in METRIC_NAMES
    }

    normalized_metrics = _merge_observations(
        metric_values,
        usage=usage,
        usage_present=usage_present,
        cost=cost,
        latency_ms=latency_ms,
    )
    row = {
        "run_id": run_id,
        "case_id": case_id,
        "input_hash": input_hash,
        "golden_revision": golden_revision,
        "budget_hash": budget_hash,
        "environment_hash": environment_hash,
        "profile": profile,
        "repetition": repetition,
        "frozen": True,
        "receipt_ref": receipt_ref,
        "manifest_ref": manifest_ref,
        "oracle_result_refs": oracle_refs,
        "metrics": normalized_metrics,
    }
    try:
        compare_pair(row, row)
    except PairingError as error:
        raise LiveReceiptError("normalized row is incompatible with paired metrics") from error

    manifest_payload = {
        "schema_version": "testweaver.m3.native-run-manifest/v1",
        "source": "external_native_run_export",
        "run_id": run_id,
        "case_id": case_id,
        "input_hash": input_hash,
        "golden_revision": golden_revision,
        "budget_hash": budget_hash,
        "environment_hash": environment_hash,
        "profile": profile,
        "repetition": repetition,
        "run_state": "completed",
        "fresh": True,
        "native": native,
        "actor": actor,
        "usage": usage,
        "latency_ms": latency_ms,
        "evidence_refs": evidence_refs,
        "oracle_result_refs": oracle_refs,
        "receipt_ref": receipt_ref,
        "manifest_ref": manifest_ref,
    }
    manifest = {
        **manifest_payload,
        "content_hash": canonical_hash(manifest_payload),
    }
    payload = {
        "schema_version": NORMALIZED_SCHEMA_VERSION,
        "rows": [row],
        "manifest": manifest,
    }
    return {**payload, "content_hash": canonical_hash(payload)}


def normalize_native_run_exports(
    exports: Iterable[Mapping[str, Any]],
    *,
    expected_input_hash: str,
    expected_budget_hash: str,
) -> dict[str, Any]:
    """Normalize a caller-selected batch and reject reused native identities."""

    normalized = [
        normalize_native_run_export(
            export,
            expected_input_hash=expected_input_hash,
            expected_budget_hash=expected_budget_hash,
        )
        for export in exports
    ]
    if not normalized:
        raise LiveReceiptError("at least one export is required")

    rows: list[dict[str, Any]] = []
    manifests: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_pair_keys: set[tuple[Any, ...]] = set()
    for item in normalized:
        row = item["rows"][0]
        manifest = item["manifest"]
        native_ids = tuple(manifest["native"][field] for field in ("project_id", "task_id", "room_id"))
        all_ids = (row["run_id"], *native_ids)
        if any(value in seen_ids for value in all_ids):
            raise LiveReceiptError("duplicate fresh native identity")
        if len(set(all_ids)) != len(all_ids):
            raise LiveReceiptError("duplicate identity within normalized export")
        pair_key = tuple(row[field] for field in PAIRING_FIELDS)
        if pair_key in seen_pair_keys:
            raise LiveReceiptError("duplicate paired observation")
        seen_ids.update(all_ids)
        seen_pair_keys.add(pair_key)
        rows.append(row)
        manifests.append(manifest)

    payload = {
        "schema_version": "testweaver.m3.native-run-manifest-batch/v1",
        "rows": rows,
        "manifests": manifests,
    }
    return {**payload, "content_hash": canonical_hash(payload)}


def _check_keys(
    value: Mapping[str, Any], allowed: frozenset[str], required: frozenset[str], label: str
) -> None:
    keys = set(value)
    if not all(isinstance(key, str) for key in keys):
        raise LiveReceiptError(f"{label} has a non-string field")
    unknown = keys - allowed
    missing = required - keys
    if unknown:
        raise LiveReceiptError(f"{label} has unknown fields")
    if missing:
        raise LiveReceiptError(f"{label} is missing required fields")


def _reject_forbidden_fields(value: Any, path: str = "export") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise LiveReceiptError("field names must be strings")
            normalized = key.lower().replace("-", "_")
            if normalized in _FORBIDDEN_FIELD_NAMES:
                raise LiveReceiptError(f"forbidden field at {path}.{key}")
            _reject_forbidden_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_fields(child, f"{path}[{index}]")


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise LiveReceiptError(f"{field} must be an opaque identifier")
    return value


def _hash_value(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise LiveReceiptError(f"{field} must be a sha256 digest")
    return value


def _require_hash(value: Any, field: str) -> None:
    _hash_value(value, field)


def _validate_ref(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != _REF_FIELDS:
        raise LiveReceiptError(f"{field} must contain only ref and content_hash")
    return {
        "ref": _identifier(value["ref"], f"{field}.ref"),
        "content_hash": _hash_value(value["content_hash"], f"{field}.content_hash"),
    }


def _validate_refs(value: Any, field: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise LiveReceiptError(f"{field} must be a non-empty list")
    return [_validate_ref(item, f"{field}[{index}]") for index, item in enumerate(value)]


def _validate_native(value: Any, run_id: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise LiveReceiptError("native must be an object")
    _check_keys(value, _NATIVE_FIELDS, _NATIVE_FIELDS, "native")
    project_id = _identifier(value["project_id"], "native.project_id")
    task_id = _identifier(value["task_id"], "native.task_id")
    room_id = _identifier(value["room_id"], "native.room_id")
    if len({run_id, project_id, task_id, room_id}) != 4:
        raise LiveReceiptError("native identities must be fresh and distinct")
    if value["fresh_ids"] is not True:
        raise LiveReceiptError("native.fresh_ids must be true")
    for field in ("project_state", "task_state"):
        state = value[field]
        if not isinstance(state, str) or state not in TERMINAL_STATES:
            raise LiveReceiptError(f"native.{field} must be terminal")
    return {
        "project_id": project_id,
        "task_id": task_id,
        "room_id": room_id,
        "project_state": value["project_state"],
        "task_state": value["task_state"],
        "fresh_ids": True,
        "read_only": True,
    }


def _validate_actor(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise LiveReceiptError("actor must be an object")
    _check_keys(value, _ACTOR_FIELDS, _ACTOR_FIELDS, "actor")
    return {
        field: _identifier(value[field], f"actor.{field}")
        for field in ("provider", "model", "runtime")
    }


def _normalize_usage(value: Any) -> dict[str, int | float | str]:
    records = _usage_records(value)
    if not records:
        return {
            "call_count": NOT_AVAILABLE,
            "input_tokens": NOT_AVAILABLE,
            "output_tokens": NOT_AVAILABLE,
            "total_tokens": NOT_AVAILABLE,
            "cost": NOT_AVAILABLE,
        }

    input_tokens = _sum_if_complete(records, "input_tokens")
    output_tokens = _sum_if_complete(records, "output_tokens")
    if input_tokens != NOT_AVAILABLE and output_tokens != NOT_AVAILABLE:
        total_tokens: int | str = input_tokens + output_tokens
    else:
        total_tokens = _sum_if_complete(records, "total_tokens")
    return {
        "call_count": _sum_if_complete(records, "call_count"),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cost": _sum_if_complete(records, "cost"),
    }


def _usage_records(value: Any) -> list[dict[str, int | float | None]]:
    if value is None:
        return []
    if isinstance(value, list):
        records: list[dict[str, int | float | None]] = []
        for child in value:
            if child is None:
                records.append(_empty_usage_record())
            else:
                records.extend(_usage_records(child))
        return records
    if not isinstance(value, Mapping):
        raise LiveReceiptError("usage has an unsupported shape")

    keys = set(value)
    if keys & _USAGE_FIELDS:
        unknown = keys - _USAGE_FIELDS
        if unknown:
            raise LiveReceiptError("usage record has unknown fields")
        has_session_tokens = bool(keys & {"input_tokens", "output_tokens"})
        has_aggregate_tokens = bool(keys & {"prompt_tokens", "completion_tokens"})
        if has_session_tokens and has_aggregate_tokens:
            raise LiveReceiptError("usage mixes incompatible token shapes")
        if not has_session_tokens and not has_aggregate_tokens and not keys & {
            "total_tokens",
            "cost",
            "call_count",
        }:
            raise LiveReceiptError("usage record has no measurable fields")
        input_value = value.get("input_tokens", value.get("prompt_tokens"))
        output_value = value.get("output_tokens", value.get("completion_tokens"))
        for field in ("model_name", "provider_id"):
            if field in value and value[field] is not None:
                _identifier(value[field], f"usage.{field}")
        return [
            {
                "call_count": _token_count(value.get("call_count"), "usage.call_count"),
                "input_tokens": _token_count(input_value, "usage.input_tokens"),
                "output_tokens": _token_count(output_value, "usage.output_tokens"),
                "total_tokens": _token_count(value.get("total_tokens"), "usage.total_tokens"),
                "cost": _non_negative_number(value.get("cost"), "usage.cost"),
            }
        ]

    records = []
    for key, child in value.items():
        if not isinstance(key, str):
            raise LiveReceiptError("usage keys must be strings")
        if child is None:
            records.append(_empty_usage_record())
            continue
        if not isinstance(child, (Mapping, list)):
            raise LiveReceiptError("usage contains an unrecognized scalar")
        records.extend(_usage_records(child))
    return records


def _empty_usage_record() -> dict[str, int | float | None]:
    return {
        "call_count": None,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "cost": None,
    }


def _token_count(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise LiveReceiptError(f"{field} must be a non-negative integer")
    return value


def _non_negative_number(value: Any, field: str) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LiveReceiptError(f"{field} must be a finite number")
    if not math.isfinite(float(value)) or value < 0:
        raise LiveReceiptError(f"{field} must be a finite non-negative number")
    return value


def _sum_if_complete(records: list[Mapping[str, Any]], field: str) -> int | float | str:
    values = [record.get(field) for record in records]
    if any(value is None for value in values):
        return NOT_AVAILABLE
    return sum(values)


def _normalize_number(value: Any, field: str) -> int | float | str:
    if value is None or value is _MISSING:
        return NOT_AVAILABLE
    return _non_negative_number(value, field)  # type: ignore[return-value]


def _coalesce_observation(
    first: int | float | str, second: int | float | str, field: str
) -> int | float | str:
    if first != NOT_AVAILABLE and second != NOT_AVAILABLE and first != second:
        raise LiveReceiptError(f"{field} observations disagree")
    return first if first != NOT_AVAILABLE else second


def _metric_value(value: Any, field: str) -> int | float | str:
    if value is None or value == NOT_AVAILABLE:
        return NOT_AVAILABLE
    if field in _INTEGER_METRICS:
        if type(value) is not int or value < 0:
            raise LiveReceiptError(f"metrics.{field} must be a non-negative integer")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LiveReceiptError(f"metrics.{field} must be a finite number")
    if not math.isfinite(float(value)):
        raise LiveReceiptError(f"metrics.{field} must be finite")
    if field in _RATIO_METRICS and not 0 <= value <= 1:
        raise LiveReceiptError(f"metrics.{field} must be between zero and one")
    if field in {"coordination_overhead", "cost", "latency_ms"} and value < 0:
        raise LiveReceiptError(f"metrics.{field} must be non-negative")
    return value


def _merge_observations(
    metrics: Mapping[str, int | float | str],
    *,
    usage: Mapping[str, int | float | str],
    usage_present: bool,
    cost: int | float | str,
    latency_ms: int | float | str,
) -> dict[str, int | float | str]:
    merged = dict(metrics)
    if not usage_present and any(metrics[field] != NOT_AVAILABLE for field in _TOKEN_METRICS):
        raise LiveReceiptError("token metrics require usage")
    for field in _TOKEN_METRICS:
        observed = usage[field]
        supplied = metrics[field]
        if supplied != NOT_AVAILABLE and observed == NOT_AVAILABLE:
            raise LiveReceiptError(f"metrics.{field} has no usage observation")
        if supplied != NOT_AVAILABLE and observed != NOT_AVAILABLE and supplied != observed:
            raise LiveReceiptError(f"metrics.{field} disagrees with usage")
        merged[field] = supplied if supplied != NOT_AVAILABLE else observed

    supplied_cost = metrics["cost"]
    if supplied_cost != NOT_AVAILABLE and cost == NOT_AVAILABLE:
        raise LiveReceiptError("cost metric has no cost observation")
    if supplied_cost != NOT_AVAILABLE and cost != NOT_AVAILABLE and supplied_cost != cost:
        raise LiveReceiptError("metrics.cost disagrees with cost observation")
    merged["cost"] = supplied_cost if supplied_cost != NOT_AVAILABLE else cost

    supplied_latency = metrics["latency_ms"]
    if supplied_latency != NOT_AVAILABLE and latency_ms == NOT_AVAILABLE:
        raise LiveReceiptError("latency metric has no latency observation")
    if supplied_latency != NOT_AVAILABLE and latency_ms != NOT_AVAILABLE and supplied_latency != latency_ms:
        raise LiveReceiptError("metrics.latency_ms disagrees with latency observation")
    merged["latency_ms"] = supplied_latency if supplied_latency != NOT_AVAILABLE else latency_ms
    return merged
