"""Pure offline comparison of two frozen, already-completed native runs.

The caller supplies facts extracted from a frozen receipt/manifest and Oracle
result references. This module never dereferences those references and has no
transport, task, room, model, or orchestration side effect.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

from testweaver.contracts.validator import canonical_hash


NOT_AVAILABLE = "NOT_AVAILABLE"
SCHEMA_VERSION = "testweaver.m3.paired-comparison/v1"
PAIRING_FIELDS = (
    "case_id",
    "input_hash",
    "golden_revision",
    "budget_hash",
    "environment_hash",
    "repetition",
)
METRIC_NAMES = (
    "quality",
    "duplicate_work_rate",
    "hallucination_or_unsupported_claim_block_rate",
    "coordination_overhead",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cost",
    "latency_ms",
    "evidence_completeness",
    "net_value",
)
METRIC_UNITS = {
    "quality": "ratio_0_to_1",
    "duplicate_work_rate": "ratio_0_to_1",
    "hallucination_or_unsupported_claim_block_rate": "ratio_0_to_1",
    "coordination_overhead": "native_coordination_units",
    "input_tokens": "tokens",
    "output_tokens": "tokens",
    "total_tokens": "tokens",
    "cost": "cost_units",
    "latency_ms": "milliseconds",
    "evidence_completeness": "ratio_0_to_1",
    "net_value": "value_units",
}


class PairingError(ValueError):
    """Raised when frozen run observations cannot be safely compared."""


_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_RUN_FIELDS = frozenset(
    {
        "run_id",
        "case_id",
        "input_hash",
        "golden_revision",
        "budget_hash",
        "environment_hash",
        "profile",
        "repetition",
        "frozen",
        "receipt_ref",
        "manifest_ref",
        "oracle_result_refs",
        "metrics",
    }
)
_REF_FIELDS = frozenset({"ref", "content_hash"})
_METRIC_FIELDS = frozenset(METRIC_NAMES)
_RATIO_METRICS = frozenset(
    {
        "quality",
        "duplicate_work_rate",
        "hallucination_or_unsupported_claim_block_rate",
        "evidence_completeness",
    }
)
_INTEGER_METRICS = frozenset({"input_tokens", "output_tokens", "total_tokens"})


def compare_pair(
    baseline: Mapping[str, Any], treatment: Mapping[str, Any]
) -> dict[str, Any]:
    """Compare one exact pair without reading or modifying either input."""

    baseline_normalized = _validate_run("baseline", baseline)
    treatment_normalized = _validate_run("treatment", treatment)
    baseline_key = _pairing_key(baseline_normalized)
    treatment_key = _pairing_key(treatment_normalized)
    if baseline_key != treatment_key:
        raise PairingError("baseline and treatment pairing key must match exactly")

    return _pair_result(baseline_normalized, treatment_normalized, baseline_key)


def compare_paired_runs(
    baseline_runs: Iterable[Mapping[str, Any]],
    treatment_runs: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Pair runs by all declared fields and return descriptive metrics only.

    Missing metric values remain ``NOT_AVAILABLE``. A mismatched or duplicate
    pairing key is rejected rather than cross-matched. The result deliberately
    carries no causal conclusion, even when more than one pair is supplied.
    """

    baseline_index = _index_runs("baseline", baseline_runs)
    treatment_index = _index_runs("treatment", treatment_runs)
    if set(baseline_index) != set(treatment_index):
        raise PairingError("baseline and treatment must have matching pairing keys")

    pairs = tuple(
        _pair_result(baseline_index[key], treatment_index[key], key)
        for key in baseline_index
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "comparison_mode": "offline_frozen_references",
        "pairing_fields": list(PAIRING_FIELDS),
        "metric_units": dict(METRIC_UNITS),
        "pairs": list(pairs),
        "aggregate": _aggregate(pairs),
        "causal_inference": {
            "status": NOT_AVAILABLE,
            "reason": "paired_observation_does_not_establish_causality",
        },
    }
    return {**payload, "content_hash": canonical_hash(payload)}


def _validate_run(label: str, run: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(run, Mapping):
        raise PairingError(f"{label} run must be an object")
    unknown = set(run) - _RUN_FIELDS
    missing = _RUN_FIELDS - set(run)
    if unknown:
        raise PairingError(f"{label} run has unknown fields: {sorted(unknown)}")
    if missing:
        raise PairingError(f"{label} run is missing fields: {sorted(missing)}")

    normalized = dict(run)
    _require_identifier(normalized["run_id"], f"{label}.run_id")
    _require_identifier(normalized["case_id"], f"{label}.case_id")
    _require_hash(normalized["input_hash"], f"{label}.input_hash")
    _require_identifier(normalized["golden_revision"], f"{label}.golden_revision")
    _require_hash(normalized["budget_hash"], f"{label}.budget_hash")
    _require_hash(normalized["environment_hash"], f"{label}.environment_hash")
    _require_identifier(normalized["profile"], f"{label}.profile")
    if type(normalized["repetition"]) is not int or normalized["repetition"] < 1:
        raise PairingError(f"{label}.repetition must be a positive integer")
    if normalized["frozen"] is not True:
        raise PairingError(f"{label}.frozen must be true")
    _validate_ref(normalized["receipt_ref"], f"{label}.receipt_ref")
    _validate_ref(normalized["manifest_ref"], f"{label}.manifest_ref")
    oracle_refs = normalized["oracle_result_refs"]
    if not isinstance(oracle_refs, list) or not oracle_refs:
        raise PairingError(f"{label}.oracle_result_refs must be non-empty")
    for index, reference in enumerate(oracle_refs):
        _validate_ref(reference, f"{label}.oracle_result_refs[{index}]")

    metrics = normalized["metrics"]
    if not isinstance(metrics, Mapping):
        raise PairingError(f"{label}.metrics must be an object")
    unknown_metrics = set(metrics) - _METRIC_FIELDS
    if unknown_metrics:
        raise PairingError(f"{label}.metrics has unknown fields: {sorted(unknown_metrics)}")
    normalized["metrics"] = _normalize_metrics(label, metrics)
    return normalized


def _normalize_metrics(label: str, metrics: Mapping[str, Any]) -> dict[str, Any]:
    normalized = {
        name: _normalize_metric(label, name, metrics.get(name, NOT_AVAILABLE))
        for name in METRIC_NAMES
    }
    input_tokens = normalized["input_tokens"]
    output_tokens = normalized["output_tokens"]
    total_tokens = normalized["total_tokens"]
    if total_tokens == NOT_AVAILABLE and input_tokens != NOT_AVAILABLE and output_tokens != NOT_AVAILABLE:
        normalized["total_tokens"] = input_tokens + output_tokens
    elif (
        total_tokens != NOT_AVAILABLE
        and input_tokens != NOT_AVAILABLE
        and output_tokens != NOT_AVAILABLE
        and total_tokens != input_tokens + output_tokens
    ):
        raise PairingError(f"{label}.metrics.total_tokens does not equal input plus output")
    return normalized


def _normalize_metric(label: str, name: str, value: Any) -> int | float | str:
    if value is None or value == NOT_AVAILABLE:
        return NOT_AVAILABLE
    if name in _INTEGER_METRICS:
        if type(value) is not int or value < 0:
            raise PairingError(f"{label}.metrics.{name} must be a non-negative integer")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PairingError(f"{label}.metrics.{name} must be a finite number")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise PairingError(f"{label}.metrics.{name} must be a finite number")
    if name in _RATIO_METRICS and not 0.0 <= numeric <= 1.0:
        raise PairingError(f"{label}.metrics.{name} must be between zero and one")
    if name in {"coordination_overhead", "cost", "latency_ms"} and numeric < 0.0:
        raise PairingError(f"{label}.metrics.{name} must be non-negative")
    return numeric


def _validate_ref(value: Any, field: str) -> None:
    if not isinstance(value, Mapping) or set(value) != _REF_FIELDS:
        raise PairingError(f"{field} must contain only ref and content_hash")
    _require_identifier(value["ref"], f"{field}.ref")
    _require_hash(value["content_hash"], f"{field}.content_hash")


def _require_identifier(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise PairingError(f"{field} must be a non-empty opaque identifier")


def _require_hash(value: Any, field: str) -> None:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise PairingError(f"{field} must be a sha256 digest")


def _pairing_key(run: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(run[field] for field in PAIRING_FIELDS)


def _index_runs(
    label: str, runs: Iterable[Mapping[str, Any]]
) -> dict[tuple[Any, ...], dict[str, Any]]:
    indexed: dict[tuple[Any, ...], dict[str, Any]] = {}
    for run in runs:
        normalized = _validate_run(label, run)
        key = _pairing_key(normalized)
        if key in indexed:
            raise PairingError(f"duplicate {label} pairing key")
        indexed[key] = normalized
    return indexed


def _pair_result(
    baseline: Mapping[str, Any], treatment: Mapping[str, Any], key: tuple[Any, ...]
) -> dict[str, Any]:
    return {
        "pairing_key": dict(zip(PAIRING_FIELDS, key, strict=True)),
        "baseline": _run_projection(baseline),
        "treatment": _run_projection(treatment),
        "metrics": {
            name: _metric_comparison(baseline["metrics"][name], treatment["metrics"][name])
            for name in METRIC_NAMES
        },
        "causal_inference": {
            "status": NOT_AVAILABLE,
            "reason": "paired_observation_does_not_establish_causality",
        },
    }


def _run_projection(run: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "run_id": run["run_id"],
        "profile": run["profile"],
        "frozen": True,
        "receipt_ref": dict(run["receipt_ref"]),
        "manifest_ref": dict(run["manifest_ref"]),
        "oracle_result_refs": [dict(reference) for reference in run["oracle_result_refs"]],
    }


def _metric_comparison(baseline: Any, treatment: Any) -> dict[str, Any]:
    delta: Any = NOT_AVAILABLE
    if baseline != NOT_AVAILABLE and treatment != NOT_AVAILABLE:
        delta = treatment - baseline
    return {"baseline": baseline, "treatment": treatment, "delta": delta}


def _aggregate(pairs: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    pair_list = tuple(pairs)
    result: dict[str, dict[str, Any]] = {}
    for name in METRIC_NAMES:
        baseline_values = [
            pair["metrics"][name]["baseline"]
            for pair in pair_list
            if pair["metrics"][name]["baseline"] != NOT_AVAILABLE
        ]
        treatment_values = [
            pair["metrics"][name]["treatment"]
            for pair in pair_list
            if pair["metrics"][name]["treatment"] != NOT_AVAILABLE
        ]
        delta_values = [
            pair["metrics"][name]["delta"]
            for pair in pair_list
            if pair["metrics"][name]["delta"] != NOT_AVAILABLE
        ]
        result[name] = {
            "baseline": _mean(baseline_values),
            "treatment": _mean(treatment_values),
            "delta": _mean(delta_values),
        }
    return result


def _mean(values: list[int | float]) -> float | str:
    if not values:
        return NOT_AVAILABLE
    return sum(values) / len(values)
