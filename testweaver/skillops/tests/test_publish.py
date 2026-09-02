import unittest

from testweaver.skillops.publish import (
    NativePackageError,
    NativePackageRef,
    build_native_publish_intent,
    verify_native_package_readback,
)
from testweaver.skillops.state import ExternalReadback


_HASH = "sha256:" + "a" * 64


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
        token = ExternalReadback.from_raw(
            source="nacos",
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
                readback_token=ExternalReadback.from_raw(
                    source="nacos", ref="controller://readback", raw=b"readback"
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
