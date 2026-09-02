from __future__ import annotations

import hashlib
import unittest

from testweaver.skillops.nacos import (
    NACOS_CONTAINER,
    NacosHttpResponse,
    NacosRegistryError,
    NacosV3Client,
)


class NacosV3ClientTests(unittest.TestCase):
    def test_skill_publish_uses_only_v3_data_plane_and_exact_readback(self) -> None:
        calls: list[tuple[str, str, bytes | None]] = []
        package = b"deterministic skill zip bytes"
        package_hash = "sha256:" + hashlib.sha256(package).hexdigest()

        def transport(
            method: str,
            url: str,
            headers: dict[str, str],
            body: bytes | None,
            timeout: float,
        ) -> NacosHttpResponse:
            del headers, timeout
            calls.append((method, url, body))
            if url.endswith("/v3/admin/ai/skills/upload"):
                return NacosHttpResponse(200, b'{"code":0,"data":true}')
            if url.endswith("/v3/admin/ai/skills/submit"):
                return NacosHttpResponse(200, b'{"code":0,"data":true}')
            if url.endswith("/v3/admin/ai/skills/publish"):
                return NacosHttpResponse(200, b'{"code":0,"data":true}')
            if "/v3/client/ai/skills?" in url:
                return NacosHttpResponse(200, package, {"content-type": "application/zip"})
            if "/v3/admin/ai/skills?" in url:
                return NacosHttpResponse(
                    200,
                    b'{"code":0,"data":{"scope":"private","versions":[{"version":"1.2.3","status":"online"}]}}',
                )
            raise AssertionError(url)

        client = NacosV3Client(transport=transport)
        result = client.publish_skill(
            name="boundary-skill",
            version="1.2.3",
            zip_bytes=package,
            package_hash=package_hash,
        )

        self.assertEqual(NACOS_CONTAINER, "tw-g8-nacos")
        self.assertTrue(result["exact_version_readback"])
        self.assertEqual(result["registry_package_hash"], package_hash)
        self.assertEqual(
            [url.split("/nacos", 1)[1].split("?", 1)[0] for _, url, _ in calls],
            [
                "/v3/admin/ai/skills/upload",
                "/v3/admin/ai/skills/submit",
                "/v3/admin/ai/skills/publish",
                "/v3/client/ai/skills",
                "/v3/admin/ai/skills",
            ],
        )

    def test_config_publish_and_client_readback_are_hashable(self) -> None:
        calls: list[str] = []

        def transport(
            method: str,
            url: str,
            headers: dict[str, str],
            body: bytes | None,
            timeout: float,
        ) -> NacosHttpResponse:
            del method, headers, body, timeout
            calls.append(url)
            if "/v3/admin/cs/config" in url:
                return NacosHttpResponse(200, b'{"code":0,"data":true}')
            return NacosHttpResponse(
                200,
                b'{"code":0,"data":{"success":true,"content":"{\\"version\\":1}","md5":"abc123"}}',
            )

        result = NacosV3Client(transport=transport).publish_config(
            data_id="skill-policy-v1.json",
            content='{"version":1}',
            description="immutable test policy",
        )
        self.assertTrue(result["exact_content_readback"])
        self.assertEqual(result["content_md5"], "abc123")
        self.assertEqual(len(calls), 2)

    def test_credentials_and_package_hashes_fail_closed_without_lifecycle(self) -> None:
        with self.assertRaises(NacosRegistryError):
            NacosV3Client("nacos://user:secret@registry/nacos")
        with self.assertRaises(NacosRegistryError):
            NacosV3Client().publish_skill(
                name="skill",
                version="1.0.0",
                zip_bytes=b"zip",
                package_hash="sha256:" + "0" * 64,
            )


if __name__ == "__main__":
    unittest.main()
