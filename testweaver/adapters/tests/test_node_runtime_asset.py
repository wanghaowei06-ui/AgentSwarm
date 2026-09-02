"""Focused checks for the locked offline Node runtime used by DSH."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "build-qwenpaw-native-extension.sh"
DOCKERFILE = ROOT / "Dockerfile.qwenpaw"
LOCKED_NODE = Path("/root/.hermes/node/bin/node")
LOCKED_SHA256 = "93956de2e59480474a7b46571da1651180b1a050cdf32641ebec4ce6e478e068"


def run_preflight(executable: Path, digest: str) -> subprocess.CompletedProcess[str]:
    command = 'source "$1"; preflight_node_runtime "$2" "$3"'
    return subprocess.run(
        ["bash", "-c", command, "test", str(BUILD_SCRIPT), str(executable), digest],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


class NodeRuntimeAssetTests(unittest.TestCase):
    def test_locked_host_asset_passes_version_hash_and_capabilities(self) -> None:
        self.assertTrue(LOCKED_NODE.is_file(), "locked competition runtime asset is absent")
        self.assertFalse(LOCKED_NODE.is_symlink())
        completed = run_preflight(LOCKED_NODE, LOCKED_SHA256)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_preflight_rejects_wrong_declared_hash(self) -> None:
        completed = run_preflight(LOCKED_NODE, "0" * 64)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("SHA256", completed.stderr)

    def test_preflight_rejects_symlink_even_when_target_is_locked_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            link = Path(temporary) / "node"
            link.symlink_to(LOCKED_NODE)
            completed = run_preflight(link, LOCKED_SHA256)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("non-symlink", completed.stderr)

    def test_build_wiring_is_offline_explicit_and_does_not_replace_system_node(self) -> None:
        script = BUILD_SCRIPT.read_text(encoding="utf-8")
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        self.assertEqual(
            subprocess.run(["bash", "-n", str(BUILD_SCRIPT)], check=False).returncode,
            0,
        )
        for marker in (
            "TESTWEAVER_NODE_EXECUTABLE",
            "TESTWEAVER_NODE_SHA256",
            LOCKED_SHA256,
            'TESTWEAVER_NODE_RUNTIME_VERSION="v22.23.1"',
            "Promise.withResolvers",
            "createZstdDecompress",
            'install -m 0755 -- "${TESTWEAVER_NODE_EXECUTABLE}" "${build_context}/node-runtime"',
        ):
            self.assertIn(marker, script)
        for marker in (
            "COPY node-runtime /opt/agentteams/testweaver-native-worker/bin/node",
            'ENV PATH="/opt/agentteams/testweaver-native-worker/bin:${PATH}"',
            LOCKED_SHA256,
            'test "$(node --version)" = "v22.23.1"',
            "Promise.withResolvers",
            "createZstdDecompress",
        ):
            self.assertIn(marker, dockerfile)
        self.assertNotIn("/root/.hermes", script)
        self.assertNotIn("/root/.hermes", dockerfile)
        self.assertNotIn("curl ", script + dockerfile)
        self.assertNotIn("wget ", script + dockerfile)
        self.assertNotIn("/usr/bin/node", dockerfile)

    def test_dsh_image_smoke_supplies_profile_home_and_checks_projection(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        normalized_dockerfile = " ".join(dockerfile.replace(chr(92) + "\n", " ").split())
        profile_home = "/tmp/testweaver-dsh-home"
        dsh = "/opt/agentteams/testweaver-native-worker/bin/dsh"
        runtime_node_modules = "/opt/agentteams/testweaver-native-worker/dsh-runtime/node_modules"
        for marker in (
            f"install -d -m 0700 {profile_home}",
            f"HOME={profile_home} {dsh} --profile headless --version",
            f"HOME={profile_home} {dsh} --profile headless --help >/dev/null",
            f'test "$(readlink -- {profile_home}/.dsh/profiles/headless/node_modules)" = "{runtime_node_modules}"',
        ):
            self.assertIn(marker, normalized_dockerfile)
        self.assertNotIn(f"&& {dsh} --version", normalized_dockerfile)
        self.assertNotIn(f"&& {dsh} --help >/dev/null", normalized_dockerfile)


if __name__ == "__main__":
    unittest.main()
