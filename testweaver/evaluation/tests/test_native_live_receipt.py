from __future__ import annotations

import copy
import inspect
import unittest

from testweaver.contracts.validator import canonical_hash
from testweaver.evaluation import native_live_receipt
from testweaver.evaluation.native_live_receipt import (
    LiveReceiptError,
    normalize_native_run_export,
    normalize_native_run_exports,
)
from testweaver.evaluation.paired_metrics import NOT_AVAILABLE, compare_pair


_INPUT_HASH = "sha256:" + "a" * 64
_BUDGET_HASH = "sha256:" + "b" * 64
_CONTENT_HASH = "sha256:" + "c" * 64


def _ref(name: str) -> dict[str, str]:
    return {"ref": f"evidence/{name}", "content_hash": _CONTENT_HASH}


def _export(*, run_id: str = "run-1", repetition: int = 1) -> dict:
    return {
        "schema_version": "testweaver.m3.native-run-export/v1",
        "run_id": run_id,
        "case_id": "openworker-pr161-public-inputs",
        "input_hash": _INPUT_HASH,
        "golden_revision": "golden-v1",
        "budget_hash": _BUDGET_HASH,
        "environment_hash": _CONTENT_HASH,
        "profile": "E3",
        "repetition": repetition,
        "run_state": "completed",
        "fresh": True,
        "native": {
            "project_id": f"project-{run_id}",
            "task_id": f"task-{run_id}",
            "room_id": f"!room-{run_id}:matrix.example",
            "project_state": "completed",
            "task_state": "completed",
            "fresh_ids": True,
        },
        "actor": {
            "provider": "provider-ref",
            "model": "model-ref",
            "runtime": "qwenpaw",
        },
        "oracle_result_refs": [_ref(f"{run_id}/outcome"), _ref(f"{run_id}/boundary")],
        "receipt_ref": _ref(f"{run_id}/receipt"),
        "manifest_ref": _ref(f"{run_id}/manifest"),
        "evidence_refs": [_ref(f"{run_id}/matrix"), _ref(f"{run_id}/artifact")],
        "usage": {
            "2026-09-02": {
                "provider:model": {
                    "call_count": 2,
                    "prompt_tokens": 18,
                    "completion_tokens": 14,
                    "model_name": "model-ref",
                    "provider_id": "provider-ref",
                }
            }
        },
        "latency_ms": 12.5,
        "metrics": {
            "quality": 0.75,
            "evidence_completeness": 1.0,
        },
    }


class NativeLiveReceiptTests(unittest.TestCase):
    def test_qwenpaw_token_usage_is_normalized_to_a_paired_row(self) -> None:
        result = normalize_native_run_export(
            _export(), expected_input_hash=_INPUT_HASH, expected_budget_hash=_BUDGET_HASH
        )

        row = result["rows"][0]
        self.assertEqual(
            set(row),
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
            },
        )
        self.assertTrue(row["frozen"])
        self.assertEqual(row["metrics"]["input_tokens"], 18)
        self.assertEqual(row["metrics"]["output_tokens"], 14)
        self.assertEqual(row["metrics"]["total_tokens"], 32)
        self.assertEqual(row["metrics"]["cost"], NOT_AVAILABLE)
        self.assertEqual(row["metrics"]["latency_ms"], 12.5)
        self.assertEqual(result["manifest"]["usage"]["call_count"], 2)
        self.assertEqual(result["manifest"]["actor"]["runtime"], "qwenpaw")
        compare_pair(row, row)

    def test_qwenpaw_session_usage_shape_is_supported_without_content(self) -> None:
        export = _export()
        export["usage"] = [
            {"input_tokens": 10, "output_tokens": 3},
            {"input_tokens": 2, "output_tokens": 1},
        ]

        result = normalize_native_run_export(
            export, expected_input_hash=_INPUT_HASH, expected_budget_hash=_BUDGET_HASH
        )

        metrics = result["rows"][0]["metrics"]
        self.assertEqual(metrics["input_tokens"], 12)
        self.assertEqual(metrics["output_tokens"], 4)
        self.assertEqual(metrics["total_tokens"], 16)
        self.assertEqual(result["manifest"]["usage"]["call_count"], NOT_AVAILABLE)

    def test_partial_session_usage_is_not_silently_summed(self) -> None:
        export = _export()
        export["usage"] = [
            {"input_tokens": 10, "output_tokens": 3},
            None,
        ]

        result = normalize_native_run_export(
            export, expected_input_hash=_INPUT_HASH, expected_budget_hash=_BUDGET_HASH
        )

        metrics = result["rows"][0]["metrics"]
        self.assertEqual(metrics["input_tokens"], NOT_AVAILABLE)
        self.assertEqual(metrics["output_tokens"], NOT_AVAILABLE)
        self.assertEqual(metrics["total_tokens"], NOT_AVAILABLE)

    def test_missing_usage_and_cost_are_not_available_not_zero(self) -> None:
        export = _export()
        export.pop("usage")
        export.pop("latency_ms")

        result = normalize_native_run_export(
            export, expected_input_hash=_INPUT_HASH, expected_budget_hash=_BUDGET_HASH
        )

        metrics = result["rows"][0]["metrics"]
        self.assertEqual(metrics["input_tokens"], NOT_AVAILABLE)
        self.assertEqual(metrics["output_tokens"], NOT_AVAILABLE)
        self.assertEqual(metrics["total_tokens"], NOT_AVAILABLE)
        self.assertEqual(metrics["cost"], NOT_AVAILABLE)
        self.assertEqual(metrics["latency_ms"], NOT_AVAILABLE)

    def test_public_and_budget_hashes_are_checked_against_external_expectations(self) -> None:
        export = _export()
        export["input_hash"] = _CONTENT_HASH
        with self.assertRaisesRegex(LiveReceiptError, "input_hash"):
            normalize_native_run_export(
                export, expected_input_hash=_INPUT_HASH, expected_budget_hash=_BUDGET_HASH
            )

        export = _export()
        export["budget_hash"] = _CONTENT_HASH
        with self.assertRaisesRegex(LiveReceiptError, "budget_hash"):
            normalize_native_run_export(
                export, expected_input_hash=_INPUT_HASH, expected_budget_hash=_BUDGET_HASH
            )

    def test_only_e0_to_e3_profiles_and_positive_repetitions_are_allowed(self) -> None:
        for profile in ("E0", "E1", "E2", "E3"):
            export = _export()
            export["profile"] = profile
            result = normalize_native_run_export(
                export, expected_input_hash=_INPUT_HASH, expected_budget_hash=_BUDGET_HASH
            )
            self.assertEqual(result["rows"][0]["profile"], profile)

        export = _export()
        export["profile"] = "E4"
        with self.assertRaisesRegex(LiveReceiptError, "profile"):
            normalize_native_run_export(
                export, expected_input_hash=_INPUT_HASH, expected_budget_hash=_BUDGET_HASH
            )

        export = _export()
        export["repetition"] = 0
        with self.assertRaisesRegex(LiveReceiptError, "repetition"):
            normalize_native_run_export(
                export, expected_input_hash=_INPUT_HASH, expected_budget_hash=_BUDGET_HASH
            )

    def test_fresh_native_ids_and_terminal_state_are_required(self) -> None:
        export = _export()
        export["fresh"] = False
        with self.assertRaisesRegex(LiveReceiptError, "fresh"):
            normalize_native_run_export(
                export, expected_input_hash=_INPUT_HASH, expected_budget_hash=_BUDGET_HASH
            )

        export = _export()
        export["native"]["fresh_ids"] = False
        with self.assertRaisesRegex(LiveReceiptError, "fresh_ids"):
            normalize_native_run_export(
                export, expected_input_hash=_INPUT_HASH, expected_budget_hash=_BUDGET_HASH
            )

        export = _export()
        export["run_state"] = "in_progress"
        with self.assertRaisesRegex(LiveReceiptError, "run_state"):
            normalize_native_run_export(
                export, expected_input_hash=_INPUT_HASH, expected_budget_hash=_BUDGET_HASH
            )

        export = _export()
        export["native"]["task_id"] = export["native"]["project_id"]
        with self.assertRaisesRegex(LiveReceiptError, "native"):
            normalize_native_run_export(
                export, expected_input_hash=_INPUT_HASH, expected_budget_hash=_BUDGET_HASH
            )

    def test_forbidden_gold_and_authority_fields_fail_closed(self) -> None:
        for field in (
            "gold",
            "fixture",
            "synthetic",
            "runner",
            "scheduler",
            "observer",
            "taskrun",
        ):
            export = _export()
            export[field] = "forbidden"
            with self.assertRaisesRegex(LiveReceiptError, "forbidden"):
                normalize_native_run_export(
                    export,
                    expected_input_hash=_INPUT_HASH,
                    expected_budget_hash=_BUDGET_HASH,
                )

        export = _export()
        export["metrics"]["runner"] = "forbidden"
        with self.assertRaisesRegex(LiveReceiptError, "forbidden"):
            normalize_native_run_export(
                export, expected_input_hash=_INPUT_HASH, expected_budget_hash=_BUDGET_HASH
            )

    def test_prompt_secret_and_unknown_fields_are_not_consumed(self) -> None:
        for field in ("prompt", "api_key", "password", "body"):
            export = _export()
            export[field] = "must-not-be-read"
            with self.assertRaisesRegex(LiveReceiptError, "forbidden"):
                normalize_native_run_export(
                    export,
                    expected_input_hash=_INPUT_HASH,
                    expected_budget_hash=_BUDGET_HASH,
                )

        export = _export()
        export["unmodeled_field"] = "reject"
        with self.assertRaisesRegex(LiveReceiptError, "unknown"):
            normalize_native_run_export(
                export, expected_input_hash=_INPUT_HASH, expected_budget_hash=_BUDGET_HASH
            )

    def test_missing_usage_cannot_be_replaced_by_token_metrics(self) -> None:
        export = _export()
        export.pop("usage")
        export["metrics"]["input_tokens"] = 1
        with self.assertRaisesRegex(LiveReceiptError, "usage"):
            normalize_native_run_export(
                export, expected_input_hash=_INPUT_HASH, expected_budget_hash=_BUDGET_HASH
            )

    def test_many_exports_reject_duplicate_native_identity(self) -> None:
        first = _export(run_id="run-1", repetition=1)
        second = _export(run_id="run-2", repetition=2)
        second["native"]["project_id"] = first["native"]["project_id"]
        with self.assertRaisesRegex(LiveReceiptError, "duplicate"):
            normalize_native_run_exports(
                [first, second],
                expected_input_hash=_INPUT_HASH,
                expected_budget_hash=_BUDGET_HASH,
            )

    def test_many_exports_allow_profiles_but_reject_duplicate_observations(self) -> None:
        baseline = _export(run_id="baseline", repetition=1)
        treatment = _export(run_id="treatment", repetition=1)
        treatment["profile"] = "E0"

        result = normalize_native_run_exports(
            [baseline, treatment],
            expected_input_hash=_INPUT_HASH,
            expected_budget_hash=_BUDGET_HASH,
        )
        self.assertEqual(len(result["rows"]), 2)

        duplicate = _export(run_id="duplicate", repetition=1)
        with self.assertRaisesRegex(LiveReceiptError, "duplicate paired observation"):
            normalize_native_run_exports(
                [baseline, duplicate],
                expected_input_hash=_INPUT_HASH,
                expected_budget_hash=_BUDGET_HASH,
            )

    def test_manifest_hash_is_sealed_and_input_is_not_mutated(self) -> None:
        export = _export()
        original = copy.deepcopy(export)
        result = normalize_native_run_export(
            export, expected_input_hash=_INPUT_HASH, expected_budget_hash=_BUDGET_HASH
        )

        self.assertEqual(export, original)
        manifest = result["manifest"]
        self.assertRegex(manifest["content_hash"], r"^sha256:[0-9a-f]{64}$")
        self.assertNotIn("prompt", manifest)
        self.assertNotIn("content", manifest)
        manifest_payload = {key: value for key, value in manifest.items() if key != "content_hash"}
        self.assertEqual(manifest["content_hash"], canonical_hash(manifest_payload))
        result_payload = {key: value for key, value in result.items() if key != "content_hash"}
        self.assertEqual(result["content_hash"], canonical_hash(result_payload))

    def test_module_has_no_runtime_or_task_authority_dependency(self) -> None:
        source = inspect.getsource(native_live_receipt).lower()
        for forbidden in (
            "subprocess",
            "socket",
            "requests",
            "docker",
            "matrix",
            "taskflow",
            "projectflow",
            "roomflow",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
