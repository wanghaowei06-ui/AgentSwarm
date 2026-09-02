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
            "source_ref": "native-source://run",
            "source_hash": "sha256:" + "a" * 64,
            "attestation_ref": "collector://run",
            "source_kind": "agentteams-native-export",
            "manifest_ref": "manifest.json",
            "manifest_hash": "sha256:" + hashlib.sha256(inputs["manifest.json"].read_bytes()).hexdigest(),
        }
        attestation["attestation_hash"] = canonical_hash(attestation)
        return attestation

    def test_build_is_deterministic_and_verifies_allowlisted_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self._inputs(root)
            first = root / "first.zip"
            second = root / "second.zip"
            attestation = self._attestation(inputs)
            build_bundle(
                first,
                inputs,
                classification="PARTIAL",
                source_commit="abc123",
                raw_source_attestation=attestation,
            )
            build_bundle(
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
                build_bundle(
                    root / "symlink.zip",
                    inputs,
                    classification="PARTIAL",
                    source_commit="abc123",
                    raw_source_attestation=self._attestation(inputs),
                )
            with self.assertRaises(BundleError):
                build_bundle(
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
            build_bundle(
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

    def test_offline_bundle_cannot_claim_live(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self._inputs(root)
            with self.assertRaisesRegex(BundleError, "LIVE"):
                build_bundle(
                    root / "live.zip",
                    inputs,
                    classification="LIVE_AGENTTEAMS_HERO",
                    source_commit="abc123",
                    raw_source_attestation=self._attestation(inputs),
                )

    def test_offline_bundle_preserves_attested_external_without_live_label(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self._inputs(root)
            bundle = root / "attested.zip"
            build_bundle(
                bundle,
                inputs,
                classification="ATTESTED_EXTERNAL_EXPORT",
                source_commit="abc123",
                raw_source_attestation=self._attestation(inputs),
            )
            result = verify_bundle(bundle, expected_files=tuple(inputs), expected_source_commit="abc123")
            self.assertEqual(result["classification"], "ATTESTED_EXTERNAL_EXPORT")
            self.assertNotIn("LIVE", result["classification"])


if __name__ == "__main__":
    unittest.main()
