from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Any

from testweaver.authority import OracleResult


SCRIPT = Path(__file__).resolve().parents[1] / "testweaver-hero-bundle.py"
SPEC = importlib.util.spec_from_file_location("testweaver_hero_bundle", SCRIPT)
assert SPEC and SPEC.loader
bundle = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bundle
SPEC.loader.exec_module(bundle)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
SCOPE = {"campaign_id": "campaign-1", "run_id": "run-1", "trace_id": "trace-1"}


def _write(path: Path, value: bytes | str | dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        path.write_bytes(value)
    elif isinstance(value, str):
        path.write_text(value, encoding="utf-8")
    else:
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _oracle(kind: str, *, identity_ref: str | None = None) -> dict[str, Any]:
    result = OracleResult.create(
        result_id=f"oracle-result:{kind}",
        oracle_kind=kind,
        run_id=SCOPE["run_id"],
        campaign_id=SCOPE["campaign_id"],
        trace_id=SCOPE["trace_id"],
        identity_ref=identity_ref or f"oracle-identity:{kind}",
        process_ref=f"oracle-process:{kind}",
        result_ref=f"oracle-artifact:{kind}",
        result_hash=HASH_B if kind == "outcome" else HASH_C,
        evidence_root_ref="evidence-root:hero",
        evidence_root_hash=HASH_A,
        evidence_refs=({"ref": "evidence:shared", "content_hash": HASH_A},),
        gold_ref="gold:sealed" if kind == "outcome" else None,
        source_ref=f"native-oracle:{kind}",
        status="PASS",
        provenance="agentteams-native",
    )
    return result.as_dict()


def _seal(evidence: Path) -> None:
    lines = []
    for path in sorted(item for item in evidence.rglob("*") if item.is_file()):
        if path.name == "SHA256SUMS":
            continue
        relative = path.relative_to(evidence).as_posix()
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  ./{relative}\n")
    _write(evidence / "SHA256SUMS", "".join(lines))


def _fixture(root: Path, *, complete: bool = True) -> Path:
    evidence = root / "hero"
    snapshot = evidence / "snapshots" / "20260903T010203Z"
    manifest = {
        "schema": "testweaver.native-hero-capture.v1",
        "status": "STOPPED",
        "checksum_state": "FINAL",
        "authority_scope": SCOPE,
        "latest_snapshot": "snapshots/20260903T010203Z",
        "classification": "NOT_ASSESSED",
        "live_claimed": False,
    }
    _write(evidence / "manifest.json", manifest)
    _write(
        snapshot / "snapshot-manifest.json",
        {
            "schema": "testweaver.native-hero-capture.v1",
            "authority_scope": SCOPE,
            "snapshot_ref": "snapshots/20260903T010203Z",
        },
    )

    event = b'{"event_id":"$human","room_id":"!hero:hs","sender":"@human:hs","type":"m.room.message"}\n'
    event_path = snapshot / "matrix" / "manager" / "events" / "human.json"
    _write(event_path, event)
    event_digest = hashlib.sha256(event).hexdigest()
    _write(event_path.with_name("human.raw.sha256"), event_digest + "\n")
    _write(
        snapshot / "matrix" / "manager" / "event-index.jsonl",
        json.dumps(
            {
                "actor": "manager",
                "room_id": "!hero:hs",
                "event_id": "$human",
                "sender": "@human:hs",
                "identity_binding": "HUMAN_ALLOWLIST_EXACT",
                "authority_scope": SCOPE,
                "immutable_source": {
                    "ref": "snapshots/20260903T010203Z/matrix/manager/events/human.json",
                    "raw_bytes_sha256": event_digest,
                },
            },
            sort_keys=True,
        )
        + "\n",
    )
    _write(snapshot / "matrix" / "manager" / "joined_rooms.json", {"joined_rooms": ["!hero:hs"]})
    _write(snapshot / "authority" / "projects.json", {"projects": [{"id": "project-1"}]})
    _write(snapshot / "authority" / "tasks.json", {"tasks": [{"task_id": "task-1", "status": "submitted"}]})
    _write(snapshot / "shared-fs" / "task-metadata.jsonl", '{"task_id":"task-1","status":"submitted"}\n')
    _write(snapshot / "manager-choice-readback.json", {"status": "OBSERVED_PROVIDER_TURN", "provider": "gateway"})
    _write(snapshot / "sessions" / "manager" / "readback.jsonl", '{"role":"assistant","provider":"gateway"}\n')
    _write(snapshot / "pg-tw-row-hashes.jsonl", '{"table":"tw_events","row_hash":"abc"}\n')
    _write(snapshot / "skills" / "worker" / "list.json", [{"name": "evidence", "enabled": True}])
    _write(snapshot / "skills" / "worker" / "hashes.txt", "a" * 64 + "  /skills/evidence/SKILL.md\n")
    _write(evidence / "facts" / "hitl" / "decision.json", {"status": "OBSERVED", **SCOPE})
    _write(evidence / "facts" / "recovery" / "result.json", {"status": "OBSERVED", **SCOPE})
    _write(evidence / "facts" / "oracles" / "outcome.json", _oracle("outcome"))
    _write(evidence / "facts" / "oracles" / "boundary.json", _oracle("boundary"))
    _write(evidence / "facts" / "otel" / "receipt.json", {"status": "EXPORT_ACCEPTED", **SCOPE})
    _write(evidence / "facts" / "agentloop" / "receipt.json", {"status": "API_QUERY_VERIFIED", **SCOPE})
    if not complete:
        (evidence / "facts" / "oracles" / "boundary.json").unlink()
        (evidence / "facts" / "agentloop" / "receipt.json").unlink()

    _seal(evidence)
    return evidence


class HeroBundleTests(unittest.TestCase):
    def test_complete_bundle_is_deterministic_and_independently_replays(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = _fixture(root)
            first = root / "first.zip"
            second = root / "second.zip"
            built = bundle.build_hero_bundle(evidence, first, source_commit="abc123")
            bundle.build_hero_bundle(evidence, second, source_commit="abc123")

            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(built["classification"], "ATTESTED_EXTERNAL_EXPORT")
            verified = bundle.verify_hero_bundle(first)
            replayed = bundle.replay_hero_bundle(first)
            self.assertEqual(verified["bundle_sha256"], replayed["bundle_sha256"])
            self.assertTrue(replayed["replay_equal"])

            with zipfile.ZipFile(first) as archive:
                self.assertIn("manifest.json", archive.namelist())
                self.assertIn("SHA256SUMS", archive.namelist())
                self.assertIn("replay.py", archive.namelist())
                manifest = json.loads(archive.read("manifest.json"))
                self.assertNotIn("PASS", {item["status"] for item in manifest["observations"].values()})
                self.assertNotIn("LIVE", manifest["classification"])
                replay_script = root / "replay.py"
                replay_script.write_bytes(archive.read("replay.py"))
            replay = subprocess.run(
                [sys.executable, str(replay_script), str(first)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(replay.returncode, 0, replay.stderr)
            self.assertEqual(json.loads(replay.stdout)["classification"], "ATTESTED_EXTERNAL_EXPORT")

    def test_missing_evidence_stays_partial_and_not_observed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "partial.zip"
            bundle.build_hero_bundle(_fixture(root, complete=False), output, source_commit="abc123")
            with zipfile.ZipFile(output) as archive:
                manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["classification"], "PARTIAL")
            self.assertEqual(manifest["observations"]["oracle_boundary"]["status"], "NOT_OBSERVED")
            self.assertEqual(manifest["observations"]["agentloop"]["status"], "NOT_OBSERVED")

    def test_runtime_skill_invocation_is_packaged_with_skill_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = _fixture(root)
            snapshot = evidence / "snapshots" / "20260903T010203Z"
            _write(
                snapshot / "skill-invocations.jsonl",
                json.dumps({"authority_scope": SCOPE, "record_hash": HASH_A, "skill": {"name": "evidence"}})
                + "\n",
            )
            _seal(evidence)
            output = root / "skill.zip"
            bundle.build_hero_bundle(evidence, output, source_commit="abc123")
            with zipfile.ZipFile(output) as archive:
                manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["observations"]["skill"]["status"], "OBSERVED")
            self.assertIn(
                "source/snapshots/20260903T010203Z/skill-invocations.jsonl",
                manifest["observations"]["skill"]["refs"],
            )

    def test_unfinished_or_hash_changed_source_is_blocked_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = _fixture(root)
            manifest = json.loads((evidence / "manifest.json").read_text())
            manifest["status"] = "ACTIVE"
            _write(evidence / "manifest.json", manifest)
            with self.assertRaisesRegex(bundle.HeroBundleError, "completed"):
                bundle.build_hero_bundle(evidence, root / "unfinished.zip", source_commit="abc123")
            self.assertFalse((root / "unfinished.zip").exists())

            evidence = _fixture(root / "other")
            target = next(evidence.glob("snapshots/*/authority/tasks.json"))
            target.write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(bundle.HeroBundleError, "checksum"):
                bundle.build_hero_bundle(evidence, root / "tampered.zip", source_commit="abc123")
            self.assertFalse((root / "tampered.zip").exists())

    def test_only_allowlisted_facts_are_packaged_and_tampering_fails_verify(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = _fixture(root)
            _write(evidence / "private.log", "must-not-be-packed\n")
            output = root / "bundle.zip"
            bundle.build_hero_bundle(evidence, output, source_commit="abc123")
            with zipfile.ZipFile(output) as archive:
                self.assertFalse(any("private.log" in name for name in archive.namelist()))
                self.assertFalse(any("joined_rooms.json" in name for name in archive.namelist()))

            data = bytearray(output.read_bytes())
            data[-32] ^= 1
            output.write_bytes(data)
            with self.assertRaises(bundle.HeroBundleError):
                bundle.verify_hero_bundle(output)

    def test_incomplete_readback_group_is_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = _fixture(root)
            next(evidence.glob("snapshots/*/sessions/manager/readback.jsonl")).unlink()
            _seal(evidence)
            output = root / "partial-group.zip"

            bundle.build_hero_bundle(evidence, output, source_commit="abc123")

            with zipfile.ZipFile(output) as archive:
                manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["classification"], "PARTIAL")
            self.assertEqual(manifest["observations"]["provider_facts"]["status"], "PARTIAL")

    def test_scope_mismatch_and_non_independent_oracles_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = _fixture(root)
            _write(
                evidence / "facts" / "hitl" / "decision.json",
                {"status": "OBSERVED", **{**SCOPE, "run_id": "another-run"}},
            )
            _write(
                evidence / "facts" / "oracles" / "boundary.json",
                _oracle("boundary", identity_ref="oracle-identity:outcome"),
            )
            _seal(evidence)
            output = root / "blocked.zip"

            bundle.build_hero_bundle(evidence, output, source_commit="abc123")

            with zipfile.ZipFile(output) as archive:
                manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["classification"], "PARTIAL")
            self.assertEqual(manifest["observations"]["hitl"]["status"], "BLOCKED")
            self.assertEqual(manifest["observations"]["oracle_outcome"]["status"], "BLOCKED")
            self.assertEqual(manifest["observations"]["oracle_boundary"]["status"], "BLOCKED")

    def test_tool_has_no_runtime_or_orchestration_calls(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in (
            "subprocess",
            "docker",
            "requests",
            "urllib.request",
            "create_project",
            "create_task",
            "send_matrix",
            "invoke_model",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
