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
                    "record_hash": "f" * 64,
                    "sequence": 0,
                    "timestamp": 1000,
                    "timestamp_ms": 1000,
                    "role": "user",
                    "actor": "worker-a",
                    "container": "worker-a-container",
                    "provider": None,
                    "model": None,
                    "usage": None,
                    "latency_ms": None,
                    "session_ref": "/protected/native/session.jsonl",
                    "session_file_sha256": "d" * 64,
                    "scope_mentions": {
                        "campaign_id": True,
                        "run_id": True,
                        "trace_id": True,
                    },
                    "task_refs": ["task-1"],
                    "matrix_event_refs": ["$task-root"],
                },
                {
                    "record_hash": self.session_record_hash,
                    "sequence": 1,
                    "role": "assistant",
                    "timestamp": 1200,
                    "timestamp_ms": 1200,
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
                    "task_refs": [],
                    "matrix_event_refs": [],
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
        pg_raw = {
            **self.scope,
            "pg_revision": 9,
            "content_hash": self.pg_content_hash,
            "agent_id": "worker-a",
            "task_id": "task-1",
            "provider_session_record_hash": "sha256:" + self.session_record_hash,
        }
        pg_raw_bytes = (json.dumps(pg_raw, sort_keys=True) + "\n").encode()
        pg_raw_hash = hashlib.sha256(pg_raw_bytes).hexdigest()
        pg_raw_ref = (
            "snapshots/20260903T000000000Z/pg-exact-raw/"
            f"tw_authority/{pg_raw_hash}.json"
        )
        self._write_json(pg_raw_ref, pg_raw)
        pg = _seal(
            {
                "schema_version": "testweaver.pg-exact-readback/v1",
                "authority_scope": self.scope,
                "table": "tw_authority",
                "pg_revision": 9,
                "content_hash": self.pg_content_hash,
                "agent_id": "worker-a",
                "task_id": "task-1",
                "provider_session_record_hash": "sha256:" + self.session_record_hash,
                "source_ref": pg_raw_ref,
                "source_hash": "sha256:" + _sha(self.capture / pg_raw_ref),
            }
        )
        self._write_jsonl(
            "snapshots/20260903T000000000Z/pg-exact-readback.jsonl", [pg]
        )
        task_event = {
            "event_id": "$task-root",
            "room_id": "!hero:example.test",
            "sender": "@leader:example.test",
            "origin_server_ts": 900,
            "type": "m.room.message",
            "content": {
                "msgtype": "m.text",
                "body": "@worker-a:example.test TASK_ASSIGNED task-1",
            },
        }
        task_event_ref = (
            "snapshots/20260903T000000000Z/matrix/worker-a/events/task-root.json"
        )
        self._write_json(task_event_ref, task_event)
        skill_event = {
            "event_id": "$skill-event",
            "room_id": "!hero:example.test",
            "sender": "@worker-a:example.test",
            "origin_server_ts": 1100,
            "type": "m.room.message",
            "content": {
                "msgtype": "m.text",
                "body": (
                    "🔧 **read_file**\n```\n"
                    '{"file_path":"/workspace/skills/'
                    "testweaver-native-external-worker/SKILL.md" + '"}\n```'
                ),
                "m.relates_to": {
                    "event_id": "$task-root",
                    "rel_type": "m.thread",
                    "is_falling_back": False,
                },
            },
        }
        skill_event_ref = (
            "snapshots/20260903T000000000Z/matrix/worker-a/events/skill-event.json"
        )
        self._write_json(skill_event_ref, skill_event)
        self.event_index_ref = (
            "snapshots/20260903T000000000Z/matrix/worker-a/event-index.jsonl"
        )
        self._write_jsonl(
            self.event_index_ref,
            [
                {
                    "actor": "worker-a",
                    "actor_matrix_id": "@worker-a:example.test",
                    "room_id": "!hero:example.test",
                    "event_id": "$task-root",
                    "sender": "@leader:example.test",
                    "identity_binding": "UNBOUND",
                    "origin_server_ts": 900,
                    "authority_scope": self.scope,
                    "immutable_source": {
                        "ref": task_event_ref,
                        "raw_bytes_sha256": _sha(self.capture / task_event_ref),
                    },
                },
                {
                    "actor": "worker-a",
                    "actor_matrix_id": "@worker-a:example.test",
                    "room_id": "!hero:example.test",
                    "event_id": "$skill-event",
                    "sender": "@worker-a:example.test",
                    "identity_binding": "ACTOR_EXACT",
                    "origin_server_ts": 1100,
                    "authority_scope": self.scope,
                    "immutable_source": {
                        "ref": skill_event_ref,
                        "raw_bytes_sha256": _sha(self.capture / skill_event_ref),
                    },
                },
            ],
        )
        session_ref = (
            "snapshots/20260903T000000000Z/sessions/worker-a/readback.jsonl"
        )
        skill = _seal(
            {
                "schema_version": "testweaver.skill-invocation-capture/v1",
                "authority_scope": self.scope,
                "agent_id": "worker-a",
                "task_id": "task-1",
                "provider_session_record_hash": "sha256:" + self.session_record_hash,
                "skill": {
                    "name": "testweaver-native-external-worker",
                    "version": "sha256:" + self.skill_source_hash,
                    "source_ref": "/workspace/skills/testweaver-native-external-worker/SKILL.md",
                    "source_hash": "sha256:" + self.skill_source_hash,
                },
                "invoke_ref": "$skill-event",
                "source_kind": "runtime_matrix_skill_event",
                "task_event_ref": "$task-root",
                "task_event_source_ref": task_event_ref,
                "task_event_source_hash": "sha256:" + _sha(self.capture / task_event_ref),
                "source_ref": skill_event_ref,
                "source_hash": "sha256:" + _sha(self.capture / skill_event_ref),
                "session_ref": session_ref,
                "session_hash": "sha256:" + _sha(self.capture / session_ref),
                "turn_input_record_hash": "sha256:" + "f" * 64,
                "event_timestamp_ms": 1100,
            }
        )
        self._write_jsonl(
            "snapshots/20260903T000000000Z/skill-invocations.jsonl",
            [skill],
        )
        (self.snapshot / "skills" / "worker-a" / "hashes.txt").write_text(
            f"{self.skill_source_hash}  /workspace/skills/testweaver-native-external-worker/SKILL.md\n",
            encoding="utf-8",
        )
        self._write_json(
            "snapshots/20260903T000000000Z/skills/worker-a/list.json",
            [
                {
                    "name": "testweaver-native-external-worker",
                    "enabled": True,
                }
            ],
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

    def _replace_skill_event_body(self, body: str) -> None:
        event_ref = (
            "snapshots/20260903T000000000Z/matrix/worker-a/events/skill-event.json"
        )
        event = json.loads((self.capture / event_ref).read_text())
        event["content"]["body"] = body
        self._write_json(event_ref, event)
        event_hash = _sha(self.capture / event_ref)

        indexes = [
            json.loads(line)
            for line in (self.capture / self.event_index_ref).read_text().splitlines()
        ]
        next(item for item in indexes if item["event_id"] == "$skill-event")[
            "immutable_source"
        ]["raw_bytes_sha256"] = event_hash
        self._write_jsonl(self.event_index_ref, indexes)

        skill_ref = "snapshots/20260903T000000000Z/skill-invocations.jsonl"
        skill = json.loads((self.capture / skill_ref).read_text())
        skill["source_hash"] = "sha256:" + event_hash
        skill = _seal({key: value for key, value in skill.items() if key != "record_hash"})
        self._write_jsonl(skill_ref, [skill])
        self._write_sums()

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
            next(
                str(path.relative_to(self.capture))
                for path in (self.snapshot / "pg-exact-raw").rglob("*.json")
            ),
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

    def test_blocks_runtime_skill_event_source_hash_when_exact_bytes_change(self) -> None:
        self._write_json(
            "snapshots/20260903T000000000Z/matrix/worker-a/events/skill-event.json",
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

    def test_blocks_nonexistent_skill_tool_event_even_when_resealed(self) -> None:
        self._replace_skill_event_body(
            '🔧 **Skill**\n```\n{"skill":"testweaver-native-external-worker"}\n```'
        )
        completed = self._run()
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse((self.root / "provider-turn.json").exists())
        self.assertEqual(
            json.loads((self.root / "build-receipt.json").read_text())["reason"],
            "SOURCE_READBACK_MISMATCH",
        )

    def test_blocks_free_text_skill_claim_even_when_resealed(self) -> None:
        self._replace_skill_event_body(
            "I loaded testweaver-native-external-worker for this task."
        )
        completed = self._run()
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse((self.root / "provider-turn.json").exists())
        self.assertEqual(
            json.loads((self.root / "build-receipt.json").read_text())["reason"],
            "SOURCE_READBACK_MISMATCH",
        )

    def test_blocks_read_file_for_a_different_skill_path_even_when_resealed(self) -> None:
        self._replace_skill_event_body(
            '🔧 **read_file**\n```\n{"file_path":"/workspace/skills/other/SKILL.md"}\n```'
        )
        completed = self._run()
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse((self.root / "provider-turn.json").exists())
        self.assertEqual(
            json.loads((self.root / "build-receipt.json").read_text())["reason"],
            "SOURCE_READBACK_MISMATCH",
        )

    def test_blocks_task_artifact_source_hash_mismatch(self) -> None:
        artifact_path = self.snapshot / "shared-fs" / "task-artifacts.jsonl"
        artifacts = [json.loads(line) for line in artifact_path.read_text().splitlines()]
        artifacts[0]["raw_bytes_sha256"] = "9" * 64
        self._write_jsonl(
            "snapshots/20260903T000000000Z/shared-fs/task-artifacts.jsonl",
            artifacts,
        )
        self._write_sums()
        completed = self._run()
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(
            json.loads((self.root / "build-receipt.json").read_text())["reason"],
            "SOURCE_HASH_MISMATCH",
        )

    def test_blocks_missing_or_mismatched_required_evidence(self) -> None:
        skill_path = self.snapshot / "skill-invocations.jsonl"
        skill = json.loads(skill_path.read_text())
        skill["task_id"] = "other-task"
        skill = _seal({key: value for key, value in skill.items() if key != "record_hash"})
        self._write_jsonl(
            "snapshots/20260903T000000000Z/skill-invocations.jsonl",
            [skill],
        )
        self._write_sums()
        completed = self._run()
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse((self.root / "provider-turn.json").exists())
        self.assertEqual(
            json.loads((self.root / "build-receipt.json").read_text())["reason"],
            "EVIDENCE_MISSING",
        )

    def test_blocks_self_reported_pg_source_hash_after_raw_bytes_change(self) -> None:
        raw = next((self.snapshot / "pg-exact-raw").rglob("*.json"))
        value = json.loads(raw.read_text())
        value["pg_revision"] = 10
        self._write_json(str(raw.relative_to(self.capture)), value)
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

    def test_skill_inventory_without_captured_invocation_is_blocked(self) -> None:
        (self.snapshot / "skill-invocations.jsonl").unlink()
        self._write_sums()
        completed = self._run()
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse((self.root / "provider-turn.json").exists())
        self.assertEqual(
            json.loads((self.root / "build-receipt.json").read_text())["reason"],
            "EVIDENCE_NOT_SEALED",
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
