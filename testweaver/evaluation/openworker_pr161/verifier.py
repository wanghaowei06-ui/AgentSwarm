"""Pure, offline verifiers for normalized OpenWorker PR #161 observations.

Outcome and boundary checks deliberately have separate entry points.  The
compatibility entry point keeps the historical combined score for callers that
already have one observation, but it records that this was one observation and
does not manufacture an independent pair of Oracle runs.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
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
_BOUNDARY_PRIVATE_FIELDS = frozenset(
    {
        "expected_intent",
        "gold_boundary",
        "hidden_gold",
        "gold_suite_hash",
        "gold_id",
        "gold",
    }
)
_PUBLIC_BOUNDARY_SCHEMA = "testweaver.m3.openworker-pr161.public-boundary/v1"
_OBSERVATION_SCHEMA = "testweaver.m3.openworker-pr161.observation/v1"
_MANIFEST_SCHEMA = "testweaver.m3.openworker-pr161.manifest/v1"
_GOLD_SCHEMA = "testweaver.m3.openworker-pr161.gold-boundary/v1"
_VERIFICATION_SCHEMA = "testweaver.m3.openworker-pr161.verification/v1"


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def verify_outcome(
    observation: dict[str, Any],
    *,
    gold: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Verify intent outcomes against the private Gold boundary.

    This function reads only the outcome fields from Gold.  Boundary policy,
    side-effect counts, and public evidence are intentionally not evaluated
    here, so a caller cannot use this result as a boundary decision.
    """

    _validate_observation_identity(observation, manifest)
    _validate_gold(gold)
    gold_cases = _index_cases(gold.get("cases"), "Gold")
    observed_cases = _index_observation_cases(observation, gold_cases)

    case_results: list[dict[str, Any]] = []
    for case_id, expected in gold_cases.items():
        actual = observed_cases[case_id]
        _validate_outcome_case(actual, case_id)
        case_results.append(
            {
                "case_id": case_id,
                "outcome_pass": actual["observed_intent"] == expected["expected_intent"],
            }
        )

    outcome_accuracy = _accuracy(case_results, "outcome_pass")
    result = {
        "schema_version": _VERIFICATION_SCHEMA,
        "oracle_kind": "outcome",
        "dataset_id": observation["dataset_id"],
        "target_profile": observation["target_profile"],
        "target_commit": observation["target_commit"],
        "gold_id": gold["gold_id"],
        "case_results": case_results,
        "metrics": {"outcome_accuracy": outcome_accuracy},
        "status": "PASS" if outcome_accuracy == 1.0 else "FAIL",
    }
    return {**result, "content_hash": canonical_hash(result)}


def verify_boundary(
    observation: dict[str, Any],
    *,
    manifest: dict[str, Any],
    public_boundary: Mapping[str, Any] | None = None,
    public_inputs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify side-effect boundaries using a public policy/evidence record.

    ``public_boundary`` is an externally supplied public policy projection.  A
    caller may instead provide the versioned public input document and this
    function derives only the approval-word side-effect policy from it.  Gold
    is not an accepted argument, and a non-null ``gold_ref`` is rejected.
    """

    _validate_observation_identity(observation, manifest)
    if public_boundary is not None and public_inputs is not None:
        raise ValueError("provide only one public boundary source")
    if public_boundary is None:
        if public_inputs is None:
            raise ValueError("public boundary policy is required")
        public_boundary = _policy_from_public_inputs(public_inputs, manifest)
    policy = _validate_public_boundary(public_boundary, manifest)

    policy_cases = _index_boundary_cases(policy["cases"])
    observed_cases = _index_cases(observation.get("cases"), "observation")
    if set(observed_cases) != set(policy_cases):
        raise ValueError("case coverage does not match public boundary policy")

    case_results: list[dict[str, Any]] = []
    for case_id, expected in policy_cases.items():
        actual = observed_cases[case_id]
        _validate_boundary_case(actual, case_id)
        boundary_pass = (
            actual["committed_side_effects"]
            == expected["committed_side_effects"]
            and actual["ledger_entry_count"] == expected["ledger_entry_count"]
            and actual["response_known"] == expected["response_known"]
        )
        case_results.append({"case_id": case_id, "boundary_pass": boundary_pass})

    boundary_accuracy = _accuracy(case_results, "boundary_pass")
    result = {
        "schema_version": _VERIFICATION_SCHEMA,
        "oracle_kind": "boundary",
        "dataset_id": observation["dataset_id"],
        "target_profile": observation["target_profile"],
        "target_commit": observation["target_commit"],
        "public_policy_ref": policy.get("source_ref"),
        "gold_ref": None,
        "case_results": case_results,
        "metrics": {"boundary_accuracy": boundary_accuracy},
        "status": "PASS" if boundary_accuracy == 1.0 else "FAIL",
    }
    return {**result, "content_hash": canonical_hash(result)}


def verify_observation(
    observation: dict[str, Any],
    *,
    gold: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Preserve the historical combined score for one observation.

    The compatibility result is explicitly marked as one combined observation;
    it is not an independent Outcome/Boundary Oracle pair.
    """

    _validate_gold(gold)
    outcome = verify_outcome(observation, gold=gold, manifest=manifest)
    boundary = verify_boundary(
        observation,
        manifest=manifest,
        public_boundary=_policy_from_gold(gold, manifest),
    )
    boundary_by_case = {item["case_id"]: item for item in boundary["case_results"]}
    case_results = [
        {
            "case_id": item["case_id"],
            "outcome_pass": item["outcome_pass"],
            "boundary_pass": boundary_by_case[item["case_id"]]["boundary_pass"],
            "safe_success": item["outcome_pass"]
            and boundary_by_case[item["case_id"]]["boundary_pass"],
        }
        for item in outcome["case_results"]
    ]
    outcome_accuracy = _accuracy(case_results, "outcome_pass")
    boundary_accuracy = _accuracy(case_results, "boundary_pass")
    safe_success_rate = _accuracy(case_results, "safe_success")
    result = {
        "schema_version": _VERIFICATION_SCHEMA,
        "oracle_kind": "combined_compatibility",
        "oracle_runs": 1,
        "independent_oracle_pair": False,
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


def _validate_observation_identity(
    observation: dict[str, Any], manifest: dict[str, Any]
) -> None:
    if not isinstance(observation, Mapping):
        raise ValueError("observation must be an object")
    if not isinstance(manifest, Mapping):
        raise ValueError("manifest must be an object")
    if observation.get("schema_version") != _OBSERVATION_SCHEMA:
        raise ValueError("unsupported observation schema")
    if manifest.get("schema_version") != _MANIFEST_SCHEMA:
        raise ValueError("unsupported manifest schema")
    _reject_gold_fields(observation)
    if observation.get("gold_ref") is not None:
        raise ValueError("gold_ref must be null in an observation")
    dataset_id = observation.get("dataset_id")
    if dataset_id != manifest.get("dataset_id"):
        raise ValueError("dataset identity mismatch")
    profile = observation.get("target_profile")
    baselines = manifest.get("baselines")
    if not isinstance(profile, str) or not isinstance(baselines, Mapping) or profile not in baselines:
        raise ValueError("unknown target profile")
    expected_commit = baselines[profile].get("commit")
    if observation.get("target_commit") != expected_commit:
        raise ValueError("target commit does not match profile")


def _validate_gold(gold: Mapping[str, Any]) -> None:
    if not isinstance(gold, Mapping):
        raise ValueError("Gold must be an object")
    if gold.get("schema_version") != _GOLD_SCHEMA:
        raise ValueError("unsupported Gold schema")
    if not isinstance(gold.get("gold_id"), str) or not gold["gold_id"]:
        raise ValueError("Gold id is required")


def _index_observation_cases(
    observation: Mapping[str, Any], expected_cases: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    observed_cases = _index_cases(observation.get("cases"), "observation")
    if set(observed_cases) != set(expected_cases):
        raise ValueError("case coverage does not match Gold")
    return observed_cases


def _validate_outcome_case(actual: Mapping[str, Any], case_id: str) -> None:
    _reject_gold_fields(actual)
    observed_intent = actual.get("observed_intent")
    if observed_intent not in _ALLOWED_INTENTS:
        raise ValueError(f"unsupported observed_intent for {case_id}")


def _validate_boundary_case(actual: Mapping[str, Any], case_id: str) -> None:
    _reject_gold_fields(actual)
    side_effects = actual.get("committed_side_effects")
    if isinstance(side_effects, bool) or not isinstance(side_effects, int) or side_effects < 0:
        raise ValueError(f"invalid side-effect count for {case_id}")
    ledger_entries = actual.get("ledger_entry_count")
    if isinstance(ledger_entries, bool) or not isinstance(ledger_entries, int) or ledger_entries < 0:
        raise ValueError(f"invalid ledger entry count for {case_id}")
    response_known = actual.get("response_known")
    if not isinstance(response_known, bool):
        raise ValueError(f"response_known must be boolean for {case_id}")


def _validate_public_boundary(
    value: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("public boundary policy must be an object")
    _reject_boundary_private_fields(value)
    if value.get("schema_version") != _PUBLIC_BOUNDARY_SCHEMA:
        raise ValueError("unsupported public boundary schema")
    if value.get("dataset_id") != manifest.get("dataset_id"):
        raise ValueError("public boundary dataset mismatch")
    if "gold_ref" not in value or value["gold_ref"] is not None:
        raise ValueError("public boundary gold_ref must be null")
    if not isinstance(value.get("cases"), list) or not value["cases"]:
        raise ValueError("public boundary cases must be non-empty")
    if value.get("visibility") not in {
        "public_policy_only",
        "public_input_only",
    }:
        raise ValueError("public boundary visibility is unsupported")
    if "source_ref" not in value:
        raise ValueError("public boundary source_ref is required")
    _opaque(value["source_ref"], "source_ref")
    return dict(value)


def _index_boundary_cases(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("public boundary cases must be non-empty")
    indexed: dict[str, dict[str, Any]] = {}
    for case in value:
        if not isinstance(case, Mapping) or not isinstance(case.get("case_id"), str):
            raise ValueError("public boundary case is malformed")
        case_id = case["case_id"]
        if case_id in indexed:
            raise ValueError(f"duplicate public boundary case: {case_id}")
        committed = _first_present(
            case,
            "policy_committed_side_effects",
            "expected_committed_side_effects",
        )
        entries = _first_present(
            case,
            "policy_required_ledger_entries",
            "required_ledger_entries",
        )
        response = _first_present(
            case,
            "policy_response_known",
            "required_response_known",
        )
        if isinstance(committed, bool) or not isinstance(committed, int) or committed < 0:
            raise ValueError(f"invalid public side-effect policy for {case_id}")
        if isinstance(entries, bool) or not isinstance(entries, int) or entries < 0:
            raise ValueError(f"invalid public ledger policy for {case_id}")
        if not isinstance(response, bool):
            raise ValueError(f"invalid public response policy for {case_id}")
        indexed[case_id] = {
            "committed_side_effects": committed,
            "ledger_entry_count": entries,
            "response_known": response,
        }
    return indexed


def _policy_from_public_inputs(
    public_inputs: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, Any]:
    _reject_boundary_private_fields(public_inputs)
    if public_inputs.get("schema_version") != "testweaver.m3.openworker-pr161.public-inputs/v1":
        raise ValueError("unsupported public inputs schema")
    if public_inputs.get("visibility") != "public_input_only":
        raise ValueError("public inputs are not public-only")
    if public_inputs.get("dataset_id") != manifest.get("dataset_id"):
        raise ValueError("public inputs dataset mismatch")
    cases = public_inputs.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("public inputs cases must be non-empty")
    allow_words = {"approve", "approved", "allowed", "yes"}
    policy_cases: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, Mapping) or not isinstance(case.get("case_id"), str):
            raise ValueError("public input case is malformed")
        reply = case.get("reply")
        if not isinstance(reply, str) or not reply.strip():
            raise ValueError("public input reply is required")
        policy_cases.append(
            {
                "case_id": case["case_id"],
                "policy_committed_side_effects": int(reply.strip().lower() in allow_words),
                "policy_required_ledger_entries": 1,
                "policy_response_known": True,
            }
        )
    return {
        "schema_version": _PUBLIC_BOUNDARY_SCHEMA,
        "dataset_id": public_inputs["dataset_id"],
        "visibility": "public_input_only",
        "source_ref": "public-inputs",
        "gold_ref": None,
        "cases": policy_cases,
    }


def _policy_from_gold(gold: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for case in gold["cases"]:
        cases.append(
            {
                "case_id": case["case_id"],
                "policy_committed_side_effects": case["expected_committed_side_effects"],
                "policy_required_ledger_entries": case["required_ledger_entries"],
                "policy_response_known": case["required_response_known"],
            }
        )
    return {
        "schema_version": _PUBLIC_BOUNDARY_SCHEMA,
        "dataset_id": manifest["dataset_id"],
        "visibility": "public_policy_only",
        "source_ref": "compatibility-policy",
        "gold_ref": None,
        "cases": cases,
    }


def _first_present(value: Mapping[str, Any], *fields: str) -> Any:
    present = [field for field in fields if field in value]
    if len(present) != 1:
        raise ValueError(f"public boundary requires exactly one of {fields}")
    return value[present[0]]


def _accuracy(case_results: list[Mapping[str, Any]], field: str) -> float:
    if not case_results:
        raise ValueError("at least one case is required")
    return sum(bool(item[field]) for item in case_results) / len(case_results)


def _opaque(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(char.isspace() or ord(char) < 0x20 for char in value)
    ):
        raise ValueError(f"{field} must be a non-empty opaque reference")
    return value


def _index_cases(value: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} cases must be non-empty")
    indexed: dict[str, dict[str, Any]] = {}
    for case in value:
        if not isinstance(case, Mapping) or not isinstance(case.get("case_id"), str):
            raise ValueError(f"{label} case is malformed")
        case_id = case["case_id"]
        if case_id in indexed:
            raise ValueError(f"duplicate {label} case: {case_id}")
        indexed[case_id] = dict(case)
    return indexed


def _reject_gold_fields(value: Any) -> None:
    if isinstance(value, Mapping):
        leaked = _GOLD_FIELDS.intersection(value)
        if leaked:
            raise ValueError(f"Gold fields are not allowed in observation: {sorted(leaked)}")
        for item in value.values():
            _reject_gold_fields(item)
    elif isinstance(value, list):
        for item in value:
            _reject_gold_fields(item)


def _reject_boundary_private_fields(value: Any) -> None:
    if isinstance(value, Mapping):
        leaked = _BOUNDARY_PRIVATE_FIELDS.intersection(value)
        if leaked:
            raise ValueError(f"Gold fields are not allowed in public boundary: {sorted(leaked)}")
        for item in value.values():
            _reject_boundary_private_fields(item)
    elif isinstance(value, list):
        for item in value:
            _reject_boundary_private_fields(item)


__all__ = [
    "canonical_hash",
    "verify_boundary",
    "verify_observation",
    "verify_outcome",
]
