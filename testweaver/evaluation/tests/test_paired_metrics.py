from __future__ import annotations

import copy
import inspect
import json
import unittest
from pathlib import Path

from testweaver.contracts.validator import canonical_hash
import testweaver.evaluation.paired_metrics as paired_metrics
from testweaver.evaluation.paired_metrics import (
    METRIC_NAMES,
    METRIC_UNITS,
    NOT_AVAILABLE,
    PairingError,
    compare_pair,
    compare_paired_runs,
)


_HASH = "sha256:" + "a" * 64
_SCHEMA = Path(__file__).resolve().parents[1] / "paired-metrics-v1.json"


def _ref(name: str) -> dict[str, str]:
    return {"ref": f"evidence/{name}", "content_hash": _HASH}


def _run(run_id: str, *, repetition: int = 1, metrics: dict | None = None) -> dict:
    return {
        "run_id": run_id,
        "case_id": "case-alpha",
        "input_hash": _HASH,
        "golden_revision": "golden-v1",
        "budget_hash": _HASH,
        "environment_hash": _HASH,
        "profile": "native-profile",
        "repetition": repetition,
        "frozen": True,
        "receipt_ref": _ref(f"{run_id}/receipt.txt"),
        "manifest_ref": _ref(f"{run_id}/manifest.json"),
        "oracle_result_refs": [_ref(f"{run_id}/outcome.json"), _ref(f"{run_id}/boundary.json")],
        "metrics": metrics or {},
    }


class PairedMetricsTests(unittest.TestCase):
    def test_exact_pairing_and_metric_deltas_are_offline(self) -> None:
        baseline = _run(
            "baseline-1",
            metrics={
                "quality": 0.6,
                "duplicate_work_rate": 0.5,
                "hallucination_or_unsupported_claim_block_rate": 0.0,
                "coordination_overhead": 4,
                "input_tokens": 10,
                "output_tokens": 20,
                "cost": 1.2,
                "latency_ms": 100,
                "evidence_completeness": 0.5,
                "net_value": 0.4,
            },
        )
        treatment = _run(
            "treatment-1",
            metrics={
                "quality": 0.8,
                "duplicate_work_rate": 0.25,
                "hallucination_or_unsupported_claim_block_rate": 0.5,
                "coordination_overhead": 6,
                "input_tokens": 15,
                "output_tokens": 25,
                "cost": 1.7,
                "latency_ms": 140,
                "evidence_completeness": 0.75,
                "net_value": 0.6,
            },
        )

        result = compare_pair(baseline, treatment)

        self.assertEqual(
            result["pairing_key"],
            {
                "case_id": "case-alpha",
                "input_hash": _HASH,
                "golden_revision": "golden-v1",
                "budget_hash": _HASH,
                "environment_hash": _HASH,
                "repetition": 1,
            },
        )
        self.assertEqual(result["metrics"]["total_tokens"]["baseline"], 30)
        self.assertEqual(result["metrics"]["total_tokens"]["treatment"], 40)
        self.assertEqual(result["metrics"]["total_tokens"]["delta"], 10)
        self.assertAlmostEqual(result["metrics"]["quality"]["delta"], 0.2)
        self.assertAlmostEqual(result["metrics"]["net_value"]["delta"], 0.2)
        self.assertEqual(result["causal_inference"]["status"], NOT_AVAILABLE)

    def test_missing_metrics_are_not_available(self) -> None:
        baseline = _run("baseline-2", metrics={"input_tokens": 12})
        treatment = _run("treatment-2", metrics={"output_tokens": 9})

        result = compare_pair(baseline, treatment)

        for metric in (
            "quality",
            "cost",
            "latency_ms",
            "evidence_completeness",
            "total_tokens",
        ):
            self.assertEqual(result["metrics"][metric]["baseline"], NOT_AVAILABLE)
            self.assertEqual(result["metrics"][metric]["treatment"], NOT_AVAILABLE)
            self.assertEqual(result["metrics"][metric]["delta"], NOT_AVAILABLE)

    def test_profile_is_a_comparison_dimension_not_a_pairing_key(self) -> None:
        baseline = _run("baseline-3")
        treatment = _run("treatment-3")
        treatment["profile"] = "other-profile"
        result = compare_pair(baseline, treatment)
        self.assertEqual(result["pairing_key"]["case_id"], "case-alpha")
        self.assertEqual(result["baseline"]["profile"], "native-profile")
        self.assertEqual(result["treatment"]["profile"], "other-profile")

        treatment["environment_hash"] = "sha256:" + "b" * 64
        with self.assertRaisesRegex(PairingError, "pairing key"):
            compare_pair(baseline, treatment)

        duplicate = _run("baseline-duplicate")
        with self.assertRaisesRegex(PairingError, "duplicate"):
            compare_paired_runs([baseline, duplicate], [treatment])

    def test_unmatched_pairs_are_not_cross_matched(self) -> None:
        baseline = _run("baseline-4", repetition=1)
        treatment = _run("treatment-4", repetition=2)
        with self.assertRaisesRegex(PairingError, "matching pairing keys"):
            compare_paired_runs([baseline], [treatment])

    def test_frozen_references_are_required_and_unknown_orchestration_fields_rejected(self) -> None:
        for forbidden_field in ("runner", "scheduler", "gold", "fixture", "synthetic"):
            baseline = _run("baseline-5")
            treatment = _run("treatment-5")
            baseline[forbidden_field] = "must-not-be-here"
            with self.assertRaisesRegex(PairingError, "unknown fields"):
                compare_pair(baseline, treatment)

        baseline = _run("baseline-6")
        baseline["frozen"] = False
        with self.assertRaisesRegex(PairingError, "frozen"):
            compare_pair(baseline, treatment)

    def test_multi_pair_output_is_descriptive_and_does_not_mutate_inputs(self) -> None:
        baseline = [_run("baseline-7"), _run("baseline-8", repetition=2)]
        treatment = [_run("treatment-7"), _run("treatment-8", repetition=2)]
        original = copy.deepcopy((baseline, treatment))

        result = compare_paired_runs(baseline, treatment)

        self.assertEqual(len(result["pairs"]), 2)
        self.assertEqual(result["causal_inference"]["status"], NOT_AVAILABLE)
        self.assertEqual(result["aggregate"]["quality"]["baseline"], NOT_AVAILABLE)
        self.assertEqual((baseline, treatment), original)

    def test_output_schema_and_content_hash_are_consistent(self) -> None:
        result = compare_paired_runs([_run("baseline-9")], [_run("treatment-9")])
        schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))

        self.assertEqual(schema["properties"]["schema_version"]["const"], result["schema_version"])
        self.assertEqual(schema["properties"]["pairing_fields"]["const"], list(result["pairing_fields"]))
        self.assertEqual(result["metric_units"], METRIC_UNITS)
        self.assertEqual(
            set(schema["$defs"]["MetricSet"]["required"]),
            set(METRIC_NAMES),
        )
        payload = {key: value for key, value in result.items() if key != "content_hash"}
        self.assertEqual(result["content_hash"], canonical_hash(payload))

    def test_comparator_has_no_runtime_or_orchestration_dependency(self) -> None:
        source = inspect.getsource(paired_metrics).lower()
        for forbidden in (
            "subprocess",
            "socket",
            "requests",
            "docker",
            "matrix",
            "taskrun",
            "scheduler",
            "observer",
            "hero",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
