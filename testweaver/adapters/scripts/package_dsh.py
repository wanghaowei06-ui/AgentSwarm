#!/usr/bin/env python3
"""Make a small deterministic DSH runtime tree from the fixed materialization."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any


EXPECTED_COMMIT = "47f943859bef60e4160492346772ded9b24f765a"
EXPECTED_TREE = "f904efab9ef435201d6ba4da88a34d6366568272"
EXPECTED_VERSION = "0.1.0-rc.5"
EXPECTED_PACKAGE_SHA256 = "a83af30293a1af777416ad890576840fecbeed33a56218993910239e39f19786"
EXPECTED_ENTRYPOINT_SHA256 = "c0226687bb20f45c603ec6fe50f3de16d1c3510c3a803304ec575ef9bc366c62"
EXPECTED_CANONICAL_LOCK_SHA256 = "6177ec61bdb8194eb5a606813a62ffb0ab2cc7fdfe2cd6e0249dcbfe4bce58e0"
EXPECTED_MATERIALIZED_LOCK_SHA256 = "b6f01683dca822848360087255d7847b4961afd2ad6e08cf6ed36a4d38daa377"
EXPECTED_CACHE_SHA256 = "bf23d5e48eadc9468442f035afd90f1624b9c0ad6784a1809150512f7376c761"
HEADLESS_PLUGIN_PACKAGE = "@deepseek-ai/dsh-llm"


class PackageError(ValueError):
    """Raised when the fixed materialization cannot produce a safe package."""


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageError(f"invalid package manifest: {path}") from exc
    if not isinstance(value, dict):
        raise PackageError(f"package manifest is not an object: {path}")
    return value


def validate_inputs(source: Path, canonical_lock: Path, provenance: Path) -> dict[str, Any]:
    package_json = source / "package.json"
    entrypoint = source / "lib" / "bin.js"
    materialized_lock = source / "node_modules" / ".pnpm" / "lock.yaml"
    if not package_json.is_file() or package_json.is_symlink():
        raise PackageError("materialized DSH package.json is missing or symlinked")
    if not entrypoint.is_file() or entrypoint.is_symlink():
        raise PackageError("materialized DSH lib/bin.js is missing or symlinked")
    if not materialized_lock.is_file() or materialized_lock.is_symlink():
        raise PackageError("materialized pnpm lockfile is missing or symlinked")
    if not canonical_lock.is_file() or canonical_lock.is_symlink():
        raise PackageError("canonical upstream pnpm lockfile is missing or symlinked")
    if not provenance.is_file() or provenance.is_symlink():
        raise PackageError("upstream provenance receipt is missing or symlinked")

    package = manifest(package_json)
    if (
        package.get("name") != "@deepseek-ai/dsh"
        or package.get("version") != EXPECTED_VERSION
        or package.get("bin") != {"dsh": "lib/bin.js"}
    ):
        raise PackageError("materialized DSH package identity or bin contract changed")
    if digest(package_json) != EXPECTED_PACKAGE_SHA256:
        raise PackageError("materialized DSH package.json hash changed")
    if digest(entrypoint) != EXPECTED_ENTRYPOINT_SHA256:
        raise PackageError("materialized DSH entrypoint hash changed")
    if digest(canonical_lock) != EXPECTED_CANONICAL_LOCK_SHA256:
        raise PackageError("canonical upstream lockfile hash changed")
    if digest(materialized_lock) != EXPECTED_MATERIALIZED_LOCK_SHA256:
        raise PackageError("materialized pnpm lockfile hash changed")

    receipt = manifest(provenance)
    upstream = receipt.get("upstream") if isinstance(receipt.get("upstream"), dict) else {}
    lock = receipt.get("lockfile") if isinstance(receipt.get("lockfile"), dict) else {}
    commit = receipt.get("upstream_commit", upstream.get("commit"))
    version = receipt.get("package_version", upstream.get("version"))
    lock_hash = receipt.get("lockfile_hash", lock.get("sha256"))
    cache_hash = receipt.get("official_cache_hash", receipt.get("materialized_cache_sha256"))
    if (
        commit != EXPECTED_COMMIT
        or version != EXPECTED_VERSION
        or lock_hash != f"sha256:{EXPECTED_CANONICAL_LOCK_SHA256}"
        or cache_hash not in (EXPECTED_CACHE_SHA256, f"sha256:{EXPECTED_CACHE_SHA256}")
    ):
        raise PackageError("upstream provenance does not match the fixed DSH source")
    return package


def find_dependency(root: Path, anchor: Path, name: str) -> Path | None:
    current = anchor
    while True:
        candidate = current / "node_modules" / name / "package.json"
        if candidate.is_file():
            return candidate
        if current == root or current.parent == current:
            break
        current = current.parent
    candidate = root / "node_modules" / name / "package.json"
    return candidate if candidate.is_file() else None


def instance_root(path: Path, pnpm_root: Path) -> Path | None:
    current = path
    while current != current.parent:
        if current.parent == pnpm_root:
            return current
        current = current.parent
    return None


def _node_resolvable(root: Path, names: list[str]) -> set[str]:
    if not names:
        return set()
    node = shutil.which("node")
    if node is None:
        raise PackageError("node is required for dependency resolution preflight")
    script = (
        "const root = process.argv[1];"
        "const names = JSON.parse(process.argv[2]);"
        "const resolved = [];"
        "for (const name of names) {"
        "  try { require.resolve(name, {paths: [root]}); resolved.push(name); }"
        "  catch (_) {}"
        "}"
        "process.stdout.write(JSON.stringify(resolved));"
    )
    try:
        completed = subprocess.run(
            [node, "-e", script, str(root), json.dumps(names)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PackageError("dependency resolution preflight failed") from exc
    if completed.returncode != 0:
        raise PackageError("dependency resolution preflight failed")
    try:
        resolved = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PackageError("dependency resolution preflight failed") from exc
    if not isinstance(resolved, list) or not all(isinstance(name, str) for name in resolved):
        raise PackageError("dependency resolution preflight failed")
    return set(resolved)


def root_runtime_resolution(source: Path, package: dict[str, Any]) -> tuple[set[str], list[str]]:
    names: set[str] = set()
    for field in ("dependencies", "optionalDependencies", "devDependencies"):
        values = package.get(field) or {}
        if isinstance(values, dict):
            names.update(values)
    if HEADLESS_PLUGIN_PACKAGE not in names:
        raise PackageError("headless plugin dependency is not declared")
    resolved = _node_resolvable(source.resolve(), sorted(names))
    if HEADLESS_PLUGIN_PACKAGE not in resolved:
        raise PackageError("headless plugin dependency is not resolvable")
    return resolved, sorted(names - resolved)


def collect(
    source: Path,
    skip_root_names: set[str] | None = None,
) -> tuple[dict[tuple[str, str], tuple[Path, dict[str, Any]]], list[tuple[str, str, str]]]:
    root = source.resolve()
    skip_root_names = skip_root_names or set()
    queue = [(source / "package.json", "<root>")]
    seen: dict[tuple[str, str], tuple[Path, dict[str, Any]]] = {}
    missing: list[tuple[str, str, str]] = []
    while queue:
        package_json, _parent = queue.pop()
        package_dir = Path(os.path.realpath(package_json.parent))
        package = manifest(package_json)
        key = (str(package_dir), str(package.get("name")))
        if key in seen:
            continue
        seen[key] = (package_dir, package)
        dependencies: dict[str, Any] = {}
        for field in ("dependencies", "optionalDependencies", "peerDependencies", "devDependencies"):
            values = package.get(field) or {}
            if isinstance(values, dict):
                dependencies.update({name: (field, spec) for name, spec in values.items()})
        for name, (field, _spec) in dependencies.items():
            if package_dir == root and name in skip_root_names:
                continue
            dependency = find_dependency(root, package_dir, name)
            if dependency is None:
                missing.append((str(package.get("name")), field, name))
            else:
                queue.append((dependency, str(package.get("name"))))
    required = [item for item in missing if item[1] == "dependencies"]
    if required:
        raise PackageError(f"required dependency is absent: {required[0][2]}")
    return seen, missing


def preflight_plugin_tree(output: Path, package: dict[str, Any] | None = None) -> None:
    """Verify the packaged root can resolve the headless plugin entrypoint."""

    root = output.resolve()
    package = package or manifest(root / "package.json")
    declared = set()
    for field in ("dependencies", "devDependencies"):
        values = package.get(field) or {}
        if isinstance(values, dict):
            declared.update(values)
    if HEADLESS_PLUGIN_PACKAGE not in declared:
        raise PackageError("headless plugin dependency is not declared")
    if HEADLESS_PLUGIN_PACKAGE not in _node_resolvable(root, [HEADLESS_PLUGIN_PACKAGE]):
        raise PackageError("packaged plugin-tree preflight failed")


def _root_export_targets(exports: Any) -> list[str]:
    if isinstance(exports, str):
        return [exports]
    if isinstance(exports, list):
        targets: list[str] = []
        for value in exports:
            targets.extend(_root_export_targets(value))
        return targets
    if not isinstance(exports, dict):
        return []
    if "." in exports:
        return _root_export_targets(exports["."])
    if any(isinstance(key, str) and key.startswith(".") for key in exports):
        return []
    targets = []
    for value in exports.values():
        targets.extend(_root_export_targets(value))
    return targets


def _declared_entrypoints(package: dict[str, Any]) -> list[str]:
    targets: list[str] = []
    main = package.get("main")
    if isinstance(main, str):
        targets.append(main)
    targets.extend(_root_export_targets(package.get("exports")))
    return targets


def _entrypoints_exist(package_dir: Path, package: dict[str, Any]) -> bool:
    targets = _declared_entrypoints(package)
    if not targets:
        return True
    package_root = package_dir.resolve()
    for target in targets:
        if not target or "\x00" in target or os.path.isabs(target):
            return False
        entrypoint = (package_dir / target).resolve()
        try:
            entrypoint.relative_to(package_root)
        except ValueError:
            return False
        if not entrypoint.is_file():
            return False
    return True


def _root_physical_package(source: Path, package: dict[str, Any]) -> Path | None:
    name = package.get("name")
    if not isinstance(name, str) or "\\" in name:
        return None
    parts = name.split("/")
    if len(parts) not in (1, 2) or any(not part or part in (".", "..") for part in parts):
        return None
    node_modules = (source / "node_modules").resolve()
    candidate = source / "node_modules" / Path(*parts)
    if candidate.is_symlink() or not candidate.is_dir():
        return None
    try:
        candidate.resolve().relative_to(node_modules)
    except ValueError:
        return None
    package_json = candidate / "package.json"
    if not package_json.is_file() or package_json.is_symlink():
        return None
    return candidate


def _materialization_source(
    source: Path,
    package_dir: Path,
    package: dict[str, Any],
) -> Path:
    if _entrypoints_exist(package_dir, package):
        return package_dir
    pnpm_root = (source / "node_modules" / ".pnpm").resolve()
    try:
        package_dir.resolve().relative_to(pnpm_root)
    except ValueError:
        return package_dir
    candidate = _root_physical_package(source, package)
    if candidate is None:
        return package_dir
    try:
        if manifest(candidate / "package.json") != package:
            return package_dir
    except PackageError:
        return package_dir
    return candidate if _entrypoints_exist(candidate, package) else package_dir


def remove_broken_symlinks(root: Path) -> None:
    root = root.resolve()
    for directory, names, files in os.walk(root, followlinks=False):
        for name in (*names, *files):
            path = Path(directory) / name
            if not path.is_symlink():
                continue
            target = os.readlink(path)
            resolved = Path(target) if os.path.isabs(target) else path.parent / target
            resolved = Path(os.path.realpath(resolved))
            try:
                resolved.relative_to(root)
            except ValueError:
                path.unlink()
                continue
            if not resolved.exists():
                path.unlink()
    broken = []
    for path in root.rglob("*"):
        if not path.is_symlink():
            continue
        target = os.readlink(path)
        resolved = Path(target) if os.path.isabs(target) else path.parent / target
        resolved = Path(os.path.realpath(resolved))
        if not resolved.exists() or not resolved.is_relative_to(root):
            broken.append(path)
    if broken:
        raise PackageError(f"runtime contains unresolved symlink: {broken[0].relative_to(root)}")


def copy_pnpm_module_forest(
    source: Path,
    output: Path,
    instances: dict[str, Path],
) -> tuple[int, int]:
    """Copy only safe links from pnpm's shared module forest."""

    source_pnpm = source / "node_modules" / ".pnpm"
    source_forest = source_pnpm / "node_modules"
    if not source_forest.is_dir() or source_forest.is_symlink():
        return 0, 0

    source_pnpm = source_pnpm.resolve()
    output_root = output.resolve()
    target_forest = output / "node_modules" / ".pnpm" / "node_modules"
    copied = 0
    skipped = 0
    for directory, names, files in os.walk(source_forest, followlinks=False):
        for name in sorted((*names, *files)):
            link = Path(directory) / name
            if not link.is_symlink():
                continue
            target = os.readlink(link)
            if os.path.isabs(target):
                skipped += 1
                continue

            source_target = Path(os.path.realpath(link))
            if not source_target.exists():
                skipped += 1
                continue
            try:
                source_target.relative_to(source_pnpm)
            except ValueError:
                skipped += 1
                continue
            instance = instance_root(source_target, source_pnpm)
            if instance is None or instance.name not in instances:
                skipped += 1
                continue
            if Path(os.path.realpath(instances[instance.name])) != Path(os.path.realpath(instance)):
                skipped += 1
                continue

            relative = link.relative_to(source_forest)
            destination = target_forest / relative
            output_target = Path(os.path.realpath(destination.parent / target))
            try:
                output_target.relative_to(output_root)
            except ValueError:
                skipped += 1
                continue
            if not output_target.exists():
                skipped += 1
                continue
            if destination.exists() or destination.is_symlink():
                if destination.is_symlink() and os.readlink(destination) == target:
                    continue
                raise PackageError(f"pnpm module forest collision: {relative}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(target, destination)
            copied += 1
    return copied, skipped


def build(source: Path, output: Path, canonical_lock: Path, provenance: Path) -> dict[str, Any]:
    validate_inputs(source, canonical_lock, provenance)
    root_manifest = manifest(source / "package.json")
    _resolved, skipped_unresolved = root_runtime_resolution(source, root_manifest)
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise PackageError("output directory must be absent or empty")
    else:
        output.mkdir(parents=True)

    seen, missing = collect(source, set(skipped_unresolved))
    pnpm_root = source / "node_modules" / ".pnpm"
    instances: dict[str, Path] = {}
    instance_package_dirs: dict[str, Path] = {}
    instance_manifests: dict[str, dict[str, Any]] = {}
    root_packages: dict[str, Path] = {}
    for (directory, _name), (_path, dependency_manifest) in seen.items():
        package_dir = Path(directory)
        if package_dir == source.resolve():
            continue
        instance = instance_root(package_dir, pnpm_root)
        if instance is not None:
            instances[instance.name] = instance
            instance_package_dirs[instance.name] = package_dir
            instance_manifests[instance.name] = dependency_manifest
        else:
            root_packages[str(dependency_manifest["name"])] = package_dir

    shutil.copy2(source / "package.json", output / "package.json")
    for name in ("lib", "config"):
        shutil.copytree(source / name, output / name, symlinks=True)

    target_node_modules = output / "node_modules"
    target_pnpm = target_node_modules / ".pnpm"
    target_pnpm.mkdir(parents=True)
    root_physical_fallbacks = 0
    for name, instance_root_dir in sorted(instances.items()):
        destination = target_pnpm / name
        shutil.copytree(instance_root_dir, destination, symlinks=True)
        package_dir = instance_package_dirs[name]
        package_manifest = instance_manifests[name]
        materialization = _materialization_source(source, package_dir, package_manifest)
        if materialization != package_dir:
            root_physical_fallbacks += 1
            relative_package = package_dir.relative_to(instance_root_dir)
            materialized_destination = destination / relative_package
            if materialized_destination.is_symlink():
                materialized_destination.unlink()
            elif materialized_destination.exists():
                shutil.rmtree(materialized_destination)
            shutil.copytree(materialization, materialized_destination, symlinks=True)
    for name, package_dir in sorted(root_packages.items()):
        destination = target_node_modules / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(package_dir, destination, symlinks=True)

    direct: dict[str, Any] = {}
    for field in ("dependencies", "optionalDependencies", "devDependencies"):
        values = root_manifest.get(field) or {}
        if isinstance(values, dict):
            direct.update(values)
    for name in sorted(direct):
        if name in skipped_unresolved:
            continue
        source_link = source / "node_modules" / name
        destination = target_node_modules / name
        if source_link.is_symlink():
            if destination.exists() or destination.is_symlink():
                if destination.is_symlink():
                    destination.unlink()
                else:
                    raise PackageError(f"root dependency collision: {name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(os.readlink(source_link), destination)
        elif not destination.exists():
            raise PackageError(f"root dependency is not materialized: {name}")

    forest_links, forest_skipped = copy_pnpm_module_forest(source, output, instances)
    self_link = target_node_modules / "@deepseek-ai" / "dsh"
    if not self_link.exists() and not self_link.is_symlink():
        self_link.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(os.path.relpath(output, self_link.parent), self_link)
    remove_broken_symlinks(output)
    preflight_plugin_tree(output, root_manifest)
    return {
        "package": "@deepseek-ai/dsh",
        "version": EXPECTED_VERSION,
        "pnpm_instances": len(instances),
        "root_packages": len(root_packages),
        "missing_optional_or_peer": len(missing),
        "skipped_unresolved": skipped_unresolved,
        "published_files": ["package.json", "lib", "config"],
        "node_modules_source_copied": forest_links > 0,
        "pnpm_forest_links_copied": forest_links,
        "pnpm_forest_links_skipped": forest_skipped,
        "root_physical_fallbacks": root_physical_fallbacks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--canonical-lock", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    args = parser.parse_args()
    summary = build(
        args.source.resolve(),
        args.output.resolve(),
        args.canonical_lock.resolve(),
        args.provenance.resolve(),
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
