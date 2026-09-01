from __future__ import annotations

import copy
import json
import re
import unittest
from pathlib import Path

from testweaver.evaluation.openworker_pr161 import verifier


ROOT = Path(__file__).resolve().parents[3]
ASSET_ROOT = ROOT / "testweaver" / "evaluation" / "openworker_pr161"
PUBLIC_INPUTS = ASSET_ROOT / "public-inputs-v1.json"
GOLD_BOUNDARY = ASSET_ROOT / "gold-boundary-v1.json"
MANIFEST = ASSET_ROOT / "manifest-v1.json"
METRICS = ASSET_ROOT / "metrics-contract-v1.json"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def candidate_from_gold(profile: str, commit: str, gold: dict) -> dict:
    return {
        "schema_version": "testweaver.m3.openworker-pr161.observation/v1",
        "dataset_id": "openworker-pr161-public-inputs",
        "target_profile": profile,
        "target_commit": commit,
        "cases": [
            {
                "case_id": case["case_id"],
                "observed_intent": case["expected_intent"],
                "committed_side_effects": case["expected_committed_side_effects"],
                "ledger_entry_count": 1,
                "response_known": True,
            }
            for case in gold["cases"]
        ],
    }


class OpenWorkerPr161EvaluationTests(unittest.TestCase):
    def test_public_inputs_are_versioned_and_gold_free(self) -> None:
        public = read_json(PUBLIC_INPUTS)
        self.assertEqual(public["schema_version"], "testweaver.m3.openworker-pr161.public-inputs/v1")
        self.assertEqual(public["visibility"], "public_input_only")
        self.assertGreaterEqual(len(public["cases"]), 3)
        serialized = json.dumps(public, ensure_ascii=False).lower()
        for forbidden in ("expected_intent", "expected_committed", "gold_boundary", "hidden_gold"):
            self.assertNotIn(forbidden, serialized)
        for case in public["cases"]:
            self.assertIn("case_id", case)
            self.assertIn("interaction_kind", case)
            self.assertIn("reply", case)

    def test_manifest_records_pinned_vulnerable_fixed_sources(self) -> None:
        manifest = read_json(MANIFEST)
        self.assertEqual(manifest["schema_version"], "testweaver.m3.openworker-pr161.manifest/v1")
        self.assertEqual(manifest["license"]["spdx_id"], "MIT")
        self.assertEqual(
            manifest["agentteams_gap_audit"]["pinned_matching_domain_asset_paths"],
            0,
        )
        self.assertEqual(
            manifest["agentteams_gap_audit"]["observed_main_matching_domain_asset_paths"],
            0,
        )
        self.assertEqual(
            manifest["baselines"]["historical-vulnerable"]["commit"],
            "98445fee112eec07423da5eeef2a3ebba54f6acd",
        )
        self.assertEqual(
            manifest["baselines"]["historical-fixed"]["commit"],
            "38e1f030219c75e7423a9a9813253d8178915db7",
        )
        self.assertEqual(
            manifest["source_files"]["inbox_routing_vulnerable_sha256"],
            "9170af275ab252b338651dd1dc5d357ad1f3a54525ad94f86942f16f8005e519",
        )
        self.assertEqual(
            manifest["source_files"]["inbox_routing_fixed_sha256"],
            "1a75dad625fdb6c9257b3d9225175042579c6a8712d40532aed7e37f3431c98e",
        )

    def test_verifier_scores_clean_observation_and_detects_vulnerable_observation(self) -> None:
        manifest = read_json(MANIFEST)
        gold = read_json(GOLD_BOUNDARY)
        fixed = candidate_from_gold(
            "historical-fixed",
            manifest["baselines"]["historical-fixed"]["commit"],
            gold,
        )
        fixed_result = verifier.verify_observation(fixed, gold=gold, manifest=manifest)
        self.assertEqual(fixed_result["status"], "PASS")
        self.assertEqual(fixed_result["metrics"]["outcome_accuracy"], 1.0)
        self.assertEqual(fixed_result["metrics"]["boundary_accuracy"], 1.0)
        self.assertEqual(fixed_result["metrics"]["safe_success_rate"], 1.0)

        vulnerable = copy.deepcopy(fixed)
        vulnerable["target_profile"] = "historical-vulnerable"
        vulnerable["target_commit"] = manifest["baselines"]["historical-vulnerable"]["commit"]
        vulnerable["cases"][0]["observed_intent"] = "allow"
        vulnerable["cases"][0]["committed_side_effects"] = 1
        vulnerable_result = verifier.verify_observation(vulnerable, gold=gold, manifest=manifest)
        self.assertEqual(vulnerable_result["status"], "FAIL")
        self.assertEqual(vulnerable_result["case_results"][0]["outcome_pass"], False)
        self.assertEqual(vulnerable_result["case_results"][0]["boundary_pass"], False)

    def test_verifier_rejects_duplicate_missing_and_gold_leaking_cases(self) -> None:
        manifest = read_json(MANIFEST)
        gold = read_json(GOLD_BOUNDARY)
        candidate = candidate_from_gold(
            "historical-fixed",
            manifest["baselines"]["historical-fixed"]["commit"],
            gold,
        )

        duplicate = copy.deepcopy(candidate)
        duplicate["cases"].append(copy.deepcopy(duplicate["cases"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            verifier.verify_observation(duplicate, gold=gold, manifest=manifest)

        missing = copy.deepcopy(candidate)
        missing["cases"] = missing["cases"][1:]
        with self.assertRaisesRegex(ValueError, "coverage"):
            verifier.verify_observation(missing, gold=gold, manifest=manifest)

        leaking = copy.deepcopy(candidate)
        leaking["cases"][0]["expected_intent"] = "deny"
        with self.assertRaisesRegex(ValueError, "Gold fields"):
            verifier.verify_observation(leaking, gold=gold, manifest=manifest)

    def test_metrics_contract_is_case_level_and_bounded(self) -> None:
        metrics = read_json(METRICS)
        self.assertEqual(metrics["schema_version"], "testweaver.m3.metrics-contract/v1")
        self.assertEqual(metrics["aggregation"], "macro_over_cases")
        self.assertEqual(
            set(metrics["required_case_fields"]),
            {"case_id", "outcome_pass", "boundary_pass", "safe_success"},
        )
        self.assertEqual(
            set(metrics["metrics"]),
            {"outcome_accuracy", "boundary_accuracy", "safe_success_rate"},
        )

    def test_evaluation_code_has_no_runtime_or_orchestration_dependency(self) -> None:
        source = (ASSET_ROOT / "verifier.py").read_text(encoding="utf-8").lower()
        for forbidden in (
            "subprocess",
            "socket",
            "requests",
            "docker",
            "matrix",
            "taskrun",
            "scheduler",
            "observer",
            "receipt",
        ):
            self.assertNotIn(forbidden, source)

    def test_source_license_record_names_both_licenses_and_no_code_copy(self) -> None:
        source_license = (ASSET_ROOT / "SOURCE-LICENSE.md").read_text(encoding="utf-8")
        self.assertIn("MIT License", source_license)
        self.assertIn("Apache License 2.0", source_license)
        self.assertIn("No OpenWorker source code is copied", source_license)
        self.assertRegex(source_license, r"27157efd241ed1028f20074530315b88c6f5491a")


if __name__ == "__main__":
    unittest.main()
