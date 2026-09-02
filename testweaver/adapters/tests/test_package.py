"""Static package and image wiring checks; no image or provider is invoked."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
from unittest import mock
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

    def test_collect_tracks_root_dev_dependency_for_runtime_plugin(self) -> None:
        source = ROOT / "scripts/package_dsh.py"
        spec = importlib.util.spec_from_file_location("package_dsh", source)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "runtime"
            instance = root / "node_modules/.pnpm/@deepseek-ai+dsh-llm@fixture/node_modules/@deepseek-ai/dsh-llm"
            instance.mkdir(parents=True)
            (instance / "package.json").write_text(
                json.dumps({"name": "@deepseek-ai/dsh-llm", "version": "fixture"}),
                encoding="utf-8",
            )
            (root / "node_modules/@deepseek-ai").mkdir(parents=True)
            (root / "node_modules/@deepseek-ai/dsh-llm").symlink_to(
                "../.pnpm/@deepseek-ai+dsh-llm@fixture/node_modules/@deepseek-ai/dsh-llm",
                target_is_directory=True,
            )
            (root / "package.json").write_text(
                json.dumps(
                    {
                        "name": "@deepseek-ai/dsh",
                        "devDependencies": {"@deepseek-ai/dsh-llm": "workspace:^"},
                    }
                ),
                encoding="utf-8",
            )
            seen, _missing = module.collect(root)
            names = {package.get("name") for _path, package in seen.values()}
            self.assertIn("@deepseek-ai/dsh-llm", names)

    def test_packaged_runtime_links_root_dev_dependency_and_resolves(self) -> None:
        source = ROOT / "scripts/package_dsh.py"
        spec = importlib.util.spec_from_file_location("package_dsh", source)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            source_root = Path(temporary) / "source"
            output = Path(temporary) / "output"
            instance = source_root / "node_modules/.pnpm/@deepseek-ai+dsh-llm@fixture/node_modules/@deepseek-ai/dsh-llm"
            instance.mkdir(parents=True)
            (instance / "package.json").write_text(
                json.dumps(
                    {
                        "name": "@deepseek-ai/dsh-llm",
                        "version": "fixture",
                        "main": "lib/index.js",
                    }
                ),
                encoding="utf-8",
            )
            (instance / "lib").mkdir()
            (instance / "lib/index.js").write_text("module.exports = {};\n", encoding="utf-8")
            (source_root / "node_modules/@deepseek-ai").mkdir(parents=True)
            (source_root / "node_modules/@deepseek-ai/dsh-llm").symlink_to(
                "../.pnpm/@deepseek-ai+dsh-llm@fixture/node_modules/@deepseek-ai/dsh-llm",
                target_is_directory=True,
            )
            (source_root / "package.json").write_text(
                json.dumps(
                    {
                        "name": "@deepseek-ai/dsh",
                        "devDependencies": {"@deepseek-ai/dsh-llm": "workspace:^"},
                    }
                ),
                encoding="utf-8",
            )
            (source_root / "lib").mkdir()
            (source_root / "lib/bin.js").write_text("module.exports = {};\n", encoding="utf-8")
            (source_root / "config").mkdir()
            with mock.patch.object(module, "validate_inputs", return_value={}):
                module.build(source_root, output, Path("/unused/lock"), Path("/unused/provenance"))
            link = output / "node_modules/@deepseek-ai/dsh-llm"
            self.assertTrue(link.is_symlink())
            module.preflight_plugin_tree(output)

    def test_noncritical_unresolved_root_dependency_is_skipped_and_reported(self) -> None:
        source = ROOT / "scripts/package_dsh.py"
        spec = importlib.util.spec_from_file_location("package_dsh", source)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            source_root = Path(temporary) / "source"
            output = Path(temporary) / "output"
            instance = source_root / "node_modules/.pnpm/@deepseek-ai+dsh-llm@fixture/node_modules/@deepseek-ai/dsh-llm"
            (instance / "lib").mkdir(parents=True)
            (instance / "package.json").write_text(
                json.dumps(
                    {
                        "name": "@deepseek-ai/dsh-llm",
                        "version": "fixture",
                        "main": "lib/index.js",
                    }
                ),
                encoding="utf-8",
            )
            (instance / "lib/index.js").write_text("module.exports = {};\n", encoding="utf-8")
            (source_root / "node_modules/@deepseek-ai").mkdir(parents=True)
            (source_root / "node_modules/@deepseek-ai/dsh-llm").symlink_to(
                "../.pnpm/@deepseek-ai+dsh-llm@fixture/node_modules/@deepseek-ai/dsh-llm",
                target_is_directory=True,
            )
            (source_root / "package.json").write_text(
                json.dumps(
                    {
                        "name": "@deepseek-ai/dsh",
                        "dependencies": {
                            "@deepseek-ai/dsh-client-ui-cordis": "workspace:^",
                        },
                        "devDependencies": {"@deepseek-ai/dsh-llm": "workspace:^"},
                    }
                ),
                encoding="utf-8",
            )
            (source_root / "lib").mkdir()
            (source_root / "lib/bin.js").write_text("module.exports = {};\n", encoding="utf-8")
            (source_root / "config").mkdir()
            with mock.patch.object(module, "validate_inputs", return_value={}):
                summary = module.build(source_root, output, Path("/unused/lock"), Path("/unused/provenance"))
            self.assertEqual(summary["skipped_unresolved"], ["@deepseek-ai/dsh-client-ui-cordis"])
            self.assertFalse((output / "node_modules/@deepseek-ai/dsh-client-ui-cordis").exists())
            self.assertTrue((output / "node_modules/@deepseek-ai/dsh-llm").is_symlink())

    def test_missing_headless_plugin_is_fail_closed(self) -> None:
        source = ROOT / "scripts/package_dsh.py"
        spec = importlib.util.spec_from_file_location("package_dsh", source)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            source_root = Path(temporary) / "source"
            output = Path(temporary) / "output"
            source_root.mkdir()
            (source_root / "node_modules").mkdir()
            (source_root / "package.json").write_text(
                json.dumps(
                    {
                        "name": "@deepseek-ai/dsh",
                        "devDependencies": {"@deepseek-ai/dsh-llm": "workspace:^"},
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(module, "validate_inputs", return_value={}):
                with self.assertRaisesRegex(module.PackageError, "headless"):
                    module.build(source_root, output, Path("/unused/lock"), Path("/unused/provenance"))

    def test_plugin_tree_preflight_rejects_missing_root_dev_dependency(self) -> None:
        source = ROOT / "scripts/package_dsh.py"
        spec = importlib.util.spec_from_file_location("package_dsh", source)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            (output / "node_modules").mkdir(parents=True)
            (output / "package.json").write_text(
                json.dumps(
                    {
                        "name": "@deepseek-ai/dsh",
                        "devDependencies": {"@deepseek-ai/dsh-llm": "workspace:^"},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(module.PackageError, "plugin-tree"):
                module.preflight_plugin_tree(output)

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

    def test_package_skill_has_qwenpaw_frontmatter(self) -> None:
        skill = (PACKAGE / "skills/testweaver-native-external-worker/SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(skill.startswith("---\n"))
        end = skill.find("\n---\n", len("---\n"))
        self.assertGreater(end, len("---\n"))
        frontmatter = skill[len("---\n") : end]
        self.assertRegex(
            frontmatter,
            r"(?m)^name:\s*testweaver-native-external-worker\s*$",
        )
        description = re.search(r"(?m)^description:\s*(.+?)\s*$", frontmatter)
        self.assertIsNotNone(description)
        self.assertTrue(description.group(1).strip().strip('"').strip("'"))

    def test_worker_system_and_skill_order_fresh_task_native_call(self) -> None:
        system = (PACKAGE / "config/AGENTS.md").read_text(encoding="utf-8")
        skill = (PACKAGE / "skills/testweaver-native-external-worker/SKILL.md").read_text(encoding="utf-8")
        for content in (system, skill):
            normalized = " ".join(content.split())
            self.assertIn("current task/context references", normalized)
            self.assertIn("prior-run history", normalized)
            self.assertIn("native_worker_execute", normalized)
            self.assertIn("first allowed work action", normalized)
            self.assertNotRegex(content, r"(?i)m2g-|native-m0|room[_ -]?id\s*[:=]")

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
