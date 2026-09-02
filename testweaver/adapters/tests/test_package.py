"""Static package and image wiring checks; no image or provider is invoked."""

from __future__ import annotations

import importlib.util
import json
import os
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

    def test_collected_forest_entries_project_missing_root_links_and_reject_conflicts(self) -> None:
        source = ROOT / "scripts/package_dsh.py"
        spec = importlib.util.spec_from_file_location("package_dsh", source)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            source_root = Path(temporary) / "source"
            output = Path(temporary) / "output"
            packages = {
                "agent_loop": (
                    "@deepseek-ai+dsh-agent-loop@fixture",
                    "@deepseek-ai/dsh-agent-loop",
                ),
                "session_title": (
                    "@deepseek-ai+dsh-session-title@fixture",
                    "@deepseek-ai/dsh-session-title",
                ),
                "llm": ("@deepseek-ai+dsh-llm@fixture", "@deepseek-ai/dsh-llm"),
                "zod": ("zod@fixture", "zod"),
                "scoped": ("@scope+pkg@fixture", "@scope/pkg"),
            }

            def package_dir(instance_name: str, package_name: str) -> Path:
                return (
                    source_root
                    / "node_modules/.pnpm"
                    / instance_name
                    / "node_modules"
                    / Path(*package_name.split("/"))
                )

            for instance_name, package_name in packages.values():
                directory = package_dir(instance_name, package_name)
                directory.mkdir(parents=True)
                (directory / "package.json").write_text(
                    json.dumps({"name": package_name, "version": "fixture", "main": "index.js"}),
                    encoding="utf-8",
                )
                (directory / "index.js").write_text("module.exports = {};\n", encoding="utf-8")

            agent_loop_dir = package_dir(*packages["agent_loop"])
            (agent_loop_dir / "package.json").write_text(
                json.dumps(
                    {
                        "name": "@deepseek-ai/dsh-agent-loop",
                        "version": "fixture",
                        "main": "index.js",
                        "dependencies": {"zod": "fixture", "@scope/pkg": "fixture"},
                    }
                ),
                encoding="utf-8",
            )
            for key in ("zod", "scoped"):
                _, package_name = packages[key]
                nested = agent_loop_dir / "node_modules" / Path(*package_name.split("/"))
                nested.parent.mkdir(parents=True, exist_ok=True)
                nested.symlink_to(
                    Path(os.path.relpath(package_dir(*packages[key]), nested.parent)),
                    target_is_directory=True,
                )

            source_root_targets = {}
            source_root_scope = source_root / "node_modules"
            for key in ("agent_loop", "session_title", "llm"):
                instance_name, package_name = packages[key]
                link = source_root_scope / Path(*package_name.split("/"))
                link.parent.mkdir(parents=True, exist_ok=True)
                target = os.path.relpath(package_dir(instance_name, package_name), link.parent)
                link.symlink_to(target, target_is_directory=True)
                source_root_targets[package_name] = target

            source_forest = source_root / "node_modules/.pnpm/node_modules"
            for instance_name, package_name in packages.values():
                link = source_forest / Path(*package_name.split("/"))
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(
                    os.path.relpath(package_dir(instance_name, package_name), link.parent),
                    target_is_directory=True,
                )
            phantom = source_root / "node_modules/.pnpm/phantom@fixture/node_modules/phantom"
            phantom.mkdir(parents=True)
            (phantom / "package.json").write_text(
                json.dumps({"name": "phantom", "version": "fixture", "main": "index.js"}),
                encoding="utf-8",
            )
            (phantom / "index.js").write_text("module.exports = {};\n", encoding="utf-8")
            (source_forest / "phantom").symlink_to(
                os.path.relpath(phantom, source_forest), target_is_directory=True
            )

            (source_root / "package.json").write_text(
                json.dumps(
                    {
                        "name": "@deepseek-ai/dsh",
                        "devDependencies": {
                            "@deepseek-ai/dsh-agent-loop": "fixture",
                            "@deepseek-ai/dsh-session-title": "fixture",
                            "@deepseek-ai/dsh-llm": "fixture",
                        },
                    }
                ),
                encoding="utf-8",
            )
            (source_root / "lib").mkdir()
            (source_root / "lib/bin.js").write_text("module.exports = {};\n", encoding="utf-8")
            (source_root / "config").mkdir()
            with mock.patch.object(module, "validate_inputs", return_value={}):
                summary = module.build(
                    source_root, output, Path("/unused/lock"), Path("/unused/provenance")
                )

            self.assertEqual(summary["pnpm_forest_links_copied"], 5)
            self.assertEqual(summary["pnpm_root_links_projected"], 2)
            self.assertEqual(summary["pnpm_root_links_skipped"], 3)
            for package_name in ("zod", "@scope/pkg"):
                link = output / "node_modules" / Path(*package_name.split("/"))
                forest_link = output / "node_modules/.pnpm/node_modules" / Path(*package_name.split("/"))
                self.assertTrue(link.is_symlink())
                self.assertFalse(os.readlink(link).startswith("/"))
                self.assertEqual(link.resolve(), forest_link.resolve())
            for package_name, target in source_root_targets.items():
                self.assertEqual(
                    os.readlink(output / "node_modules" / Path(*package_name.split("/"))),
                    target,
                )
            self.assertEqual(
                module._node_resolvable(
                    output,
                    ["zod", "@deepseek-ai/dsh-agent-loop", "@deepseek-ai/dsh-session-title"],
                ),
                {"zod", "@deepseek-ai/dsh-agent-loop", "@deepseek-ai/dsh-session-title"},
            )
            self.assertFalse((output / "node_modules/phantom").exists())
            self.assertFalse((output / "node_modules/.pnpm/node_modules/phantom").exists())

            conflict = output / "node_modules/zod"
            conflict.unlink()
            conflict.symlink_to("/outside/not-allowed", target_is_directory=True)
            with self.assertRaisesRegex(module.PackageError, "root forest projection"):
                module.project_pnpm_forest_root_links(output, {"zod"})
            self.assertEqual(os.readlink(conflict), "/outside/not-allowed")

    def test_nested_cordis_import_is_red_without_forest_and_green_after_package(self) -> None:
        source = ROOT / "scripts/package_dsh.py"
        spec = importlib.util.spec_from_file_location("package_dsh", source)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            source_root = Path(temporary) / "source"
            output = Path(temporary) / "output"
            dsh_instance_name = "@deepseek-ai+dsh-llm@fixture"
            loader_instance_name = "@deepseek-ai+cordis-plugin-loader@fixture"
            dsh_instance = (
                source_root
                / "node_modules/.pnpm"
                / dsh_instance_name
                / "node_modules/@deepseek-ai/dsh-llm"
            )
            loader_instance = (
                source_root
                / "node_modules/.pnpm"
                / loader_instance_name
                / "node_modules/@deepseek-ai/cordis-plugin-loader"
            )
            dsh_instance.joinpath("lib").mkdir(parents=True)
            loader_instance.joinpath("lib").mkdir(parents=True)
            (dsh_instance / "package.json").write_text(
                json.dumps(
                    {
                        "name": "@deepseek-ai/dsh-llm",
                        "version": "fixture",
                        "type": "module",
                        "exports": "./lib/index.mjs",
                    }
                ),
                encoding="utf-8",
            )
            (dsh_instance / "lib/index.mjs").write_text(
                'export const marker = "dsh-llm";\n', encoding="utf-8"
            )
            (loader_instance / "package.json").write_text(
                json.dumps(
                    {
                        "name": "@deepseek-ai/cordis-plugin-loader",
                        "version": "fixture",
                        "type": "module",
                        "exports": "./lib/index.mjs",
                    }
                ),
                encoding="utf-8",
            )
            (loader_instance / "lib/index.mjs").write_text(
                "export async function importHeadlessPlugin() {\n"
                '  return await import("@deepseek-ai/dsh-llm");\n'
                "}\n",
                encoding="utf-8",
            )
            scope = source_root / "node_modules/@deepseek-ai"
            scope.mkdir(parents=True)
            (scope / "dsh-llm").symlink_to(
                f"../.pnpm/{dsh_instance_name}/node_modules/@deepseek-ai/dsh-llm",
                target_is_directory=True,
            )
            (scope / "cordis-plugin-loader").symlink_to(
                f"../.pnpm/{loader_instance_name}/node_modules/@deepseek-ai/cordis-plugin-loader",
                target_is_directory=True,
            )
            forest_scope = source_root / "node_modules/.pnpm/node_modules/@deepseek-ai"
            forest_scope.mkdir(parents=True)
            (forest_scope / "dsh-llm").symlink_to(
                f"../../{dsh_instance_name}/node_modules/@deepseek-ai/dsh-llm",
                target_is_directory=True,
            )
            phantom_instance = (
                source_root
                / "node_modules/.pnpm/@deepseek-ai+phantom@fixture"
                / "node_modules/@deepseek-ai/phantom"
            )
            phantom_instance.mkdir(parents=True)
            (phantom_instance / "package.json").write_text(
                json.dumps({"name": "@deepseek-ai/phantom", "version": "fixture"}),
                encoding="utf-8",
            )
            (forest_scope / "phantom").symlink_to(
                "../../@deepseek-ai+phantom@fixture/node_modules/@deepseek-ai/phantom",
                target_is_directory=True,
            )
            (forest_scope / "broken").symlink_to(
                "../../@deepseek-ai+missing@fixture/node_modules/@deepseek-ai/missing",
                target_is_directory=True,
            )
            (forest_scope / "absolute").symlink_to(
                "/outside/materialized-source", target_is_directory=True
            )
            (source_root / "package.json").write_text(
                json.dumps(
                    {
                        "name": "@deepseek-ai/dsh",
                        "devDependencies": {
                            "@deepseek-ai/dsh-llm": "workspace:^",
                            "@deepseek-ai/cordis-plugin-loader": "workspace:^",
                        },
                    }
                ),
                encoding="utf-8",
            )
            (source_root / "lib").mkdir()
            (source_root / "lib/bin.js").write_text("export {};\n", encoding="utf-8")
            (source_root / "config").mkdir()
            with mock.patch.object(module, "validate_inputs", return_value={}):
                summary = module.build(
                    source_root, output, Path("/unused/lock"), Path("/unused/provenance")
                )
            self.assertEqual(summary["pnpm_forest_links_copied"], 1)
            self.assertEqual(summary["pnpm_forest_links_skipped"], 3)

            loader_path = loader_instance.relative_to(source_root)
            script = (
                "import { pathToFileURL } from 'node:url';"
                "const loader = await import(pathToFileURL(process.argv[1]).href);"
                "const plugin = await loader.importHeadlessPlugin();"
                "if (plugin.marker !== 'dsh-llm') process.exit(3);"
            )

            def run_import(tree: Path) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [
                        "node",
                        "--input-type=module",
                        "-e",
                        script,
                        str(tree / loader_path / "lib/index.mjs"),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5,
                )

            source_root_link = source_root / "node_modules/@deepseek-ai/dsh-llm"
            output_root_link = output / "node_modules/@deepseek-ai/dsh-llm"
            source_root_link.unlink()
            output_root_link.unlink()
            self.assertEqual(run_import(source_root).returncode, 0)

            forest_link = output / "node_modules/.pnpm/node_modules/@deepseek-ai/dsh-llm"
            self.assertTrue(forest_link.is_symlink())
            self.assertTrue(forest_link.readlink().is_absolute() is False)
            self.assertTrue(forest_link.exists())
            self.assertEqual(module.instance_root(forest_link.resolve(), output / "node_modules/.pnpm").name, dsh_instance_name)
            for name in ("phantom", "broken", "absolute"):
                self.assertFalse((forest_link.parent / name).exists())
            self.assertFalse(
                (
                    output
                    / "node_modules/.pnpm/@deepseek-ai+phantom@fixture"
                ).exists()
            )
            self.assertEqual(run_import(output).returncode, 0)
            forest_link.unlink()
            self.assertNotEqual(run_import(output).returncode, 0)

    def test_cordis_loader_materializes_matching_root_package_for_partial_instance(self) -> None:
        source = ROOT / "scripts/package_dsh.py"
        spec = importlib.util.spec_from_file_location("package_dsh", source)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            source_root = Path(temporary) / "source"
            output = Path(temporary) / "output"
            packages = {
                "loader": (
                    "@deepseek-ai+cordis-plugin-loader@fixture",
                    "@deepseek-ai/cordis-plugin-loader",
                ),
                "llm": (
                    "@deepseek-ai+dsh-llm@fixture",
                    "@deepseek-ai/dsh-llm",
                ),
                "registry": (
                    "@deepseek-ai+dsh-typert-registry@fixture",
                    "@deepseek-ai/dsh-typert-registry",
                ),
                "gateway": (
                    "@deepseek-ai+dsh-api-gateway@fixture",
                    "@deepseek-ai/dsh-api-gateway",
                ),
            }

            def package_dir(instance_name: str, package_name: str) -> Path:
                return (
                    source_root
                    / "node_modules/.pnpm"
                    / instance_name
                    / "node_modules"
                    / Path(*package_name.split("/"))
                )

            package_manifests = {}
            for key, (instance_name, package_name) in packages.items():
                directory = package_dir(instance_name, package_name)
                directory.joinpath("lib").mkdir(parents=True)
                if key in ("registry", "gateway"):
                    package_manifests[key] = {
                        "name": package_name,
                        "version": "fixture",
                        "main": "lib/index.js",
                        "exports": {".": {"default": "./lib/index.js"}},
                    }
                    (directory / "lib/types").mkdir()
                    (directory / "lib/types/index.js").write_text(
                        f'module.exports = "partial-{key}";\n', encoding="utf-8"
                    )
                else:
                    package_manifests[key] = {
                        "name": package_name,
                        "version": "fixture",
                        "type": "module",
                        "exports": "./lib/index.mjs",
                    }
                    (directory / "lib/index.mjs").write_text(
                        f'export const marker = "{key}";\n', encoding="utf-8"
                    )
                (directory / "package.json").write_text(
                    json.dumps(package_manifests[key]), encoding="utf-8"
                )

            loader_dir = package_dir(*packages["loader"])
            package_manifests["loader"]["dependencies"] = {
                "@deepseek-ai/dsh-typert-registry": "workspace:^",
                "@deepseek-ai/dsh-api-gateway": "workspace:^",
            }
            (loader_dir / "package.json").write_text(
                json.dumps(package_manifests["loader"]), encoding="utf-8"
            )
            (loader_dir / "lib/index.mjs").write_text(
                "export async function boot() {\n"
                '  const registry = await import("@deepseek-ai/dsh-typert-registry");\n'
                '  const gateway = await import("@deepseek-ai/dsh-api-gateway");\n'
                '  const llm = await import("@deepseek-ai/dsh-llm");\n'
                "  return [registry.marker, gateway.marker, llm.marker].join(\":\");\n"
                "}\n",
                encoding="utf-8",
            )

            for key in ("registry", "gateway"):
                instance_name, package_name = packages[key]
                partial = package_dir(instance_name, package_name)
                physical = source_root / "node_modules" / Path(*package_name.split("/"))
                physical.joinpath("lib").mkdir(parents=True)
                (physical / "package.json").write_text(
                    json.dumps(package_manifests[key]), encoding="utf-8"
                )
                (physical / "lib/index.js").write_text(
                    f'exports.marker = "complete-{key}";\n', encoding="utf-8"
                )
                nested = loader_dir / "node_modules" / Path(*package_name.split("/"))
                nested.parent.mkdir(parents=True, exist_ok=True)
                nested.symlink_to(
                    Path(os.path.relpath(partial, nested.parent)), target_is_directory=True
                )

            root_scope = source_root / "node_modules/@deepseek-ai"
            root_scope.mkdir(parents=True, exist_ok=True)
            for key in ("loader", "llm"):
                instance_name, package_name = packages[key]
                (root_scope / package_name.rsplit("/", 1)[1]).symlink_to(
                    f"../.pnpm/{instance_name}/node_modules/{package_name}",
                    target_is_directory=True,
                )
            forest_scope = source_root / "node_modules/.pnpm/node_modules/@deepseek-ai"
            forest_scope.mkdir(parents=True)
            for instance_name, package_name in packages.values():
                (forest_scope / package_name.rsplit("/", 1)[1]).symlink_to(
                    f"../../{instance_name}/node_modules/{package_name}",
                    target_is_directory=True,
                )
            (source_root / "package.json").write_text(
                json.dumps(
                    {
                        "name": "@deepseek-ai/dsh",
                        "devDependencies": {
                            "@deepseek-ai/cordis-plugin-loader": "workspace:^",
                            "@deepseek-ai/dsh-llm": "workspace:^",
                        },
                    }
                ),
                encoding="utf-8",
            )
            (source_root / "lib").mkdir()
            (source_root / "lib/bin.js").write_text("export {};\n", encoding="utf-8")
            (source_root / "config").mkdir()
            with mock.patch.object(module, "validate_inputs", return_value={}):
                module.build(
                    source_root, output, Path("/unused/lock"), Path("/unused/provenance")
                )

            for key in ("registry", "gateway"):
                _, package_name = packages[key]
                materialized = output / "node_modules/.pnpm" / packages[key][0] / "node_modules" / Path(*package_name.split("/"))
                self.assertTrue((materialized / "lib/index.js").is_file())

            loader_path = loader_dir.relative_to(source_root)
            script = (
                "import { pathToFileURL } from 'node:url';"
                "const loader = await import(pathToFileURL(process.argv[1]).href);"
                "const result = await loader.boot();"
                "if (result !== 'complete-registry:complete-gateway:llm') process.exit(3);"
            )
            (output / "node_modules/@deepseek-ai/dsh-llm").unlink()
            completed = subprocess.run(
                [
                    "node",
                    "--input-type=module",
                    "-e",
                    script,
                    str(output / loader_path / "lib/index.mjs"),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

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

    def test_preflight_uses_root_manifest_after_non_pnpm_package_collection(self) -> None:
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
            local_package = source_root / "node_modules/local-tool"
            local_package.mkdir(parents=True)
            (local_package / "package.json").write_text(
                json.dumps({"name": "local-tool", "version": "fixture", "main": "index.js"}),
                encoding="utf-8",
            )
            (local_package / "index.js").write_text("module.exports = {};\n", encoding="utf-8")
            (source_root / "package.json").write_text(
                json.dumps(
                    {
                        "name": "@deepseek-ai/dsh",
                        "dependencies": {"local-tool": "file:local-tool"},
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
            self.assertEqual(summary["skipped_unresolved"], [])
            self.assertTrue((output / "node_modules/@deepseek-ai/dsh-llm").is_symlink())
            self.assertTrue((output / "node_modules/local-tool/index.js").is_file())

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
        # +30 is reserved only for Filesync-restored artifact-directory fail-closed checks.
        self.assertLessEqual(nonblank, 500)


if __name__ == "__main__":
    unittest.main()
