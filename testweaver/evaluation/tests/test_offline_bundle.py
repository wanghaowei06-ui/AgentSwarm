import hashlib
import tempfile
import unittest
from pathlib import Path

from testweaver.contracts.validator import canonical_hash

from testweaver.evaluation.offline_bundle import (
    BundleError,
    build_bundle,
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
