from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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

    def test_build_is_deterministic_and_verifies_allowlisted_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self._inputs(root)
            first = root / "first.zip"
            second = root / "second.zip"
            build_bundle(first, inputs, classification="PARTIAL", source_commit="abc123")
            build_bundle(second, inputs, classification="PARTIAL", source_commit="abc123")
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
                build_bundle(root / "symlink.zip", inputs, classification="PARTIAL", source_commit="abc123")
            with self.assertRaises(BundleError):
                build_bundle(root / "traversal.zip", {"../receipt.json": inputs["receipt.json"]}, classification="PARTIAL", source_commit="abc123")

    def test_extra_unlisted_files_are_not_packed_and_classification_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self._inputs(root)
            (root / "untracked.txt").write_text("not allowlisted", encoding="utf-8")
            bundle = root / "bundle.zip"
            build_bundle(bundle, inputs, classification="NOT_OBSERVED", source_commit="abc123")
            result = verify_bundle(bundle, expected_files=tuple(inputs), expected_source_commit="abc123")
            self.assertEqual(result["classification"], "NOT_OBSERVED")
            self.assertNotIn("untracked.txt", result["files"])


if __name__ == "__main__":
    unittest.main()
