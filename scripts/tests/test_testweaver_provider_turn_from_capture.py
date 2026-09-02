from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from testweaver.contracts.validator import canonical_hash


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "testweaver-provider-turn-from-capture.py"
BRIDGE_SCRIPT = ROOT / "scripts" / "testweaver-agentloop-bridge.py"


def _seal(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result["record_hash"] = canonical_hash(result)
    return result


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ProviderTurnFromCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.capture = self.root / "capture"
        self.snapshot = self.capture / "snapshots" / "20260903T000000000Z"
        (self.snapshot / "sessions" / "worker-a").mkdir(parents=True)
        (self.snapshot / "shared-fs").mkdir()
        (self.snapshot / "skills" / "worker-a").mkdir(parents=True)
        self.scope = {
            "campaign_id": "campaign-1",
            "run_id": "run-1",
            "trace_id": "0123456789abcdef0123456789abcdef",
        }
        self.session_record_hash = "a" * 64
        self.skill_source_hash = "b" * 64
        self.pg_content_hash = "sha256:" + "c" * 64

        self._write_json(
            "manifest.json",
            {
                "schema": "testweaver.native-hero-capture.v1",
                "status": "STOPPED",
                "checksum_state": "FINAL",
                "authority_scope": self.scope,
                "latest_snapshot": "snapshots/20260903T000000000Z",
                "classification": "NOT_ASSESSED",
                "live_claimed": False,
                "prohibited_actions_performed": {
                    "matrix_send": False,
                    "resource_mutation": False,
                    "fault_injection": False,
                    "provider_call": False,
                    "gold_read": False,
                    "event_injection": False,
                },
            },
        )
        self._write_json(
            "snapshots/20260903T000000000Z/roster.json",
            {
                "actors": [
                    {
                        "name": "worker-a",
                        "kind": "worker",
                        "matrix_user_id": "@worker-a:example.test",
                    }
                ]
            },
        )
        self._write_jsonl(
            "snapshots/20260903T000000000Z/sessions/worker-a/readback.jsonl",
            [
                {
                    "record_hash": self.session_record_hash,
                    "role": "assistant",
                    "actor": "worker-a",
                    "container": "worker-a-container",
                    "provider": "aliyun-bailian",
                    "model": "qwen3-coder-plus",
                    "usage": {"input": 13, "output": 8, "total": 21},
                    "latency_ms": 42.5,
                    "session_ref": "/protected/native/session.jsonl",
                    "session_file_sha256": "d" * 64,
                    "scope_mentions": {
                        "campaign_id": True,
                        "run_id": True,
                        "trace_id": True,
                    },
                }
            ],
        )
        self._write_jsonl(
            "snapshots/20260903T000000000Z/shared-fs/task-metadata.jsonl",
            [
                {
                    "task_id": "task-1",
                    "status": "submitted",
                    "result_status": "SUCCESS",
                    "assigned_to": "@worker-a:example.test",
                    "submitted_by_role": "worker",
                    "source_ref": "/protected/native/task/meta.json",
                    "raw_bytes_sha256": "e" * 64,
                }
            ],
        )
        self._write_jsonl(
            "snapshots/20260903T000000000Z/shared-fs/task-artifacts.jsonl",
            [
                {
                    "kind": "metadata",
                    "source_ref": "/protected/native/task/meta.json",
                    "raw_bytes_sha256": "e" * 64,
                }
            ],
        )
        self._write_json(
            "snapshots/20260903T000000000Z/raw/pg-authority-row.json",
            {
                **self.scope,
                "pg_revision": 9,
                "content_hash": self.pg_content_hash,
                "agent_id": "worker-a",
                "task_id": "task-1",
                "provider_session_record_hash": "sha256:" + self.session_record_hash,
            },
        )
        pg_raw_ref = "snapshots/20260903T000000000Z/raw/pg-authority-row.json"
        pg = _seal(
            {
                "schema_version": "testweaver.pg-authority-readback/v1",
                "authority_scope": self.scope,
                "pg_revision": 9,
                "content_hash": self.pg_content_hash,
                "agent_id": "worker-a",
                "task_id": "task-1",
                "provider_session_record_hash": "sha256:" + self.session_record_hash,
                "source_ref": pg_raw_ref,
                "source_hash": "sha256:" + _sha(self.capture / pg_raw_ref),
            }
        )
        self._write_json("snapshots/20260903T000000000Z/pg-exact.json", pg)
        self._write_json(
            "snapshots/20260903T000000000Z/raw/skill-invocation.json",
            {
                **self.scope,
                "agent_id": "worker-a",
                "task_id": "task-1",
                "provider_session_record_hash": "sha256:" + self.session_record_hash,
                "skill_name": "testweaver-native-external-worker",
                "skill_version": "0.1.0",
                "invoke_ref": "task:task-1:skill-invocation:1",
            },
        )
        invocation_raw_ref = "snapshots/20260903T000000000Z/raw/skill-invocation.json"
        skill = _seal(
            {
                "schema_version": "testweaver.skill-invocation-readback/v1",
                "authority_scope": self.scope,
                "agent_id": "worker-a",
                "task_id": "task-1",
                "provider_session_record_hash": "sha256:" + self.session_record_hash,
                "skill": {
                    "name": "testweaver-native-external-worker",
                    "version": "0.1.0",
                    "source_ref": "/workspace/skills/testweaver-native-external-worker/SKILL.md",
                    "source_hash": "sha256:" + self.skill_source_hash,
                },
                "invoke_ref": "task:task-1:skill-invocation:1",
                "source_ref": invocation_raw_ref,
                "source_hash": "sha256:" + _sha(self.capture / invocation_raw_ref),
            }
        )
        self._write_json("snapshots/20260903T000000000Z/skill-invocation.json", skill)
        (self.snapshot / "skills" / "worker-a" / "hashes.txt").write_text(
            f"{self.skill_source_hash}  /workspace/skills/testweaver-native-external-worker/SKILL.md\n",
            encoding="utf-8",
        )
        self._write_sums()

    def _write_json(self, relative: str, value: Any) -> None:
        path = self.capture / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")

    def _write_jsonl(self, relative: str, values: list[dict[str, Any]]) -> None:
        path = self.capture / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(value, sort_keys=True) + "\n" for value in values),
            encoding="utf-8",
        )

    def _write_sums(self) -> None:
        rows = []
        for path in sorted(self.capture.rglob("*")):
            if path.is_file() and path.name != "SHA256SUMS":
                rows.append(f"{_sha(path)}  {path.relative_to(self.capture).as_posix()}\n")
        (self.capture / "SHA256SUMS").write_text("".join(rows), encoding="utf-8")

    def _run(self, *extra: str) -> subprocess.CompletedProcess[str]:
        output = self.root / "provider-turn.json"
        receipt = self.root / "build-receipt.json"
        args = [
            sys.executable,
            str(SCRIPT),
            "--capture-dir",
            str(self.capture),
            "--provider-session-ref",
            "snapshots/20260903T000000000Z/sessions/worker-a/readback.jsonl",
            "--provider-record-hash",
            "sha256:" + self.session_record_hash,
            "--task-ref",
            "snapshots/20260903T000000000Z/shared-fs/task-metadata.jsonl",
            "--task-id",
            "task-1",
            "--pg-ref",
            "snapshots/20260903T000000000Z/pg-exact.json",
            "--skill-invocation-ref",
            "snapshots/20260903T000000000Z/skill-invocation.json",
            "--output",
            str(output),
            "--receipt",
            str(receipt),
            *extra,
        ]
        return subprocess.run(args, text=True, capture_output=True, check=False)

    def test_builds_bridge_compatible_turn_only_from_exact_matching_sources(self) -> None:
        completed = self._run()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        turn_path = self.root / "provider-turn.json"
        receipt = json.loads((self.root / "build-receipt.json").read_text())
        self.assertEqual(receipt["status"], "PASS")
        self.assertFalse(receipt["synthetic"])
        self.assertTrue(turn_path.is_file())

        spec = importlib.util.spec_from_file_location("bridge_for_builder_test", BRIDGE_SCRIPT)
        assert spec and spec.loader
        bridge = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = bridge
        spec.loader.exec_module(bridge)
        turn = bridge.parse_provider_turn(turn_path.read_bytes())
        self.assertEqual(turn.task_id, "task-1")
        self.assertEqual(turn.pg_revision, 9)
        self.assertEqual(turn.usage, {"input_tokens": 13, "output_tokens": 8, "total_tokens": 21})

    def test_blocks_active_capture_without_writing_provider_turn(self) -> None:
        manifest = json.loads((self.capture / "manifest.json").read_text())
        manifest["status"] = "ACTIVE"
        self._write_json("manifest.json", manifest)
        self._write_sums()
        completed = self._run()
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse((self.root / "provider-turn.json").exists())
        receipt = json.loads((self.root / "build-receipt.json").read_text())
        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertEqual(receipt["reason"], "CAPTURE_NOT_FINAL")
        self.assertEqual(receipt["record_hash"], canonical_hash({k: v for k, v in receipt.items() if k != "record_hash"}))

    def test_blocks_checksum_tamper(self) -> None:
        with (self.snapshot / "shared-fs" / "task-metadata.jsonl").open("a", encoding="utf-8") as stream:
            stream.write("{}\n")
        completed = self._run()
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(
            json.loads((self.root / "build-receipt.json").read_text())["reason"],
            "CAPTURE_CHECKSUM_MISMATCH",
        )

    def test_blocks_pg_source_hash_when_sealed_bytes_change(self) -> None:
        self._write_json(
            "snapshots/20260903T000000000Z/raw/pg-authority-row.json",
            {"unexpected": "pg-row"},
        )
        self._write_sums()
        completed = self._run()
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse((self.root / "provider-turn.json").exists())
        self.assertEqual(
            json.loads((self.root / "build-receipt.json").read_text())["reason"],
            "SOURCE_HASH_MISMATCH",
        )

    def test_blocks_skill_invocation_source_hash_when_sealed_bytes_change(self) -> None:
        self._write_json(
            "snapshots/20260903T000000000Z/raw/skill-invocation.json",
            {"unexpected": "skill-invocation"},
        )
        self._write_sums()
        completed = self._run()
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse((self.root / "provider-turn.json").exists())
        self.assertEqual(
            json.loads((self.root / "build-receipt.json").read_text())["reason"],
            "SOURCE_HASH_MISMATCH",
        )

    def test_blocks_task_artifact_source_hash_mismatch(self) -> None:
        artifact_path = self.snapshot / "shared-fs" / "task-artifacts.jsonl"
        artifact = json.loads(artifact_path.read_text())
        artifact["raw_bytes_sha256"] = "9" * 64
        self._write_jsonl(
            "snapshots/20260903T000000000Z/shared-fs/task-artifacts.jsonl",
            [artifact],
        )
        self._write_sums()
        completed = self._run()
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(
            json.loads((self.root / "build-receipt.json").read_text())["reason"],
            "SOURCE_HASH_MISMATCH",
        )

    def test_blocks_missing_or_mismatched_required_evidence(self) -> None:
        skill_path = self.snapshot / "skill-invocation.json"
        skill = json.loads(skill_path.read_text())
        skill["task_id"] = "other-task"
        skill = _seal({key: value for key, value in skill.items() if key != "record_hash"})
        self._write_json("snapshots/20260903T000000000Z/skill-invocation.json", skill)
        self._write_sums()
        completed = self._run()
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse((self.root / "provider-turn.json").exists())
        self.assertEqual(
            json.loads((self.root / "build-receipt.json").read_text())["reason"],
            "EVIDENCE_BINDING_MISMATCH",
        )

    def test_blocks_self_reported_pg_source_hash_after_raw_bytes_change(self) -> None:
        raw = self.snapshot / "raw" / "pg-authority-row.json"
        value = json.loads(raw.read_text())
        value["pg_revision"] = 10
        self._write_json("snapshots/20260903T000000000Z/raw/pg-authority-row.json", value)
        self._write_sums()
        completed = self._run()
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse((self.root / "provider-turn.json").exists())
        self.assertEqual(
            json.loads((self.root / "build-receipt.json").read_text())["reason"],
            "SOURCE_HASH_MISMATCH",
        )

    def test_blocks_skill_source_not_present_in_captured_inventory(self) -> None:
        inventory = self.snapshot / "skills" / "worker-a" / "hashes.txt"
        inventory.write_text(
            f"{'9' * 64}  /workspace/skills/testweaver-native-external-worker/SKILL.md\n",
            encoding="utf-8",
        )
        self._write_sums()
        completed = self._run()
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(
            json.loads((self.root / "build-receipt.json").read_text())["reason"],
            "SOURCE_HASH_MISMATCH",
        )

    def test_blocks_ambiguous_provider_record(self) -> None:
        path = self.snapshot / "sessions" / "worker-a" / "readback.jsonl"
        path.write_text(path.read_text() + path.read_text(), encoding="utf-8")
        self._write_sums()
        completed = self._run()
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(
            json.loads((self.root / "build-receipt.json").read_text())["reason"],
            "EVIDENCE_AMBIGUOUS",
        )


if __name__ == "__main__":
    unittest.main()
