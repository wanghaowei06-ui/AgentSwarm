#!/usr/bin/env python3
"""Offline, receipt-only operator for one post-Hero Skill evolution.

Every command consumes one exact, hash-sealed JSON request and emits one
hash-sealed receipt.  It never sends Matrix traffic, calls Nacos/AgentLoop, or
creates AgentTeams resources.  External systems execute the emitted intents;
their exact raw readbacks are required by the following stage.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import stat
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from testweaver.authority import (  # noqa: E402
    AuthorityError,
    OracleResult,
    digest_bytes,
    validate_hash,
    validate_oracle_pair,
    validate_ref,
)
from testweaver.contracts.validator import canonical_hash  # noqa: E402
from testweaver.integrations.agentloop_client import (  # noqa: E402
    AgentLoopClient,
    AgentLoopCredentialLease,
    AgentLoopEndpoint,
    AgentLoopHTTPResponse,
    AgentLoopScope,
)
from testweaver.integrations.matrix_readback import (  # noqa: E402
    MatrixAuthenticatedEvent,
    MatrixDecisionExpectation,
    MatrixHumanReadbackVerifier,
)
from testweaver.skillops import (  # noqa: E402
    ArtifactRef,
    Attribution,
    Baseline,
    CanaryObservation,
    ExternalReadback,
    HumanDecision,
    HumanDecisionVerification,
    NativePackageRef,
    NacosHttpResponse,
    NacosV3Client,
    ReevaluationObservation,
    SkillEvolution,
    SkillProposal,
    SkillReceipt,
    build_native_publish_intent,
    verify_native_package_readback,
)


REQUEST_SCHEMA = "testweaver.skill-evolve-request/v1"
RECEIPT_SCHEMA = "testweaver.skill-evolve-receipt/v1"
_MAX_INPUT_BYTES = 64 * 1024 * 1024
_MAX_RAW_BYTES = 4 * 1024 * 1024
_MAX_RECEIPT_BYTES = 64 * 1024 * 1024
_TRACE = re.compile(r"^[0-9a-f]{32}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_AUTHORITY_FIELDS = (
    "campaign_id",
    "run_id",
    "trace_id",
    "pg_revision",
    "content_hash",
)
_STAGES = (
    "prepare",
    "verify-approval",
    "publish-candidate",
    "record-canary",
    "reevaluate",
    "close",
)
_PREVIOUS_STAGE = dict(zip(_STAGES[1:], _STAGES[:-1], strict=True))
_RECORD_KEYS = (
    "baseline",
    "attribution",
    "proposal",
    "human_decision",
    "human_verification",
    "canary",
    "reevaluation",
    "receipt",
)
_SOURCE_FOR_KIND = {
    "frozen-dataset": "evaluation",
    "evaluation-export": "evaluation",
    "agentteams-native": "agentteams",
    "otel-genai": "otel",
    "agentloop-sls": "agentloop",
}


class EvolutionInputError(ValueError):
    """A sealed stage request or exact external readback is unsafe."""


@dataclass(frozen=True, slots=True)
class RawReadback:
    source: str
    ref: str
    raw: bytes
    raw_hash: str

    def as_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "ref": self.ref,
            "raw_base64": base64.b64encode(self.raw).decode("ascii"),
            "raw_hash": self.raw_hash,
        }


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvolutionInputError(f"{field} must be an object")
    return value


def _exact(value: Mapping[str, Any], fields: set[str], label: str) -> None:
    if set(value) != fields:
        raise EvolutionInputError(f"{label} fields are not exact")


def _ref(value: object, field: str) -> str:
    try:
        return validate_ref(value, field)  # type: ignore[arg-type]
    except AuthorityError as error:
        raise EvolutionInputError(str(error)) from error


def _hash(value: object, field: str) -> str:
    try:
        return validate_hash(value, field)  # type: ignore[arg-type]
    except AuthorityError as error:
        raise EvolutionInputError(str(error)) from error


def _version(value: object, field: str) -> str:
    if not isinstance(value, str) or _VERSION.fullmatch(value) is None:
        raise EvolutionInputError(f"{field} must be a semantic version")
    return value


def _authority(value: object) -> dict[str, Any]:
    result = _object(value, "authority")
    _exact(result, set(_AUTHORITY_FIELDS), "authority")
    _ref(result["campaign_id"], "campaign_id")
    _ref(result["run_id"], "run_id")
    trace = result["trace_id"]
    if not isinstance(trace, str) or _TRACE.fullmatch(trace) is None:
        raise EvolutionInputError("trace_id must be 32 lowercase hexadecimal characters")
    revision = result["pg_revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise EvolutionInputError("pg_revision must be a positive integer")
    _hash(result["content_hash"], "content_hash")
    return dict(result)


def _decode_readback(value: object, *, expected_source: str | None = None) -> RawReadback:
    item = _object(value, "readback")
    _exact(item, {"source", "ref", "raw_base64", "raw_hash"}, "readback")
    source = _ref(item["source"], "readback.source")
    ref = _ref(item["ref"], "readback.ref")
    if expected_source is not None and source != expected_source:
        raise EvolutionInputError("readback source does not match the exact-read boundary")
    encoded = item["raw_base64"]
    if not isinstance(encoded, str):
        raise EvolutionInputError("readback raw_base64 must be text")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, UnicodeEncodeError) as error:
        raise EvolutionInputError("readback raw_base64 is invalid") from error
    if not raw or len(raw) > _MAX_RAW_BYTES:
        raise EvolutionInputError("readback exact raw bytes are empty or too large")
    if base64.b64encode(raw).decode("ascii") != encoded:
        raise EvolutionInputError("readback raw_base64 is not canonical")
    raw_hash = _hash(item["raw_hash"], "readback.raw_hash")
    if digest_bytes(raw) != raw_hash:
        raise EvolutionInputError("readback hash does not match exact raw bytes")
    return RawReadback(source, ref, raw, raw_hash)


def _readback_list(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise EvolutionInputError("receipt readbacks must be a list")
    result: list[dict[str, str]] = []
    seen: dict[tuple[str, str], str] = {}
    for child in value:
        readback = _decode_readback(child)
        key = (readback.source, readback.ref)
        if key in seen and seen[key] != readback.raw_hash:
            raise EvolutionInputError("receipt contains conflicting exact readbacks")
        if key not in seen:
            seen[key] = readback.raw_hash
            result.append(readback.as_dict())
    return result


def _add_readback(target: list[dict[str, str]], readback: RawReadback) -> None:
    for item in target:
        if (item["source"], item["ref"]) == (readback.source, readback.ref):
            if item["raw_hash"] != readback.raw_hash or item["raw_base64"] != readback.as_dict()["raw_base64"]:
                raise EvolutionInputError("exact readback conflicts with prior receipt")
            return
    target.append(readback.as_dict())


def _find_readback(
    readbacks: list[dict[str, str]], *, source: str, raw_hash: str | None = None, ref: str | None = None
) -> RawReadback:
    matches = []
    for item in readbacks:
        decoded = _decode_readback(item)
        if decoded.source != source:
            continue
        if raw_hash is not None and decoded.raw_hash != raw_hash:
            continue
        if ref is not None and decoded.ref != ref:
            continue
        matches.append(decoded)
    if len(matches) != 1:
        raise EvolutionInputError("required exact readback is missing or ambiguous")
    return matches[0]


def _sealed_json(raw: bytes, field: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvolutionInputError(f"{field} exact raw result is not JSON") from error
    result = _object(value, field)
    record_hash = _hash(result.get("record_hash"), f"{field}.record_hash")
    if record_hash != canonical_hash({key: child for key, child in result.items() if key != "record_hash"}):
        raise EvolutionInputError(f"{field} exact raw result is not sealed")
    return result


def _check_raw_authority(raw: bytes, expected: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = _sealed_json(raw, field)
    scope = result.get("authority_scope")
    nested = scope if isinstance(scope, Mapping) else {}
    for name in _AUTHORITY_FIELDS:
        actual = result.get(name, nested.get(name))
        if actual != expected[name]:
            raise EvolutionInputError(f"{field} crosses the sealed authority {name}")
    return result


def _verify_receipt(value: object) -> dict[str, Any]:
    receipt = _object(value, "previous_receipt")
    fields = {
        "schema_version",
        "stage",
        "authority",
        "status",
        "records",
        "readbacks",
        "intents",
        "observations",
        "record_hash",
    }
    _exact(receipt, fields, "previous receipt")
    if receipt["schema_version"] != RECEIPT_SCHEMA or receipt["stage"] not in _STAGES:
        raise EvolutionInputError("previous receipt schema or stage is unsupported")
    _authority(receipt["authority"])
    _ref(receipt["status"], "previous receipt status")
    records = _object(receipt["records"], "previous receipt records")
    _exact(records, set(_RECORD_KEYS), "previous receipt records")
    _readback_list(receipt["readbacks"])
    if not isinstance(receipt["intents"], list):
        raise EvolutionInputError("previous receipt intents must be a list")
    _object(receipt["observations"], "previous receipt observations")
    record_hash = _hash(receipt["record_hash"], "previous receipt record_hash")
    if record_hash != canonical_hash({key: child for key, child in receipt.items() if key != "record_hash"}):
        raise EvolutionInputError("previous receipt is not sealed")
    return receipt


def _load_request(raw: bytes, expected_stage: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    if not isinstance(raw, bytes) or not raw or len(raw) > _MAX_INPUT_BYTES:
        raise EvolutionInputError("stage request exact raw bytes are empty or too large")
    try:
        request = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvolutionInputError("stage request is not exact UTF-8 JSON") from error
    request = _object(request, "stage request")
    fields = {"schema_version", "stage", "authority", "previous_receipt", "payload", "record_hash"}
    _exact(request, fields, "stage request")
    if request["schema_version"] != REQUEST_SCHEMA or request["stage"] != expected_stage:
        raise EvolutionInputError("stage request schema or stage is unsupported")
    authority = _authority(request["authority"])
    payload = _object(request["payload"], "payload")
    supplied_hash = _hash(request["record_hash"], "stage request record_hash")
    if supplied_hash != canonical_hash({key: child for key, child in request.items() if key != "record_hash"}):
        raise EvolutionInputError("stage request is not sealed")
    previous_value = request["previous_receipt"]
    if expected_stage == "prepare":
        if previous_value is not None:
            raise EvolutionInputError("prepare cannot consume a previous receipt")
        previous = None
    else:
        previous = _verify_receipt(previous_value)
        if previous["stage"] != _PREVIOUS_STAGE[expected_stage]:
            raise EvolutionInputError("previous receipt is from the wrong stage")
        if previous["authority"] != authority:
            raise EvolutionInputError("stage request crosses the previous receipt authority")
    return payload, authority, previous


def _empty_records() -> dict[str, Any]:
    return {key: None for key in _RECORD_KEYS}


def _receipt(
    *,
    stage: str,
    authority: Mapping[str, Any],
    status: str,
    records: Mapping[str, Any],
    readbacks: list[dict[str, str]],
    intents: list[dict[str, Any]],
    observations: Mapping[str, Any],
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA,
        "stage": stage,
        "authority": dict(authority),
        "status": status,
        "records": dict(records),
        "readbacks": _readback_list(readbacks),
        "intents": intents,
        "observations": dict(observations),
    }
    value["record_hash"] = canonical_hash(value)
    return value


def _artifact_from_input(kind: str, value: object, authority: Mapping[str, Any]) -> tuple[ArtifactRef, RawReadback]:
    item = _object(value, f"{kind} artifact")
    _exact(item, {"ref", "source_kind", "attestation_ref", "readback"}, f"{kind} artifact")
    ref = _ref(item["ref"], f"{kind}.ref")
    source_kind = _ref(item["source_kind"], f"{kind}.source_kind")
    if source_kind not in _SOURCE_FOR_KIND:
        raise EvolutionInputError(f"{kind} source kind is unsupported")
    readback = _decode_readback(item["readback"], expected_source=_SOURCE_FOR_KIND[source_kind])
    live = kind in {"trace", "evidence", "result"}
    token = ExternalReadback.from_raw(source=readback.source, ref=readback.ref, raw=readback.raw) if live else None
    artifact = ArtifactRef(
        kind=kind,  # type: ignore[arg-type]
        ref=ref,
        content_hash=readback.raw_hash,
        source_kind=source_kind,
        provenance="LIVE" if live else "FROZEN",
        classification="LIVE_ATTESTED" if live else "NON_LIVE",
        attestation_ref=_ref(item["attestation_ref"], f"{kind}.attestation_ref"),
        attested=live,
        run_id=authority["run_id"] if live else None,
        verified_readback=token,
    )
    return artifact, readback


def _artifact_from_record(value: object, readbacks: list[dict[str, str]]) -> ArtifactRef:
    item = _object(value, "artifact record")
    live = item.get("provenance") == "LIVE"
    token = None
    if live:
        expected_source = _SOURCE_FOR_KIND.get(str(item.get("source_kind")))
        if expected_source is None:
            raise EvolutionInputError("artifact record has unsupported source")
        raw = _find_readback(readbacks, source=expected_source, raw_hash=item.get("content_hash"))
        token = ExternalReadback.from_raw(source=raw.source, ref=raw.ref, raw=raw.raw)
    return ArtifactRef(**item, verified_readback=token)  # type: ignore[arg-type]


def _skillops_record(value: object, artifact_type: str, field: str) -> dict[str, Any]:
    item = dict(_object(value, field))
    if item.pop("artifact_type", None) != artifact_type:
        raise EvolutionInputError(f"{field} artifact_type is invalid")
    return item


def _records_and_evolution(previous: Mapping[str, Any]) -> tuple[dict[str, Any], SkillEvolution]:
    records = json.loads(json.dumps(previous["records"]))
    readbacks = _readback_list(previous["readbacks"])
    try:
        baseline_value = _skillops_record(records["baseline"], Baseline.artifact_type, "baseline")
        baseline = Baseline(
            **{
                **baseline_value,
                "dataset_ref": _artifact_from_record(baseline_value["dataset_ref"], readbacks),
                "evaluation_ref": _artifact_from_record(baseline_value["evaluation_ref"], readbacks),
                "trace_refs": tuple(_artifact_from_record(item, readbacks) for item in baseline_value["trace_refs"]),
                "evidence_refs": tuple(
                    _artifact_from_record(item, readbacks)
                    for item in baseline_value["evidence_refs"]
                ),
            }
        )
        attribution_value = _skillops_record(records["attribution"], Attribution.artifact_type, "attribution")
        attribution = Attribution(
            **{
                **attribution_value,
                "trace_refs": tuple(
                    _artifact_from_record(item, readbacks)
                    for item in attribution_value["trace_refs"]
                ),
                "evidence_refs": tuple(
                    _artifact_from_record(item, readbacks)
                    for item in attribution_value["evidence_refs"]
                ),
            }
        )
        proposal = SkillProposal(**_skillops_record(records["proposal"], SkillProposal.artifact_type, "proposal"))
        evolution = SkillEvolution(proposal.skill_name)
        evolution.freeze_baseline(baseline)
        evolution.attribute(attribution)
        evolution.propose(proposal)
        if records["human_decision"] is not None:
            decision = HumanDecision(
                **_skillops_record(
                    records["human_decision"],
                    HumanDecision.artifact_type,
                    "human decision",
                )
            )
            verification_value = _skillops_record(
                records["human_verification"],
                HumanDecisionVerification.artifact_type,
                "human verification",
            )
            matrix_raw = _find_readback(readbacks, source="matrix", raw_hash=verification_value["event_hash"])
            verification = HumanDecisionVerification(
                **verification_value,
                verified_readback=ExternalReadback.from_raw(source="matrix", ref=matrix_raw.ref, raw=matrix_raw.raw),
            )
            evolution.record_human_decision(decision, verifier=lambda *_: verification)
        if records["canary"] is not None:
            value = _skillops_record(records["canary"], CanaryObservation.artifact_type, "canary")
            canary = CanaryObservation(
                **{
                    **value,
                    "dataset_ref": _artifact_from_record(value["dataset_ref"], readbacks),
                    "evaluation_ref": _artifact_from_record(value["evaluation_ref"], readbacks),
                    "result_ref": _artifact_from_record(value["result_ref"], readbacks),
                    "trace_refs": tuple(_artifact_from_record(item, readbacks) for item in value["trace_refs"]),
                    "evidence_refs": tuple(_artifact_from_record(item, readbacks) for item in value["evidence_refs"]),
                }
            )
            evolution.record_canary(canary)
        if records["reevaluation"] is not None:
            value = _skillops_record(records["reevaluation"], ReevaluationObservation.artifact_type, "reevaluation")
            reevaluation = ReevaluationObservation(
                **{
                    **value,
                    "dataset_ref": _artifact_from_record(value["dataset_ref"], readbacks),
                    "evaluation_ref": _artifact_from_record(value["evaluation_ref"], readbacks),
                    "result_ref": _artifact_from_record(value["result_ref"], readbacks),
                    "trace_refs": tuple(_artifact_from_record(item, readbacks) for item in value["trace_refs"]),
                    "evidence_refs": tuple(_artifact_from_record(item, readbacks) for item in value["evidence_refs"]),
                }
            )
            evolution.record_reevaluation(reevaluation)
        if records["receipt"] is not None:
            evolution.close(
                SkillReceipt(
                    **_skillops_record(
                        records["receipt"], SkillReceipt.artifact_type, "receipt"
                    )
                )
            )
    except (KeyError, TypeError, ValueError, AuthorityError) as error:
        raise EvolutionInputError("previous receipt cannot replay the SkillOps lifecycle") from error
    return records, evolution


def prepare(raw_request: bytes) -> dict[str, Any]:
    payload, authority, _ = _load_request(raw_request, "prepare")
    fields = {
        "skill_name", "baseline_id", "attribution_id", "proposal_id", "base_version",
        "candidate_version", "package_uri", "rollback_ref", "hero_readback",
        "human_allowlist_readback", "candidate_package_readback", "dataset",
        "evaluation", "traces", "evidence",
    }
    _exact(payload, fields, "prepare payload")
    hero = _decode_readback(payload["hero_readback"], expected_source="agentteams")
    hero_result = _check_raw_authority(hero.raw, authority, "Hero readback")
    allowlist_raw = _decode_readback(payload["human_allowlist_readback"], expected_source="authority")
    _allowlist(allowlist_raw)
    if hero_result.get("human_allowlist_hash") != allowlist_raw.raw_hash:
        raise EvolutionInputError("Hero readback does not bind the cached Human allowlist")
    package = _decode_readback(payload["candidate_package_readback"], expected_source="nacos")
    if package.ref != payload["package_uri"]:
        raise EvolutionInputError("candidate package readback does not match package_uri")
    dataset, dataset_raw = _artifact_from_input("dataset", payload["dataset"], authority)
    evaluation, evaluation_raw = _artifact_from_input("evaluation", payload["evaluation"], authority)
    if not isinstance(payload["traces"], list) or not payload["traces"]:
        raise EvolutionInputError("prepare traces must be non-empty")
    if not isinstance(payload["evidence"], list) or not payload["evidence"]:
        raise EvolutionInputError("prepare evidence must be non-empty")
    trace_pairs = [_artifact_from_input("trace", item, authority) for item in payload["traces"]]
    evidence_pairs = [_artifact_from_input("evidence", item, authority) for item in payload["evidence"]]
    baseline = Baseline.freeze(
        baseline_id=_ref(payload["baseline_id"], "baseline_id"),
        dataset_ref=dataset,
        evaluation_ref=evaluation,
        run_id=authority["run_id"],
        trace_refs=tuple(item[0] for item in trace_pairs),
        evidence_refs=tuple(item[0] for item in evidence_pairs),
    )
    attribution = Attribution.create(
        attribution_id=_ref(payload["attribution_id"], "attribution_id"),
        skill_name=_ref(payload["skill_name"], "skill_name"),
        base_version=_version(payload["base_version"], "base_version"),
        baseline=baseline,
        trace_refs=baseline.trace_refs,
        evidence_refs=baseline.evidence_refs,
    )
    proposal = SkillProposal.create(
        proposal_id=_ref(payload["proposal_id"], "proposal_id"),
        skill_name=attribution.skill_name,
        base_version=attribution.base_version,
        candidate_version=_version(payload["candidate_version"], "candidate_version"),
        content_hash=package.raw_hash,
        rollback_ref=_ref(payload["rollback_ref"], "rollback_ref"),
        baseline=baseline,
        attribution=attribution,
    )
    evolution = SkillEvolution(proposal.skill_name)
    evolution.freeze_baseline(baseline)
    evolution.attribute(attribution)
    evolution.propose(proposal)
    candidate = NativePackageRef(
        _ref(payload["package_uri"], "package_uri"), proposal.candidate_version,
        proposal.content_hash, proposal.rollback_ref,
    )
    readbacks: list[dict[str, str]] = []
    exact_sources = (
        hero,
        allowlist_raw,
        package,
        dataset_raw,
        evaluation_raw,
        *(pair[1] for pair in trace_pairs),
        *(pair[1] for pair in evidence_pairs),
    )
    for item in exact_sources:
        _add_readback(readbacks, item)
    records = _empty_records()
    records.update(
        {
            "baseline": baseline.as_dict(),
            "attribution": attribution.as_dict(),
            "proposal": proposal.as_dict(),
        }
    )
    return _receipt(
        stage="prepare", authority=authority, status=evolution.state, records=records,
        readbacks=readbacks,
        intents=[{
            "schema_version": "testweaver.external-human-approval-intent/v1",
            "action": "REQUEST_EXTERNAL_MATRIX_DECISION",
            "proposal_ref": proposal.proposal_id,
            "proposal_hash": proposal.record_hash,
            "signer": "external-human-only",
        }],
        observations={"candidate": {
            **build_native_publish_intent(candidate, action="CANARY"),
            "skill_name": proposal.skill_name,
            "package_readback_source": package.source,
            "package_readback_ref": package.ref,
            "package_readback_hash": package.raw_hash,
        }, "human_allowlist": {
            "readback_ref": allowlist_raw.ref,
            "readback_hash": allowlist_raw.raw_hash,
        }},
    )


def _allowlist(readback: RawReadback) -> tuple[dict[str, str], str, str]:
    value = _sealed_json(readback.raw, "Human allowlist")
    _exact(
        value,
        {"schema_version", "homeserver_ref", "reader_identity_ref", "identities", "record_hash"},
        "Human allowlist",
    )
    if value["schema_version"] != "testweaver.human-allowlist/v1":
        raise EvolutionInputError("Human allowlist schema is unsupported")
    identities = _object(value["identities"], "Human allowlist identities")
    if not identities:
        raise EvolutionInputError("Human allowlist is empty")
    protected: dict[str, str] = {}
    for sender, identity in identities.items():
        protected[_ref(sender, "allowlisted sender")] = _ref(identity, "allowlisted identity")
    return (
        protected,
        _ref(value["homeserver_ref"], "trusted homeserver"),
        _ref(value["reader_identity_ref"], "trusted reader"),
    )


def verify_approval(raw_request: bytes) -> dict[str, Any]:
    payload, authority, previous = _load_request(raw_request, "verify-approval")
    assert previous is not None
    _exact(
        payload,
        {
            "approval_id",
            "decision",
            "revision",
            "verification_ref",
            "verified_at",
            "allowlist_ref",
            "matrix_event",
        },
        "verify-approval payload",
    )
    records, evolution = _records_and_evolution(previous)
    if evolution.state != "PROPOSED" or evolution.proposal is None or evolution.baseline is None:
        raise EvolutionInputError("approval requires a proposed Skill evolution")
    cached_allowlist = _object(previous["observations"].get("human_allowlist"), "cached Human allowlist")
    if payload["allowlist_ref"] != cached_allowlist.get("readback_ref"):
        raise EvolutionInputError("approval does not select the Hero-bound Human allowlist")
    allowlist_raw = _find_readback(
        _readback_list(previous["readbacks"]),
        source="authority",
        ref=cached_allowlist["readback_ref"],
        raw_hash=cached_allowlist["readback_hash"],
    )
    identities, trusted_homeserver, trusted_reader = _allowlist(allowlist_raw)
    matrix = _object(payload["matrix_event"], "matrix event")
    _exact(
        matrix,
        {
            "homeserver_ref",
            "reader_identity_ref",
            "request_ref",
            "room_id",
            "event_id",
            "readback",
        },
        "matrix event",
    )
    event_raw = _decode_readback(matrix["readback"], expected_source="matrix")
    try:
        event_value = json.loads(event_raw.raw)
        sender = event_value["sender"]
        identity_ref = event_value["content"]["testweaver"]["identity_ref"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise EvolutionInputError("Matrix exact event lacks its Human identity") from error
    decision = payload["decision"]
    if decision not in {"APPROVE", "DENY"}:
        raise EvolutionInputError("Matrix decision must be APPROVE or DENY")
    revision = payload["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise EvolutionInputError("approval revision must be positive")
    expectation = MatrixDecisionExpectation.create(
        room_id=_ref(matrix["room_id"], "room_id"),
        event_id=_ref(matrix["event_id"], "event_id"),
        sender=_ref(sender, "sender"),
        identity_ref=_ref(identity_ref, "identity_ref"),
        approval_id=_ref(payload["approval_id"], "approval_id"),
        phase=decision,
        decision=decision,
        campaign_id=authority["campaign_id"],
        run_id=authority["run_id"],
        trace_id=authority["trace_id"],
        revision=revision,
        action_ref=evolution.proposal.proposal_id,
        action_hash=evolution.proposal.record_hash,
        verification_ref=_ref(payload["verification_ref"], "verification_ref"),
        verified_at=_ref(payload["verified_at"], "verified_at"),
    )
    authenticated = MatrixAuthenticatedEvent.create(
        raw_bytes=event_raw.raw,
        homeserver_ref=_ref(matrix["homeserver_ref"], "homeserver_ref"),
        reader_identity_ref=_ref(matrix["reader_identity_ref"], "reader_identity_ref"),
        request_ref=_ref(matrix["request_ref"], "request_ref"),
        room_id=expectation.room_id,
        event_id=expectation.event_id,
    )
    verifier = MatrixHumanReadbackVerifier(
        get_event=lambda *_: authenticated,
        get_identity=lambda name: identities.get(name, "NOT_ALLOWLISTED"),
        human_identities=identities,
        get_pending_approval=lambda approval_id: expectation if approval_id == expectation.approval_id else None,
        trusted_homeserver_ref=trusted_homeserver,
        trusted_reader_identity_ref=trusted_reader,
        clock=lambda: expectation.verified_at,
    )
    try:
        attestation = verifier.verify(expectation)
    except AuthorityError as error:
        raise EvolutionInputError(f"Matrix approval exact readback/allowlist verification failed: {error}") from error
    human = HumanDecision.create(
        decision_id=expectation.approval_id,
        decision_revision=expectation.revision,
        proposal=evolution.proposal,
        actor_ref=attestation.sender,
        identity_ref=attestation.identity_ref,
        attestation_ref=attestation.event_ref,
        actor_kind="external-human",
        decision="APPROVE" if decision == "APPROVE" else "REJECT",
        decided_at=attestation.verified_at,
    )
    token = ExternalReadback.from_raw(source="matrix", ref=attestation.event_ref, raw=event_raw.raw)
    verification = HumanDecisionVerification.create(
        verification_ref=attestation.verification_ref,
        source="matrix-live-readback",
        event_ref=attestation.event_ref,
        event_hash=attestation.event_hash,
        sender=attestation.sender,
        identity_ref=attestation.identity_ref,
        decision_ref=human.decision_id,
        decision_hash=human.record_hash,
        proposal_ref=evolution.proposal.proposal_id,
        proposal_hash=evolution.proposal.record_hash,
        decision_revision=human.decision_revision,
        decision=human.decision,
        baseline_ref=evolution.baseline.baseline_id,
        baseline_hash=evolution.baseline.record_hash,
        run_id=authority["run_id"],
        verified_at=attestation.verified_at,
        verified_readback=token,
    )
    evolution.record_human_decision(human, verifier=lambda *_: verification)
    records["human_decision"] = human.as_dict()
    records["human_verification"] = verification.as_dict()
    readbacks = _readback_list(previous["readbacks"])
    _add_readback(readbacks, RawReadback("matrix", attestation.event_ref, event_raw.raw, event_raw.raw_hash))
    return _receipt(
        stage="verify-approval", authority=authority, status=evolution.state, records=records,
        readbacks=readbacks, intents=[],
        observations={**previous["observations"], "human_attestation": attestation.as_dict()},
    )


def _nacos_response(
    value: object, name: str, readbacks: list[dict[str, str]]
) -> tuple[NacosHttpResponse, RawReadback]:
    item = _object(value, f"Nacos {name} response")
    _exact(item, {"status_code", "headers", "readback"}, f"Nacos {name} response")
    status = item["status_code"]
    if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
        raise EvolutionInputError("Nacos response status is invalid")
    headers = _object(item["headers"], "Nacos response headers")
    if any(not isinstance(key, str) or not isinstance(child, str) for key, child in headers.items()):
        raise EvolutionInputError("Nacos response headers are invalid")
    raw = _decode_readback(item["readback"], expected_source="nacos")
    _add_readback(readbacks, raw)
    return NacosHttpResponse(status, raw.raw, headers), raw


def publish_candidate(raw_request: bytes) -> dict[str, Any]:
    payload, authority, previous = _load_request(raw_request, "publish-candidate")
    assert previous is not None
    _exact(payload, {"nacos_readbacks"}, "publish-candidate payload")
    records, evolution = _records_and_evolution(previous)
    if evolution.state != "HUMAN_APPROVED" or evolution.proposal is None:
        raise EvolutionInputError("candidate publication requires verified Human approval")
    candidate_info = _object(previous["observations"].get("candidate"), "candidate observation")
    candidate = NativePackageRef(
        candidate_info["package_uri"], evolution.proposal.candidate_version,
        evolution.proposal.content_hash, evolution.proposal.rollback_ref,
    )
    prior_readbacks = _readback_list(previous["readbacks"])
    package = _find_readback(
        prior_readbacks, source=candidate_info["package_readback_source"],
        ref=candidate_info["package_readback_ref"], raw_hash=candidate_info["package_readback_hash"],
    )
    supplied = _object(payload["nacos_readbacks"], "Nacos readbacks")
    names = ("upload", "submit", "publish", "download", "admin")
    _exact(supplied, set(names), "Nacos readbacks")
    responses: list[tuple[NacosHttpResponse, RawReadback]] = [
        _nacos_response(supplied[name], name, prior_readbacks) for name in names
    ]
    expected = (
        ("POST", "/v3/admin/ai/skills/upload"),
        ("POST", "/v3/admin/ai/skills/submit"),
        ("POST", "/v3/admin/ai/skills/publish"),
        ("GET", "/v3/client/ai/skills"),
        ("GET", "/v3/admin/ai/skills"),
    )
    calls = 0

    def transport(
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> NacosHttpResponse:
        nonlocal calls
        del headers, body, timeout
        if calls >= len(expected):
            raise EvolutionInputError("Nacos transcript has unexpected extra operations")
        actual_path = urlsplit(url).path
        if actual_path.startswith("/nacos"):
            actual_path = actual_path[len("/nacos"):]
        if (method, actual_path) != expected[calls]:
            raise EvolutionInputError("Nacos transcript does not match the v3 native publish sequence")
        response = responses[calls][0]
        calls += 1
        return response

    try:
        result = NacosV3Client(transport=transport).publish_skill(
            name=evolution.proposal.skill_name,
            version=evolution.proposal.candidate_version,
            zip_bytes=package.raw,
            package_hash=evolution.proposal.content_hash,
        )
    except Exception as error:
        raise EvolutionInputError("Nacos exact upload/publish/download/admin readback failed") from error
    if calls != len(expected) or result.get("exact_version_readback") is not True:
        raise EvolutionInputError("Nacos exact version was not read back")
    admin_raw = responses[-1][1]
    native_readback = verify_native_package_readback(
        candidate,
        action="CANARY",
        readback={
            "package_uri": candidate.package_uri,
            "version": candidate.version,
            "content_hash": candidate.content_hash,
            "readback_ref": admin_raw.ref,
        },
        readback_token=ExternalReadback.from_raw(source="nacos", ref=admin_raw.ref, raw=admin_raw.raw),
    )
    activation_intent = {
        "schema_version": "testweaver.official-skill-activation-intent/v1",
        "action": "ACTIVATE_CANDIDATE",
        "owner": "official-agentspec-agt",
        "package_uri": candidate.package_uri,
        "skill_name": evolution.proposal.skill_name,
        "version": candidate.version,
        "content_hash": candidate.content_hash,
        "requires_external_sealed_readback": True,
        "embedded_remote_skills_exposed": False,
    }
    return _receipt(
        stage="publish-candidate", authority=authority, status="CANDIDATE_PUBLISHED",
        records=records, readbacks=prior_readbacks, intents=[activation_intent],
        observations={**previous["observations"], "nacos": result, "native_package_readback": native_readback},
    )


def _live_artifact(
    *, kind: str, ref: str, source_kind: str, readback: RawReadback, run_id: str
) -> ArtifactRef:
    token = ExternalReadback.from_raw(source=readback.source, ref=readback.ref, raw=readback.raw)
    return ArtifactRef(
        kind=kind,  # type: ignore[arg-type]
        ref=_ref(ref, f"{kind}.ref"),
        content_hash=readback.raw_hash,
        source_kind=source_kind,
        provenance="LIVE",
        classification="LIVE_ATTESTED",
        attestation_ref=readback.ref,
        attested=True,
        run_id=run_id,
        verified_readback=token,
    )


def record_canary(raw_request: bytes) -> dict[str, Any]:
    payload, authority, previous = _load_request(raw_request, "record-canary")
    assert previous is not None
    _exact(payload, {"activation_readback", "canary_readback"}, "record-canary payload")
    records, evolution = _records_and_evolution(previous)
    if evolution.state != "HUMAN_APPROVED" or evolution.proposal is None or evolution.baseline is None:
        raise EvolutionInputError("canary requires an approved proposal")
    activation_raw = _decode_readback(payload["activation_readback"], expected_source="agentteams")
    canary_raw = _decode_readback(payload["canary_readback"], expected_source="agentteams")
    activation = _check_raw_authority(activation_raw.raw, authority, "activation readback")
    result = _check_raw_authority(canary_raw.raw, authority, "native canary")
    _exact(
        activation,
        {
            "schema_version",
            *_AUTHORITY_FIELDS,
            "operator",
            "package_uri",
            "skill_name",
            "version",
            "package_hash",
            "status",
            "record_hash",
        },
        "activation readback",
    )
    _exact(
        result,
        {
            "schema_version",
            *_AUTHORITY_FIELDS,
            "skill_name",
            "candidate_version",
            "package_hash",
            "activation_receipt_hash",
            "status",
            "result_ref",
            "trace_refs",
            "evidence_refs",
            "record_hash",
        },
        "native canary",
    )
    candidate = _object(previous["observations"].get("candidate"), "candidate observation")
    expected_activation = {
        "operator": "official-agentspec-agt",
        "package_uri": candidate["package_uri"],
        "skill_name": evolution.proposal.skill_name,
        "version": evolution.proposal.candidate_version,
        "package_hash": evolution.proposal.content_hash,
        "status": "ACTIVATED",
    }
    if any(activation.get(key) != child for key, child in expected_activation.items()):
        raise EvolutionInputError("official AgentSpec/agt activation readback does not match candidate")
    if result.get("activation_receipt_hash") != activation_raw.raw_hash:
        raise EvolutionInputError("native canary is not bound to exact activation raw bytes")
    for key, child in {
        "skill_name": evolution.proposal.skill_name,
        "candidate_version": evolution.proposal.candidate_version,
        "package_hash": evolution.proposal.content_hash,
    }.items():
        if result.get(key) != child:
            raise EvolutionInputError("native canary does not match candidate")
    status = result.get("status")
    if status not in {"PASS", "FAIL"}:
        raise EvolutionInputError("native canary must report exact PASS or FAIL")
    trace_refs = result.get("trace_refs")
    evidence_refs = result.get("evidence_refs")
    if not isinstance(trace_refs, list) or not trace_refs or not isinstance(evidence_refs, list) or not evidence_refs:
        raise EvolutionInputError("native canary requires trace and evidence refs")
    observation = CanaryObservation.create(
        observation_id=f"skillops-canary:{canary_raw.raw_hash[7:23]}",
        proposal_ref=evolution.proposal.proposal_id,
        proposal_hash=evolution.proposal.record_hash,
        candidate_version=evolution.proposal.candidate_version,
        dataset_ref=evolution.baseline.dataset_ref,
        evaluation_ref=evolution.baseline.evaluation_ref,
        result_ref=_live_artifact(
            kind="result",
            ref=result["result_ref"],
            source_kind="agentteams-native",
            readback=canary_raw,
            run_id=authority["run_id"],
        ),
        trace_refs=tuple(
            _live_artifact(
                kind="trace",
                ref=child,
                source_kind="agentteams-native",
                readback=canary_raw,
                run_id=authority["run_id"],
            )
            for child in trace_refs
        ),
        evidence_refs=tuple(
            _live_artifact(
                kind="evidence",
                ref=child,
                source_kind="agentteams-native",
                readback=canary_raw,
                run_id=authority["run_id"],
            )
            for child in evidence_refs
        ),
        status=status,
    )
    evolution.record_canary(observation)
    records["canary"] = observation.as_dict()
    readbacks = _readback_list(previous["readbacks"])
    _add_readback(readbacks, activation_raw)
    _add_readback(readbacks, canary_raw)
    return _receipt(
        stage="record-canary", authority=authority, status=evolution.state, records=records,
        readbacks=readbacks, intents=[],
        observations={
            **previous["observations"],
            "activation": {
                "readback_ref": activation_raw.ref,
                "readback_hash": activation_raw.raw_hash,
            },
            "canary": {
                "status": status,
                "readback_ref": canary_raw.ref,
                "readback_hash": canary_raw.raw_hash,
            },
        },
    )


def _oracle_from_raw(readback: RawReadback, authority: Mapping[str, Any], label: str) -> OracleResult:
    try:
        value = _object(json.loads(readback.raw), label)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvolutionInputError(f"{label} exact record is not JSON") from error
    try:
        result = OracleResult(
            **{
                **value,
                "evidence_refs": tuple(value["evidence_refs"]),
                "read_result_refs": tuple(value.get("read_result_refs", ())),
            }
        )
    except (KeyError, TypeError, AuthorityError) as error:
        raise EvolutionInputError(f"{label} is not a sealed OracleResult") from error
    for field in ("campaign_id", "run_id", "trace_id"):
        if getattr(result, field) != authority[field]:
            raise EvolutionInputError(f"{label} crosses {field}")
    return result


def _combined_readback(source: str, ref: str, values: list[RawReadback]) -> RawReadback:
    raw = b"".join(len(item.raw).to_bytes(8, "big") + item.raw for item in values)
    return RawReadback(source, ref, raw, digest_bytes(raw))


def _reevaluate_oracle(
    payload: Mapping[str, Any],
    authority: Mapping[str, Any],
    readbacks: list[dict[str, str]],
) -> tuple[
    str,
    ArtifactRef,
    tuple[ArtifactRef, ...],
    tuple[ArtifactRef, ...],
    dict[str, Any],
]:
    _exact(
        payload,
        {
            "mode",
            "outcome_record",
            "outcome_result",
            "boundary_record",
            "boundary_result",
        },
        "Oracle reevaluation",
    )
    outcome_record = _decode_readback(payload["outcome_record"], expected_source="evaluation")
    outcome_result_raw = _decode_readback(payload["outcome_result"], expected_source="evaluation")
    boundary_record = _decode_readback(payload["boundary_record"], expected_source="evaluation")
    boundary_result_raw = _decode_readback(payload["boundary_result"], expected_source="evaluation")
    outcome = _oracle_from_raw(outcome_record, authority, "Outcome Oracle")
    boundary = _oracle_from_raw(boundary_record, authority, "Boundary Oracle")
    try:
        validate_oracle_pair(outcome, boundary)
    except AuthorityError as error:
        raise EvolutionInputError("independent Oracle pair verification failed") from error
    for oracle, exact in ((outcome, outcome_result_raw), (boundary, boundary_result_raw)):
        if oracle.result_ref != exact.ref or oracle.result_hash != exact.raw_hash:
            raise EvolutionInputError("Oracle result hash is a self-report without exact raw result")
    for item in (outcome_record, outcome_result_raw, boundary_record, boundary_result_raw):
        _add_readback(readbacks, item)
    combined = _combined_readback(
        "evaluation",
        f"oracle-pair:{outcome.result_id}:{boundary.result_id}",
        [outcome_result_raw, boundary_result_raw],
    )
    _add_readback(readbacks, combined)
    if outcome.status == boundary.status == "PASS":
        status = "PASS"
    elif "FAIL" in {outcome.status, boundary.status}:
        status = "FAIL"
    else:
        status = "BLOCKED"
    run_id = authority["run_id"]
    result_ref = _live_artifact(
        kind="result",
        ref=combined.ref,
        source_kind="evaluation-export",
        readback=combined,
        run_id=run_id,
    )
    traces = tuple(
        _live_artifact(
            kind="trace",
            ref=item.ref,
            source_kind="evaluation-export",
            readback=item,
            run_id=run_id,
        )
        for item in (outcome_record, boundary_record)
    )
    evidence = tuple(
        _live_artifact(
            kind="evidence",
            ref=item.ref,
            source_kind="evaluation-export",
            readback=item,
            run_id=run_id,
        )
        for item in (outcome_result_raw, boundary_result_raw)
    )
    return status, result_ref, traces, evidence, {
        "mode": "oracle", "status": status,
        "outcome_ref": outcome.result_id, "outcome_hash": outcome.content_hash,
        "boundary_ref": boundary.result_id, "boundary_hash": boundary.content_hash,
    }


class _AgentLoopExactTransport:
    def __init__(self, values: list[RawReadback]):
        self.values = values
        self.calls = 0

    def request(self, **request: Any) -> AgentLoopHTTPResponse:
        if request.get("method") != "GET" or self.calls >= len(self.values):
            raise EvolutionInputError("AgentLoop exact result attempted an unsupported operation")
        raw = self.values[self.calls]
        self.calls += 1
        return AgentLoopHTTPResponse(200, raw.raw, f"sealed-readback-{self.calls}")


def _reevaluate_agentloop(
    payload: Mapping[str, Any],
    authority: Mapping[str, Any],
    readbacks: list[dict[str, str]],
) -> tuple[
    str,
    ArtifactRef,
    tuple[ArtifactRef, ...],
    tuple[ArtifactRef, ...],
    dict[str, Any],
]:
    _exact(
        payload,
        {
            "mode",
            "endpoint",
            "agent_space",
            "task_id",
            "observed_at",
            "task_response",
            "runs_response",
        },
        "AgentLoop reevaluation",
    )
    task = _decode_readback(payload["task_response"], expected_source="agentloop")
    runs = _decode_readback(payload["runs_response"], expected_source="agentloop")
    transport = _AgentLoopExactTransport([task, runs])
    try:
        verification = AgentLoopClient(
            AgentLoopEndpoint(payload["endpoint"], payload["agent_space"]),
            transport,
            lambda: AgentLoopCredentialLease("sealed-input:agentloop-readback", object()),
            lambda: _ref(payload["observed_at"], "AgentLoop observed_at"),
        ).verify_evaluation_task_run(
            AgentLoopScope(authority["campaign_id"], authority["run_id"], authority["pg_revision"]),
            task_id=_ref(payload["task_id"], "AgentLoop task_id"),
        )
    except (AuthorityError, EvolutionInputError, TypeError) as error:
        raise EvolutionInputError("AgentLoop exact result verification failed") from error
    if transport.calls != 2:
        raise EvolutionInputError("AgentLoop exact task/run pair was not fully consumed")
    for item in (task, runs):
        _add_readback(readbacks, item)
    combined = _combined_readback("agentloop", f"agentloop-result:{payload['task_id']}", [task, runs])
    _add_readback(readbacks, combined)
    fully_successful = (
        verification.result_count > 0
        and verification.successful_result_count == verification.result_count
    )
    if verification.status == "API_QUERY_VERIFIED" and fully_successful:
        status = "PASS"
    elif verification.terminal and verification.result_count > 0:
        status = "FAIL"
    else:
        status = "BLOCKED"
    run_id = authority["run_id"]
    result_ref = _live_artifact(
        kind="result",
        ref=combined.ref,
        source_kind="agentloop-sls",
        readback=combined,
        run_id=run_id,
    )
    traces = (_live_artifact(kind="trace", ref=task.ref, source_kind="agentloop-sls", readback=task, run_id=run_id),)
    evidence = (
        _live_artifact(
            kind="evidence",
            ref=runs.ref,
            source_kind="agentloop-sls",
            readback=runs,
            run_id=run_id,
        ),
    )
    return status, result_ref, traces, evidence, {
        "mode": "agentloop", "status": status,
        "verification_status": verification.status,
        "verification_hash": verification.content_hash,
        "result_count": verification.result_count,
        "successful_result_count": verification.successful_result_count,
    }


def reevaluate(raw_request: bytes) -> dict[str, Any]:
    payload, authority, previous = _load_request(raw_request, "reevaluate")
    assert previous is not None
    records, evolution = _records_and_evolution(previous)
    if evolution.state != "CANARY_RECORDED" or evolution.proposal is None or evolution.baseline is None:
        raise EvolutionInputError("reevaluation requires one recorded native canary")
    readbacks = _readback_list(previous["readbacks"])
    mode = payload.get("mode")
    if mode == "oracle":
        status, result_ref, traces, evidence, summary = _reevaluate_oracle(payload, authority, readbacks)
    elif mode == "agentloop":
        status, result_ref, traces, evidence, summary = _reevaluate_agentloop(payload, authority, readbacks)
    else:
        raise EvolutionInputError("reevaluation mode must be oracle or agentloop")
    observation = ReevaluationObservation.create(
        observation_id=f"skillops-reevaluation:{result_ref.content_hash[7:23]}",
        proposal_ref=evolution.proposal.proposal_id,
        proposal_hash=evolution.proposal.record_hash,
        candidate_version=evolution.proposal.candidate_version,
        dataset_ref=evolution.baseline.dataset_ref,
        evaluation_ref=evolution.baseline.evaluation_ref,
        result_ref=result_ref,
        trace_refs=traces,
        evidence_refs=evidence,
        status=status,
    )
    evolution.record_reevaluation(observation)
    records["reevaluation"] = observation.as_dict()
    return _receipt(
        stage="reevaluate", authority=authority, status=evolution.state, records=records,
        readbacks=readbacks, intents=[],
        observations={**previous["observations"], "reevaluation": summary},
    )


def close(raw_request: bytes) -> dict[str, Any]:
    payload, authority, previous = _load_request(raw_request, "close")
    assert previous is not None
    _exact(payload, {"receipt_id"}, "close payload")
    records, evolution = _records_and_evolution(previous)
    required = (
        evolution.proposal,
        evolution.baseline,
        evolution.canary,
        evolution.reevaluation,
        evolution.human_decision,
        evolution.human_verification,
    )
    if evolution.state != "REEVALUATED" or not all(required):
        raise EvolutionInputError("close requires the complete verified SkillOps lifecycle")
    proposal = evolution.proposal
    action = "PROMOTE" if evolution.canary.status == evolution.reevaluation.status == "PASS" else "ROLLBACK"
    receipt = SkillReceipt.create(
        receipt_id=_ref(payload["receipt_id"], "receipt_id"),
        proposal_ref=proposal.proposal_id,
        proposal_hash=proposal.record_hash,
        action=action,
        base_version=proposal.base_version,
        candidate_version=proposal.candidate_version,
        active_version=proposal.candidate_version if action == "PROMOTE" else proposal.base_version,
        rollback_ref=proposal.rollback_ref,
        baseline_hash=evolution.baseline.record_hash,
        canary_ref=evolution.canary.observation_id,
        canary_hash=evolution.canary.record_hash,
        reevaluation_ref=evolution.reevaluation.observation_id,
        reevaluation_hash=evolution.reevaluation.record_hash,
        human_decision_ref=evolution.human_decision.decision_id,
        human_decision_hash=evolution.human_decision.record_hash,
        human_verification_ref=evolution.human_verification.verification_ref,
        human_verification_hash=evolution.human_verification.record_hash,
    )
    evolution.close(receipt)
    records["receipt"] = receipt.as_dict()
    candidate_info = _object(previous["observations"].get("candidate"), "candidate observation")
    candidate = NativePackageRef(
        candidate_info["package_uri"],
        proposal.candidate_version,
        proposal.content_hash,
        proposal.rollback_ref,
    )
    intent: dict[str, Any] = build_native_publish_intent(candidate, action=action)
    intent.update({
        "owner": "official-agentspec-agt",
        "active_version": receipt.active_version,
        "requires_external_sealed_readback": True,
        "executed": False,
    })
    return _receipt(
        stage="close", authority=authority, status=evolution.state, records=records,
        readbacks=_readback_list(previous["readbacks"]), intents=[intent],
        observations=previous["observations"],
    )


_HANDLERS = {
    "prepare": prepare,
    "verify-approval": verify_approval,
    "publish-candidate": publish_candidate,
    "record-canary": record_canary,
    "reevaluate": reevaluate,
    "close": close,
}


def _read_input(path: Path) -> bytes:
    if str(path) == "-":
        raw = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
        if len(raw) > _MAX_INPUT_BYTES:
            raise EvolutionInputError("input is too large")
        return raw
    if not path.is_absolute():
        raise EvolutionInputError("input path must be absolute or -")
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_INPUT_BYTES:
            raise EvolutionInputError("input must be a bounded regular file")
        return os.read(descriptor, _MAX_INPUT_BYTES + 1)
    except EvolutionInputError:
        raise
    except OSError as error:
        raise EvolutionInputError("input is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _write_receipt(path: Path, value: Mapping[str, Any]) -> None:
    if not path.is_absolute():
        raise EvolutionInputError("receipt path must be absolute")
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    if len(encoded) > _MAX_RECEIPT_BYTES:
        raise EvolutionInputError("receipt is too large")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
        descriptor = -1
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Advance one sealed post-Hero Skill evolution without orchestration")
    parser.add_argument("stage", choices=_STAGES)
    parser.add_argument("--input", required=True, type=Path, help="absolute sealed JSON path or -")
    parser.add_argument("--receipt", type=Path, default=None, help="optional absolute receipt output")
    args = parser.parse_args()
    try:
        result = _HANDLERS[args.stage](_read_input(args.input))
        if args.receipt is not None:
            _write_receipt(args.receipt, result)
        else:
            json.dump(result, sys.stdout, sort_keys=True, indent=2)
            sys.stdout.write("\n")
        return 0
    except (EvolutionInputError, ValueError, AuthorityError) as error:
        print(f"testweaver-skill-evolve: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
