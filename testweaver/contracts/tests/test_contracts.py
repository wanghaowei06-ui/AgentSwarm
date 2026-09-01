"""Focused contract checks; values are TEST_FIXTURE_ONLY_NOT_LIVE."""

from __future__ import annotations

import copy
import unittest

from testweaver.contracts.validator import ContractError, load_schema, seal, validate


TEST_FIXTURE_ONLY_NOT_LIVE = True


def _common(kind: str) -> dict[str, object]:
    return {
        "schema_version": f"testweaver.{kind}/v1",
        "version": 1,
        "revision": 1,
        "native_refs": {
            "project_id": "native-project-reference",
            "task_id": "native-task-reference",
            "room_id": "!native-room-reference:example.invalid",
            "read_only": True,
        },
        "producer": {
            "identity": "native-agent-reference",
            "role": "team-leader",
        },
        "artifact": {
            "channel": "message",
            "artifact_ref": "native-artifact-reference",
        },
    }


def _evidence_ref() -> dict[str, str]:
    return {
        "id": "evidence-reference",
        "kind": "artifact",
        "artifact_ref": "native-evidence-artifact",
        "content_hash": "sha256:" + "0" * 64,
    }


def _provenance() -> dict[str, object]:
    return {
        "source_refs": ["native-evidence-artifact"],
        "method": "observed artifact with reproducible source reference",
    }


def _documents() -> dict[str, dict[str, object]]:
    context = _common("context")
    context.update(
        {
            "context_id": "context-reference",
            "summary": "bounded context summary",
            "claim_refs": ["claim-reference"],
            "evidence_refs": [_evidence_ref()],
            "provenance_ref": "provenance-reference",
            "unresolved_items": ["one item remains open"],
        }
    )

    claim = _common("claim")
    claim.update(
        {
            "claim_id": "claim-reference",
            "claim": {"statement": "bounded conclusion", "claim_type": "ROOT_CAUSE"},
            "evidence_ref": _evidence_ref(),
            "provenance": _provenance(),
            "confidence": 0.75,
            "unresolved_items": [],
        }
    )

    evidence = _common("evidence")
    evidence.update(
        {
            "evidence_id": "evidence-reference",
            "evidence_type": "observed-artifact",
            "evidence_ref": _evidence_ref(),
            "provenance": _provenance(),
        }
    )

    provenance = _common("provenance")
    provenance.update(
        {
            "provenance_id": "provenance-reference",
            "source_refs": ["native-evidence-artifact"],
            "method": "direct artifact observation",
        }
    )

    handoff = _common("handoff")
    handoff.update(
        {
            "handoff_id": "handoff-reference",
            "claim": {"statement": "bounded conclusion", "claim_type": "ROOT_CAUSE"},
            "evidence_ref": _evidence_ref(),
            "provenance": _provenance(),
            "confidence": 0.75,
            "unresolved_items": ["independent confirmation remains"],
        }
    )

    return {
        kind: seal(document)
        for kind, document in {
            "context": context,
            "claim": claim,
            "evidence": evidence,
            "provenance": provenance,
            "handoff": handoff,
        }.items()
    }


class NativeContractTests(unittest.TestCase):
    def test_checked_in_schemas_are_strict_and_have_required_envelope(self) -> None:
        self.assertTrue(TEST_FIXTURE_ONLY_NOT_LIVE)
        for kind in ("context", "claim", "evidence", "provenance", "handoff"):
            schema = load_schema(kind)
            self.assertEqual(schema["additionalProperties"], False)
            self.assertIn("version", schema["required"])
            self.assertIn("revision", schema["required"])
            self.assertIn("content_hash", schema["required"])
            self.assertIn("native_refs", schema["required"])
            self.assertIn("producer", schema["required"])

    def test_valid_fixtures_cover_the_five_thin_artifacts(self) -> None:
        for kind, document in _documents().items():
            validate(kind, document)
            self.assertTrue(document["native_refs"]["read_only"])

    def test_unknown_field_is_rejected(self) -> None:
        invalid = copy.deepcopy(_documents()["handoff"])
        invalid["dispatch"] = "not part of a data artifact"
        with self.assertRaisesRegex(ContractError, "unknown fields"):
            validate("handoff", invalid)

    def test_hash_mismatch_is_rejected(self) -> None:
        invalid = copy.deepcopy(_documents()["claim"])
        invalid["claim"]["statement"] = "changed after sealing"
        with self.assertRaisesRegex(ContractError, "content_hash mismatch"):
            validate("claim", invalid)

    def test_native_reference_must_be_read_only_and_complete(self) -> None:
        invalid = copy.deepcopy(_documents()["context"])
        invalid["native_refs"]["read_only"] = False
        invalid["content_hash"] = seal(invalid)["content_hash"]
        with self.assertRaisesRegex(ContractError, "read_only"):
            validate("context", invalid)

        missing = copy.deepcopy(_documents()["context"])
        del missing["native_refs"]["room_id"]
        missing["content_hash"] = seal(missing)["content_hash"]
        with self.assertRaisesRegex(ContractError, "native_refs"):
            validate("context", missing)

    def test_confidence_and_evidence_reference_are_bounded(self) -> None:
        invalid_confidence = copy.deepcopy(_documents()["handoff"])
        invalid_confidence["confidence"] = 1.1
        invalid_confidence["content_hash"] = seal(invalid_confidence)["content_hash"]
        with self.assertRaisesRegex(ContractError, "confidence"):
            validate("handoff", invalid_confidence)

        invalid_reference = copy.deepcopy(_documents()["evidence"])
        invalid_reference["evidence_ref"]["content_hash"] = "not-a-digest"
        invalid_reference["content_hash"] = seal(invalid_reference)["content_hash"]
        with self.assertRaisesRegex(ContractError, "sha256"):
            validate("evidence", invalid_reference)


if __name__ == "__main__":
    unittest.main()
