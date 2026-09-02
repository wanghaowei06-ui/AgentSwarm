"""Static package and image wiring checks; no image or provider is invoked."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "qwenpaw-package"


class PackageWiringTests(unittest.TestCase):
    def test_packager_removes_links_that_escape_output_root(self) -> None:
        source = ROOT / "scripts/package_dsh.py"
        spec = importlib.util.spec_from_file_location("package_dsh", source)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "runtime"
            root.mkdir()
            (root / "inside").mkdir()
            (root / "inside-link").symlink_to("inside", target_is_directory=True)
            (root / "source-link").symlink_to("/outside/materialized-source")
            module.remove_broken_symlinks(root)
            self.assertTrue((root / "inside-link").is_symlink())
            self.assertFalse((root / "source-link").exists())

    def test_agentspec_package_uses_official_skill_and_stdio_shape(self) -> None:
        manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
        mcp = json.loads((PACKAGE / "mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], "agentteams.agentspec/v1")
        self.assertEqual(manifest["version"], "0.1.0")
        self.assertEqual(manifest["source"]["contract_commit"], "ae9e239")
        self.assertEqual(len(manifest["skills"]), 1)
        self.assertEqual(len(mcp["mcpServers"]), 1)
        server = mcp["mcpServers"]["testweaver-native-worker"]
        self.assertEqual(server["transport"], "stdio")
        self.assertEqual(server["command"], "/opt/venv/qwenpaw/bin/python")
        self.assertEqual(server["args"], ["-m", "testweaver.adapters.mcp_server"])
        self.assertNotRegex(json.dumps(manifest), r'"value"\s*:')
        self.assertNotRegex(json.dumps(mcp), r'"value"\s*:')

    def test_package_skill_preserves_native_ownership_and_no_secret_values(self) -> None:
        skill = (PACKAGE / "skills/testweaver-native-external-worker/SKILL.md").read_text(encoding="utf-8")
        for marker in ("task state", "native TeamHarness", "Missing upstream usage", "not LIVE provider evidence"):
            self.assertIn(marker, skill)
        self.assertNotRegex(skill, re.compile(r"(?i)(api[_-]?key|token|password)\s*[:=]\s*[^`\s]+"))
        for forbidden in ("create_project", "delegate_task", "submit_task", "scheduler"):
            self.assertNotIn(forbidden, skill)

    def test_extension_build_is_immutable_and_dsh_package_is_fixed(self) -> None:
        dockerfile = (ROOT / "Dockerfile.qwenpaw").read_text(encoding="utf-8")
        script = ROOT / "build-qwenpaw-native-extension.sh"
        self.assertIn("ARG QWENPAW_BASE_IMAGE", dockerfile)
        self.assertIn("COPY ${TESTWEAVER_DSH_PACKAGE}", dockerfile)
        self.assertIn("@deepseek-ai/dsh/lib/bin.js", dockerfile)
        self.assertIn("CODEX_CLI_SPEC=@openai/codex@0.152.0", dockerfile)
        self.assertNotIn("testweaver/evidence", dockerfile)
        self.assertNotIn("--privileged", dockerfile)
        self.assertEqual(subprocess.run(["bash", "-n", str(script)], check=False).returncode, 0)
        self.assertIn("TESTWEAVER_QWENPAW_BASE_IMAGE", script.read_text(encoding="utf-8"))
        self.assertIn("TESTWEAVER_QWENPAW_BASE_IMAGE_ID", script.read_text(encoding="utf-8"))
        self.assertIn("TESTWEAVER_DSH_SOURCE_DIR", script.read_text(encoding="utf-8"))
        self.assertIn("package_dsh.py", script.read_text(encoding="utf-8"))
        self.assertIn("mcp_client.py", script.read_text(encoding="utf-8"))
        self.assertIn("mcp_server.py mcp_client.py", dockerfile)

    def test_dsh_provenance_and_packager_are_pinned_without_cache_copy(self) -> None:
        provenance = json.loads((ROOT / "dsh-build-provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance["upstream"]["commit"], "47f943859bef60e4160492346772ded9b24f765a")
        self.assertEqual(provenance["upstream"]["tree"], "f904efab9ef435201d6ba4da88a34d6366568272")
        self.assertEqual(provenance["upstream"]["version"], "0.1.0-rc.5")
        packager = (ROOT / "scripts/package_dsh.py").read_text(encoding="utf-8")
        self.assertIn("node_modules_source_copied", packager)
        self.assertIn("EXPECTED_MATERIALIZED_LOCK_SHA256", packager)
        self.assertNotIn("shutil.copytree(source / \"node_modules\"", packager)
        self.assertNotRegex(packager, r"(?i)(api[_-]?key|token|password)\s*[:=]\s*[^\s]+")

    def test_new_bridge_nonblank_production_code_stays_near_budget(self) -> None:
        paths = (ROOT / "executor.py", ROOT / "mcp_server.py")
        nonblank = sum(1 for path in paths for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        self.assertLessEqual(nonblank, 470)


if __name__ == "__main__":
    unittest.main()
