from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import tempfile
import unittest
from pathlib import Path

ORACLES = Path(__file__).resolve().parents[1]
BOUNDARY = ORACLES / "boundary"
OUTCOME = ORACLES / "outcome"
MANAGER_OVERLAY = ORACLES.parents[0] / "manager" / "AGENTS.overlay.md"
PINNED_COMMIT = "4fb580c8da24b880f054246cb9273341940b92f7"
PINNED_VERIFIER_SHA256 = "896ea473e5a7fddae905aee3e697c8b99a5cea94ed749918969437fe176db2aa"
PRIVATE_FIELDS = {
    "expected_intent",
    "expected_committed_side_effects",
    "gold_boundary",
    "hidden_gold",
    "gold_suite_hash",
    "gold_id",
    "gold",
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def keys_recursive(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(keys_recursive(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(keys_recursive(item) for item in value))
    return set()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OracleAgentSpecPackageTests(unittest.TestCase):
    def test_boundary_and_candidate_views_contain_no_private_gold(self) -> None:
        boundary_files = [path for path in BOUNDARY.rglob("*") if path.is_file()]
        self.assertFalse(
            [path for path in boundary_files if "gold" in path.name.lower()],
            "Boundary package must not contain a Gold file",
        )

        manifest = read_json(BOUNDARY / "manifest.json")
        visible = manifest["oracle"]["candidate_visible"]
        self.assertGreaterEqual(len(visible), 3)
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory)
            for relative in visible:
                source = BOUNDARY / relative
                target = candidate / source.name
                target.write_bytes(source.read_bytes())
            self.assertFalse(list(candidate.glob("*gold*")))
            for path in candidate.iterdir():
                self.assertFalse(PRIVATE_FIELDS & keys_recursive(read_json(path)))

        public_policy = read_json(BOUNDARY / "config/oracle/public-boundary-v1.json")
        self.assertIsNone(public_policy["gold_ref"])

    def test_outcome_has_only_verifier_private_gold(self) -> None:
        gold_files = [path for path in OUTCOME.rglob("*") if path.is_file() and "gold" in path.name]
        self.assertEqual(
            [path.relative_to(OUTCOME).as_posix() for path in gold_files],
            ["config/oracle-private/gold-boundary-v1.json"],
        )
        manifest = read_json(OUTCOME / "manifest.json")
        self.assertEqual(manifest["oracle"]["visibility"], "verifier_private_gold")
        self.assertEqual(sha256(gold_files[0]), manifest["provenance"]["gold_sha256"])

    def test_artifact_hashes_and_source_commit_are_sealed(self) -> None:
        for package in (BOUNDARY, OUTCOME):
            manifest = read_json(package / "manifest.json")
            self.assertEqual(manifest["provenance"]["source_commit"], PINNED_COMMIT)
            self.assertEqual(manifest["provenance"]["verifier_sha256"], PINNED_VERIFIER_SHA256)
            for relative, expected in manifest["provenance"]["artifacts"].items():
                self.assertEqual(sha256(package / relative), expected, relative)

        boundary_verifier = BOUNDARY / "config/oracle/verifier.py"
        outcome_verifier = OUTCOME / "config/oracle/verifier.py"
        self.assertEqual(boundary_verifier.read_bytes(), outcome_verifier.read_bytes())
        self.assertEqual(sha256(boundary_verifier), PINNED_VERIFIER_SHA256)

    def test_entry_modes_and_agent_instructions_are_distinct(self) -> None:
        boundary_mode = read_json(BOUNDARY / "config/oracle/mode.json")
        outcome_mode = read_json(OUTCOME / "config/oracle/mode.json")
        self.assertEqual(boundary_mode["entrypoint"], "verify_boundary")
        self.assertEqual(outcome_mode["entrypoint"], "verify_outcome")
        self.assertNotEqual(boundary_mode["entrypoint"], outcome_mode["entrypoint"])
        self.assertIn("gold", boundary_mode["forbidden_inputs"])

        boundary_module = load_module(BOUNDARY / "config/oracle/verifier.py", "boundary_verifier")
        outcome_module = load_module(OUTCOME / "config/oracle/verifier.py", "outcome_verifier")
        self.assertNotIn("gold", inspect.signature(boundary_module.verify_boundary).parameters)
        self.assertIn("gold", inspect.signature(outcome_module.verify_outcome).parameters)

        boundary_soul = (BOUNDARY / "config/SOUL.md").read_text(encoding="utf-8")
        outcome_soul = (OUTCOME / "config/SOUL.md").read_text(encoding="utf-8")
        self.assertIn("永远禁止读取 Gold", boundary_soul)
        self.assertIn("只有在 Team Leader 原生分配明确的 Outcome Oracle Task 后", outcome_soul)
        self.assertIn("不与 Boundary Oracle 通信", outcome_soul)

    def test_manager_preserves_outcome_oracle_role_boundary(self) -> None:
        manager_policy = " ".join(MANAGER_OVERLAY.read_text(encoding="utf-8").split())
        self.assertIn("candidate inputs and Boundary Oracle assignments", manager_policy)
        self.assertIn("Do not propagate that restriction into an Outcome Oracle", manager_policy)
        self.assertIn("Leader has natively assigned an explicit Outcome verification task", manager_policy)
        self.assertIn("must follow its sealed role policy, including reading its own private Gold", manager_policy)
        self.assertIn("must return only versioned result, metric, and hash/reference", manager_policy)
        self.assertIn("Never relay Gold contents or derivations", manager_policy)


if __name__ == "__main__":
    unittest.main()
