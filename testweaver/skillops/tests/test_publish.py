import unittest
import hashlib

from testweaver.skillops.publish import (
    NativePackageError,
    NativePackageRef,
    build_native_publish_intent,
    verify_native_package_readback,
    verify_nacos_candidate_readback,
)
from testweaver.skillops.nacos import NacosCandidateReadback
from testweaver.skillops.state import ExternalReadback
from testweaver.skillops.state import _external_readback


_HASH = "sha256:" + "a" * 64


def _trusted_nacos(
    *, ref: str, raw: bytes, version: str = "1.2.3", content_hash: str = _HASH
) -> ExternalReadback:
    return _external_readback(
        source="nacos",
        ref=ref,
        raw=raw,
        classification="NATIVE_TRANSPORT",
        claims=(("content_hash", content_hash), ("version", version)),
        verified=True,
    )


class NativePackagePublishTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidate = NativePackageRef(
            package_uri="nacos://registry/ns/testweaver-skill/v1",
            version="1.2.3",
            content_hash=_HASH,
            rollback_ref="nacos://registry/ns/testweaver-skill/v0",
        )

    def test_intent_is_native_ref_only_and_supports_lifecycle_actions(self) -> None:
        intent = build_native_publish_intent(self.candidate, action="CANARY")
        self.assertEqual(intent["package_uri"], self.candidate.package_uri)
        self.assertEqual(
            build_native_publish_intent(self.candidate, action="PROMOTE")["action"],
            "PROMOTE",
        )
        self.assertEqual(
            build_native_publish_intent(self.candidate, action="ROLLBACK")["action"],
            "ROLLBACK",
        )

    def test_readback_must_match_candidate_and_is_hash_sealed(self) -> None:
        token = _trusted_nacos(
            ref="controller://worker/package-readback",
            raw=b"nacos-readback",
        )
        readback = verify_native_package_readback(
            self.candidate,
            action="CANARY",
            readback={
                "package_uri": self.candidate.package_uri,
                "version": self.candidate.version,
                "content_hash": self.candidate.content_hash,
                "readback_ref": "controller://worker/package-readback",
                "ignored_runtime_metadata": "not persisted",
            },
            readback_token=token,
        )
        self.assertTrue(readback["record_hash"].startswith("sha256:"))
        self.assertNotIn("ignored_runtime_metadata", readback)

    def test_invalid_scheme_credentials_and_mismatch_fail_closed(self) -> None:
        with self.assertRaises(NativePackageError):
            NativePackageRef("https://registry/pkg", "1.2.3", _HASH, "rollback")
        with self.assertRaises(NativePackageError):
            NativePackageRef("nacos://user:password@registry/pkg", "1.2.3", _HASH, "rollback")
        with self.assertRaises(NativePackageError):
            verify_native_package_readback(
                self.candidate,
                action="CANARY",
                readback={
                    "package_uri": self.candidate.package_uri,
                    "version": "1.2.4",
                    "content_hash": self.candidate.content_hash,
                    "readback_ref": "controller://readback",
                },
                readback_token=_trusted_nacos(
                    ref="controller://readback", raw=b"readback"
                ),
            )

        with self.assertRaisesRegex(NativePackageError, "verify_close"):
            verify_native_package_readback(
                self.candidate,
                action="PROMOTE",
                readback={
                    "package_uri": self.candidate.package_uri,
                    "version": self.candidate.version,
                    "content_hash": self.candidate.content_hash,
                    "readback_ref": "controller://readback",
                },
                readback_token=_trusted_nacos(
                    ref="controller://readback", raw=b"readback"
                ),
            )

    def test_caller_mapping_without_external_readback_cannot_be_sealed(self) -> None:
        with self.assertRaisesRegex(NativePackageError, "external token"):
            verify_native_package_readback(
                self.candidate,
                action="CANARY",
                readback={
                    "package_uri": self.candidate.package_uri,
                    "version": self.candidate.version,
                    "content_hash": self.candidate.content_hash,
                    "readback_ref": "controller://readback",
                },
            )

    def test_attested_nacos_candidate_reconciles_endpoint_namespace_and_tuple(self) -> None:
        endpoint = "https://nacos.example.invalid/nacos"
        package = b"package"
        package_hash = "sha256:" + hashlib.sha256(package).hexdigest()
        candidate = NativePackageRef(
            package_uri="nacos://registry/ns/testweaver-skill/v1",
            version="1.2.3",
            content_hash=package_hash,
            rollback_ref="nacos://registry/ns/testweaver-skill/v0",
        )
        claims = {
            "endpoint": endpoint,
            "namespace_id": "ns",
            "skill_name": "testweaver-skill",
            "version": candidate.version,
            "content_hash": candidate.content_hash,
            "admin_response_hash": _HASH,
            "registry_status": "online",
        }
        token = _external_readback(
            source="nacos",
            ref="nacos:readback:one",
            raw=package,
            classification="NATIVE_TRANSPORT",
            claims=tuple(sorted(claims.items())),
            verified=True,
        )
        readback = NacosCandidateReadback(
            endpoint=endpoint,
            namespace_id="ns",
            skill_name="testweaver-skill",
            version=candidate.version,
            registry_package_hash=candidate.content_hash,
            registry_status="online",
            admin_response_hash=_HASH,
            readback_ref=token.ref,
            token=token,
        )
        result = verify_nacos_candidate_readback(
            candidate,
            skill_name="testweaver-skill",
            readback=readback,
            expected_endpoint=endpoint,
            expected_namespace="ns",
        )
        self.assertEqual(result["classification"], "LIVE_ATTESTED")
        with self.assertRaisesRegex(NativePackageError, "namespace"):
            verify_nacos_candidate_readback(
                candidate,
                skill_name="testweaver-skill",
                readback=readback,
                expected_endpoint=endpoint,
                expected_namespace="other",
            )

    def test_no_native_publisher_or_runtime_is_implemented(self) -> None:
        intent = build_native_publish_intent(self.candidate, action="ROLLBACK")
        self.assertEqual(set(intent), {
            "schema_version",
            "action",
            "package_uri",
            "version",
            "content_hash",
            "rollback_ref",
        })


if __name__ == "__main__":
    unittest.main()
