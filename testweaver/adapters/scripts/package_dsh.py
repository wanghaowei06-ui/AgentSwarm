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


def collect(source: Path) -> tuple[dict[tuple[str, str], tuple[Path, dict[str, Any]]], list[tuple[str, str, str]]]:
    root = source.resolve()
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
    """Verify the packaged root can resolve its runtime module tree."""

    root = output.resolve()
    package = package or manifest(root / "package.json")
    names: set[str] = set()
    for field in ("dependencies", "devDependencies"):
        values = package.get(field) or {}
        if isinstance(values, dict):
            names.update(name for name in values if not name.startswith("@types/"))
    if not names:
        return
    node = shutil.which("node")
    if node is None:
        raise PackageError("node is required for the packaged plugin-tree preflight")
    script = (
        "const root = process.argv[1];"
        "const names = JSON.parse(process.argv[2]);"
        "for (const name of names) require.resolve(name, {paths: [root]});"
    )
    try:
        completed = subprocess.run(
            [node, "-e", script, str(root), json.dumps(sorted(names))],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PackageError("packaged plugin-tree preflight failed") from exc
    if completed.returncode != 0:
        raise PackageError("packaged plugin-tree preflight failed")


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


def build(source: Path, output: Path, canonical_lock: Path, provenance: Path) -> dict[str, Any]:
    validate_inputs(source, canonical_lock, provenance)
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise PackageError("output directory must be absent or empty")
    else:
        output.mkdir(parents=True)

    seen, missing = collect(source)
    pnpm_root = source / "node_modules" / ".pnpm"
    instances: dict[str, Path] = {}
    root_packages: dict[str, Path] = {}
    for (directory, _name), (_path, _package) in seen.items():
        package_dir = Path(directory)
        if package_dir == source.resolve():
            continue
        instance = instance_root(package_dir, pnpm_root)
        if instance is not None:
            instances[instance.name] = instance
        else:
            package = manifest(package_dir / "package.json")
            root_packages[str(package["name"])] = package_dir

    shutil.copy2(source / "package.json", output / "package.json")
    for name in ("lib", "config"):
        shutil.copytree(source / name, output / name, symlinks=True)

    target_node_modules = output / "node_modules"
    target_pnpm = target_node_modules / ".pnpm"
    target_pnpm.mkdir(parents=True)
    for name, package_dir in sorted(instances.items()):
        shutil.copytree(package_dir, target_pnpm / name, symlinks=True)
    for name, package_dir in sorted(root_packages.items()):
        destination = target_node_modules / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(package_dir, destination, symlinks=True)

    package = manifest(source / "package.json")
    direct: dict[str, Any] = {}
    for field in ("dependencies", "optionalDependencies", "devDependencies"):
        values = package.get(field) or {}
        if isinstance(values, dict):
            direct.update(values)
    for name in sorted(direct):
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

    self_link = target_node_modules / "@deepseek-ai" / "dsh"
    if not self_link.exists() and not self_link.is_symlink():
        self_link.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(os.path.relpath(output, self_link.parent), self_link)
    remove_broken_symlinks(output)
    preflight_plugin_tree(output, package)
    return {
        "package": "@deepseek-ai/dsh",
        "version": EXPECTED_VERSION,
        "pnpm_instances": len(instances),
        "root_packages": len(root_packages),
        "missing_optional_or_peer": len(missing),
        "published_files": ["package.json", "lib", "config"],
        "node_modules_source_copied": False,
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
