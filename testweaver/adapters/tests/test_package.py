"""Static package and image wiring checks; no image or provider is invoked."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "qwenpaw-package"


class PackageWiringTests(unittest.TestCase):
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

    def test_extension_build_is_immutable_and_dsh_is_explicit(self) -> None:
        dockerfile = (ROOT / "Dockerfile.qwenpaw").read_text(encoding="utf-8")
        script = ROOT / "build-qwenpaw-native-extension.sh"
        self.assertIn("ARG QWENPAW_BASE_IMAGE", dockerfile)
        self.assertIn("COPY ${TESTWEAVER_DSH_BINARY}", dockerfile)
        self.assertIn("CODEX_CLI_SPEC=@openai/codex@0.152.0", dockerfile)
        self.assertNotIn("testweaver/evidence", dockerfile)
        self.assertNotIn("--privileged", dockerfile)
        self.assertEqual(subprocess.run(["bash", "-n", str(script)], check=False).returncode, 0)
        self.assertIn("TESTWEAVER_QWENPAW_BASE_IMAGE", script.read_text(encoding="utf-8"))
        self.assertIn("TESTWEAVER_DSH_BINARY", script.read_text(encoding="utf-8"))

    def test_new_bridge_nonblank_production_code_stays_near_budget(self) -> None:
        paths = (ROOT / "executor.py", ROOT / "mcp_server.py")
        nonblank = sum(1 for path in paths for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        self.assertLessEqual(nonblank, 470)


if __name__ == "__main__":
    unittest.main()
