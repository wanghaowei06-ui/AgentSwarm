import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from testweaver.contracts.validator import canonical_hash

from testweaver.evaluation.offline_bundle import (
    BundleError,
    build_bundle,
    main,
    verify_external_sealed_proof,
    verify_bundle,
)


class OfflineBundleTests(unittest.TestCase):
    def _inputs(self, root: Path) -> dict[str, Path]:
        receipt = root / "receipt.json"
        manifest = root / "manifest.json"
        sums = root / "SHA256SUMS"
        receipt.write_text('{"classification":"PARTIAL"}\n', encoding="utf-8")
        manifest.write_text('{"run_id":"frozen-run"}\n', encoding="utf-8")
        sums.write_text("frozen\n", encoding="utf-8")
        return {"receipt.json": receipt, "manifest.json": manifest, "SHA256SUMS": sums}

    def _attestation(self, inputs: dict[str, Path]) -> dict[str, str]:
        attestation = {
            "source_ref": "receipt.json",
            "source_hash": "sha256:" + hashlib.sha256(inputs["receipt.json"].read_bytes()).hexdigest(),
            "attestation_ref": "collector://run",
            "source_kind": "agentteams-native-export",
            "manifest_ref": "manifest.json",
            "manifest_hash": "sha256:" + hashlib.sha256(inputs["manifest.json"].read_bytes()).hexdigest(),
        }
        attestation["attestation_hash"] = canonical_hash(attestation)
        return attestation

    def _authority(self) -> dict[str, str]:
        return {
            "campaign_id": "campaign-ref",
            "run_id": "run-ref",
            "pg_revision": "pg-ref",
            "content_hash": "sha256:" + "b" * 64,
            "trace_id": "c" * 32,
        }

    def _sealed_proof(self, inputs: dict[str, Path]) -> dict[str, object]:
        frozen = {
            key: value
            for key, value in self._authority().items()
            if key != "content_hash"
        }
        source = inputs["receipt.json"].read_bytes()
        manifest = inputs["manifest.json"].read_bytes()
        source_hash = "sha256:" + hashlib.sha256(source).hexdigest()
        manifest_hash = "sha256:" + hashlib.sha256(manifest).hexdigest()
        component_base = {
            **frozen,
            "status": "VERIFIED",
            "source_ref": "native:fact",
            "source_hash": source_hash,
            "ref": "fact:component",
        }

        def component(ref: str) -> dict[str, object]:
            value = {**component_base, "ref": ref}
            value["content_hash"] = canonical_hash(value)
            return value

        outcome = {
            **component("oracle:outcome"),
            "status": "PASS",
            "oracle_kind": "outcome",
            "identity_ref": "identity:outcome",
            "process_ref": "process:outcome",
            "result_ref": "result:outcome",
            "result_hash": "sha256:" + "b" * 64,
            "evidence_root_ref": "artifact:evidence-root",
            "evidence_root_hash": "sha256:" + "a" * 64,
            "gold_ref": "gold:private",
        }
        outcome["content_hash"] = canonical_hash(
            {key: value for key, value in outcome.items() if key != "content_hash"}
        )
        boundary = {
            **component("oracle:boundary"),
            "status": "PASS",
            "oracle_kind": "boundary",
            "identity_ref": "identity:boundary",
            "process_ref": "process:boundary",
            "result_ref": "result:boundary",
            "result_hash": "sha256:" + "c" * 64,
            "evidence_root_ref": "artifact:evidence-root",
            "evidence_root_hash": "sha256:" + "a" * 64,
            "gold_ref": None,
        }
        boundary["content_hash"] = canonical_hash(
            {key: value for key, value in boundary.items() if key != "content_hash"}
        )
        sealed_source = {
            "source_ref": "receipt.json",
            "source_hash": source_hash,
            "manifest_ref": "manifest.json",
            "manifest_hash": manifest_hash,
            "seal_ref": "authority-seal:run",
            "source_kind": "agentteams-native-sealed-authority",
        }
        sealed_source["seal_hash"] = canonical_hash(sealed_source)
        proof = {
            "schema_version": "testweaver.m4.external-sealed-authority/v1",
            "proof_id": "authority-proof:run",
            **frozen,
            "evidence_root_ref": "artifact:evidence-root",
            "evidence_root_hash": "sha256:" + "a" * 64,
            "matrix_hitl_readback": component("fact:hitl"),
            "dsh_skill": component("fact:dsh-skill"),
            "recovery": component("fact:recovery"),
            "oracles": [outcome, boundary],
            "agentloop_readback": component("fact:agentloop"),
            "sealed_source": sealed_source,
        }
        proof["content_hash"] = canonical_hash(proof)
        return proof

    def _build(self, output: Path, inputs: dict[str, Path], **kwargs: object) -> dict[str, object]:
        source_path = inputs.get("receipt.json")
        return build_bundle(
            output,
            inputs,
            raw_source_path=source_path,
            **kwargs,
        )

    def test_build_is_deterministic_and_verifies_allowlisted_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self._inputs(root)
            first = root / "first.zip"
            second = root / "second.zip"
            attestation = self._attestation(inputs)
            self._build(
                first,
                inputs,
                classification="PARTIAL",
                source_commit="abc123",
                raw_source_attestation=attestation,
            )
            self._build(
                second,
                inputs,
                classification="PARTIAL",
                source_commit="abc123",
                raw_source_attestation=attestation,
            )
            self.assertEqual(first.read_bytes(), second.read_bytes())
            result = verify_bundle(first, expected_files=tuple(inputs), expected_source_commit="abc123")
            self.assertEqual(result["classification"], "PARTIAL")
            self.assertEqual(result["files"], ["SHA256SUMS", "manifest.json", "receipt.json"])

    def test_rejects_symlinks_and_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self._inputs(root)
            link = root / "link"
            link.symlink_to(inputs["receipt.json"])
            inputs["link"] = link
            with self.assertRaises(BundleError):
                self._build(
                    root / "symlink.zip",
                    inputs,
                    classification="PARTIAL",
                    source_commit="abc123",
                    raw_source_attestation=self._attestation(inputs),
                )
            with self.assertRaises(BundleError):
                self._build(
                    root / "traversal.zip",
                    {"../receipt.json": inputs["receipt.json"]},
                    classification="PARTIAL",
                    source_commit="abc123",
                    raw_source_attestation=self._attestation(inputs),
                )

    def test_extra_unlisted_files_are_not_packed_and_classification_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self._inputs(root)
            (root / "untracked.txt").write_text("not allowlisted", encoding="utf-8")
            bundle = root / "bundle.zip"
            self._build(
                bundle,
                inputs,
                classification="NOT_OBSERVED",
                source_commit="abc123",
                raw_source_attestation=self._attestation(inputs),
            )
            result = verify_bundle(bundle, expected_files=tuple(inputs), expected_source_commit="abc123")
            self.assertEqual(result["classification"], "NOT_OBSERVED")
            self.assertNotIn("untracked.txt", result["files"])

    def test_raw_source_attestation_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self._inputs(root)
            with self.assertRaisesRegex(BundleError, "attestation"):
                build_bundle(root / "missing.zip", inputs, classification="PARTIAL", source_commit="abc123", raw_source_attestation=None)  # type: ignore[arg-type]

    def test_live_request_is_downgraded_without_external_sealed_proof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self._inputs(root)
            result = self._build(
                root / "live.zip",
                inputs,
                classification="LIVE_AGENTTEAMS_HERO",
                source_commit="abc123",
                raw_source_attestation=self._attestation(inputs),
                authority_tuple=self._authority(),
            )
            self.assertEqual(result["classification"], "PARTIAL")

    def test_live_request_drops_caller_authority_without_sealed_proof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self._inputs(root)
            bundle = root / "live.zip"
            authority = self._authority()
            self._build(
                bundle,
                inputs,
                classification="LIVE_AGENTTEAMS_HERO",
                source_commit="abc123",
                raw_source_attestation=self._attestation(inputs),
                authority_tuple=authority,
            )
            result = verify_bundle(
                bundle,
                expected_files=tuple(inputs),
                expected_source_commit="abc123",
                expected_authority_tuple=authority,
            )
            self.assertEqual(result["classification"], "PARTIAL")
            self.assertNotIn("authority_tuple", result)

    def test_external_sealed_proof_is_required_to_reach_live(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self._inputs(root)
            proof = self._sealed_proof(inputs)
            self.assertEqual(
                verify_external_sealed_proof(proof)["classification"],
                "NOT_VERIFIED",
            )
            bundle = root / "sealed.zip"
            result = self._build(
                bundle,
                inputs,
                classification="LIVE_AGENTTEAMS_HERO",
                source_commit="abc123",
                raw_source_attestation=self._attestation(inputs),
                authority_tuple=self._authority(),
                external_authority_proof=proof,
            )
            self.assertEqual(result["classification"], "LIVE_AGENTTEAMS_HERO")
            verified = verify_bundle(
                bundle,
                expected_files=tuple(inputs),
                expected_source_commit="abc123",
                expected_authority_tuple=self._authority(),
            )
            self.assertEqual(verified["classification"], "LIVE_AGENTTEAMS_HERO")
            self.assertEqual(verified["proof_id"], "authority-proof:run")

    def test_sealed_proof_tampering_or_missing_component_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self._inputs(root)
            proof = self._sealed_proof(inputs)
            tampered = json.loads(json.dumps(proof))
            tampered["run_id"] = "run:other"
            with self.assertRaisesRegex(BundleError, "content_hash"):
                verify_external_sealed_proof(tampered)

            missing = json.loads(json.dumps(proof))
            del missing["agentloop_readback"]
            missing["content_hash"] = canonical_hash(
                {key: value for key, value in missing.items() if key != "content_hash"}
            )
            with self.assertRaisesRegex(BundleError, "agentloop"):
                verify_external_sealed_proof(missing)

            boundary_gold = json.loads(json.dumps(proof))
            boundary_gold["oracles"][1]["gold_ref"] = "gold:leak"
            boundary_gold["oracles"][1]["content_hash"] = canonical_hash(
                {
                    key: value
                    for key, value in boundary_gold["oracles"][1].items()
                    if key != "content_hash"
                }
            )
            boundary_gold["content_hash"] = canonical_hash(
                {key: value for key, value in boundary_gold.items() if key != "content_hash"}
            )
            with self.assertRaisesRegex(BundleError, "gold_ref"):
                verify_external_sealed_proof(boundary_gold)

            component_hash = json.loads(json.dumps(proof))
            component_hash["dsh_skill"]["source_hash"] = "sha256:" + "d" * 64
            component_hash["dsh_skill"]["content_hash"] = canonical_hash(
                {
                    key: value
                    for key, value in component_hash["dsh_skill"].items()
                    if key != "content_hash"
                }
            )
            component_hash["content_hash"] = canonical_hash(
                {key: value for key, value in component_hash.items() if key != "content_hash"}
            )
            with self.assertRaisesRegex(BundleError, "source_hash"):
                verify_external_sealed_proof(
                    component_hash,
                    bundle_files=inputs,
                    raw_source_attestation=self._attestation(inputs),
                )

    def test_read_only_verify_and_replay_cli_do_not_upgrade_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self._inputs(root)
            bundle = root / "partial.zip"
            self._build(
                bundle,
                inputs,
                classification="PARTIAL",
                source_commit="abc123",
                raw_source_attestation=self._attestation(inputs),
            )
            self.assertEqual(
                main(
                    [
                        "verify",
                        str(bundle),
                        "--expected-file",
                        "receipt.json",
                        "--expected-file",
                        "manifest.json",
                        "--expected-file",
                        "SHA256SUMS",
                        "--source-commit",
                        "abc123",
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(
                    [
                        "replay",
                        str(bundle),
                        "--expected-file",
                        "receipt.json",
                        "--expected-file",
                        "manifest.json",
                        "--expected-file",
                        "SHA256SUMS",
                        "--source-commit",
                        "abc123",
                    ]
                ),
                0,
            )

    def test_partial_bundle_cannot_be_upgraded_by_an_authority_argument(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self._inputs(root)
            bundle = root / "partial.zip"
            self._build(
                bundle,
                inputs,
                classification="PARTIAL",
                source_commit="abc123",
                raw_source_attestation=self._attestation(inputs),
            )
            result = verify_bundle(
                bundle,
                expected_files=tuple(inputs),
                expected_source_commit="abc123",
                expected_authority_tuple=self._authority(),
            )
            self.assertEqual(result["classification"], "PARTIAL")

    def test_offline_bundle_preserves_attested_external_without_live_label(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self._inputs(root)
            bundle = root / "attested.zip"
            self._build(
                bundle,
                inputs,
                classification="ATTESTED_EXTERNAL_EXPORT",
                source_commit="abc123",
                raw_source_attestation=self._attestation(inputs),
            )
            result = verify_bundle(bundle, expected_files=tuple(inputs), expected_source_commit="abc123")
            self.assertEqual(result["classification"], "ATTESTED_EXTERNAL_EXPORT")
            self.assertNotIn("LIVE", result["classification"])

    def test_raw_source_hash_is_bound_to_actual_allowlisted_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self._inputs(root)
            attestation = self._attestation(inputs)
            attestation["source_hash"] = "sha256:" + "0" * 64
            attestation["attestation_hash"] = canonical_hash(
                {key: value for key, value in attestation.items() if key != "attestation_hash"}
            )
            with self.assertRaisesRegex(BundleError, "source_hash"):
                self._build(
                    root / "bad-source.zip",
                    inputs,
                    classification="PARTIAL",
                    source_commit="abc123",
                    raw_source_attestation=attestation,
                )

    def test_zip_member_and_total_size_caps_are_checked_before_readback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bomb = root / "bomb.zip"
            import zipfile

            with zipfile.ZipFile(bomb, "w") as archive:
                info = zipfile.ZipInfo("receipt.json")
                info.file_size = 9 * 1024 * 1024
                archive.writestr(info, b"x" * (9 * 1024 * 1024))
            with self.assertRaisesRegex(BundleError, "size limit"):
                verify_bundle(
                    bomb,
                    expected_files=("receipt.json",),
                    expected_source_commit="abc123",
                )


if __name__ == "__main__":
    unittest.main()
