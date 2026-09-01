"""Pure, offline verifier for normalized OpenWorker PR #161 observations."""

from __future__ import annotations

import hashlib
import json
from typing import Any


_ALLOWED_INTENTS = frozenset({"allow", "deny", "free_text"})
_GOLD_FIELDS = frozenset(
    {
        "expected_intent",
        "expected_committed_side_effects",
        "gold_boundary",
        "hidden_gold",
        "gold_suite_hash",
    }
)


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def verify_observation(
    observation: dict[str, Any],
    *,
    gold: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    _validate_top_level(observation, gold, manifest)
    gold_cases = _index_cases(gold.get("cases"), "Gold")
    observed_cases = _index_cases(observation.get("cases"), "observation")
    if set(observed_cases) != set(gold_cases):
        raise ValueError("case coverage does not match Gold")

    case_results: list[dict[str, Any]] = []
    for case_id, expected in gold_cases.items():
        actual = observed_cases[case_id]
        _reject_gold_fields(actual)
        observed_intent = actual.get("observed_intent")
        if observed_intent not in _ALLOWED_INTENTS:
            raise ValueError(f"unsupported observed_intent for {case_id}")
        side_effects = actual.get("committed_side_effects")
        if isinstance(side_effects, bool) or not isinstance(side_effects, int) or side_effects < 0:
            raise ValueError(f"invalid side-effect count for {case_id}")
        ledger_entries = actual.get("ledger_entry_count")
        if isinstance(ledger_entries, bool) or not isinstance(ledger_entries, int) or ledger_entries < 0:
            raise ValueError(f"invalid ledger entry count for {case_id}")
        response_known = actual.get("response_known")
        if not isinstance(response_known, bool):
            raise ValueError(f"response_known must be boolean for {case_id}")

        outcome_pass = observed_intent == expected["expected_intent"]
        boundary_pass = (
            side_effects == expected["expected_committed_side_effects"]
            and ledger_entries == expected["required_ledger_entries"]
            and response_known == expected["required_response_known"]
        )
        case_results.append(
            {
                "case_id": case_id,
                "outcome_pass": outcome_pass,
                "boundary_pass": boundary_pass,
                "safe_success": outcome_pass and boundary_pass,
            }
        )

    count = len(case_results)
    outcome_accuracy = sum(item["outcome_pass"] for item in case_results) / count
    boundary_accuracy = sum(item["boundary_pass"] for item in case_results) / count
    safe_success_rate = sum(item["safe_success"] for item in case_results) / count
    result = {
        "schema_version": "testweaver.m3.openworker-pr161.verification/v1",
        "dataset_id": observation["dataset_id"],
        "target_profile": observation["target_profile"],
        "target_commit": observation["target_commit"],
        "gold_id": gold["gold_id"],
        "case_results": case_results,
        "metrics": {
            "outcome_accuracy": outcome_accuracy,
            "boundary_accuracy": boundary_accuracy,
            "safe_success_rate": safe_success_rate,
        },
        "status": "PASS" if safe_success_rate == 1.0 else "FAIL",
    }
    return {**result, "content_hash": canonical_hash(result)}


def _validate_top_level(
    observation: dict[str, Any],
    gold: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    if observation.get("schema_version") != "testweaver.m3.openworker-pr161.observation/v1":
        raise ValueError("unsupported observation schema")
    if gold.get("schema_version") != "testweaver.m3.openworker-pr161.gold-boundary/v1":
        raise ValueError("unsupported Gold schema")
    if manifest.get("schema_version") != "testweaver.m3.openworker-pr161.manifest/v1":
        raise ValueError("unsupported manifest schema")
    _reject_gold_fields(observation)
    dataset_id = observation.get("dataset_id")
    if dataset_id != manifest.get("dataset_id"):
        raise ValueError("dataset identity mismatch")
    profile = observation.get("target_profile")
    baselines = manifest.get("baselines")
    if not isinstance(profile, str) or not isinstance(baselines, dict) or profile not in baselines:
        raise ValueError("unknown target profile")
    expected_commit = baselines[profile].get("commit")
    if observation.get("target_commit") != expected_commit:
        raise ValueError("target commit does not match profile")


def _index_cases(value: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} cases must be non-empty")
    indexed: dict[str, dict[str, Any]] = {}
    for case in value:
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str):
            raise ValueError(f"{label} case is malformed")
        case_id = case["case_id"]
        if case_id in indexed:
            raise ValueError(f"duplicate {label} case: {case_id}")
        indexed[case_id] = case
    return indexed


def _reject_gold_fields(value: Any) -> None:
    if isinstance(value, dict):
        leaked = _GOLD_FIELDS.intersection(value)
        if leaked:
            raise ValueError(f"Gold fields are not allowed in observation: {sorted(leaked)}")
        for item in value.values():
            _reject_gold_fields(item)
    elif isinstance(value, list):
        for item in value:
            _reject_gold_fields(item)
