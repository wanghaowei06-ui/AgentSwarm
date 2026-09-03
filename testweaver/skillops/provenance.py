"""Adapters from existing native receipts to SkillOps readback tokens.

Caller-supplied bytes never enter this module as attested evidence on their
own.  Every public adapter requires an existing authority or observability
receipt and reconciles that receipt with the exact raw response bytes.
"""

from __future__ import annotations

import hashlib
import json

from testweaver.authority import HumanReadbackAttestation, SideEffectEntry
from testweaver.observability import QueryReceipt

from .state import (
    ExternalReadback,
    SkillOperationVerification,
    SkillOpsError,
    SkillProposal,
    SkillReceipt,
    _external_readback,
    _hash as _state_hash,
    _ref as _state_ref,
)


def _digest(raw: bytes) -> str:
    if not isinstance(raw, bytes) or not raw:
        raise SkillOpsError("exact readback bytes are required")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def matrix_readback_from_authority(
    attestation: HumanReadbackAttestation, *, raw: bytes
) -> ExternalReadback:
    """Accept only a validated Matrix attestation bound to exact event bytes."""

    if not isinstance(attestation, HumanReadbackAttestation):
        raise SkillOpsError("Matrix authority attestation is required")
    try:
        attestation.validate()
    except Exception as error:
        raise SkillOpsError("Matrix authority attestation is invalid") from error
    if attestation.phase not in {"APPROVE", "DENY"}:
        raise SkillOpsError("Matrix receipt is not a Human decision")
    if attestation.event_hash != _digest(raw):
        raise SkillOpsError("Matrix receipt does not bind the exact event bytes")
    return _external_readback(
        source="matrix",
        ref=attestation.event_ref,
        raw=raw,
        classification="AUTHORITY_RECEIPT",
        claims=tuple(
            sorted(
                {
                    "campaign_id": attestation.campaign_id,
                    "run_id": attestation.run_id,
                    "trace_id": attestation.trace_id,
                    "revision": str(attestation.revision),
                    "sender": attestation.sender,
                    "identity_ref": attestation.identity_ref,
                    "approval_id": attestation.approval_id,
                    "decision": (
                        "APPROVE"
                        if attestation.decision == "APPROVE"
                        else "REJECT"
                    ),
                    "decision_revision": str(attestation.revision),
                }.items()
            )
        ),
        verified=True,
    )


def agentloop_readback_from_observability(
    receipt: QueryReceipt,
    *,
    raw: bytes,
    dataset_ref: str,
    dataset_hash: str,
    evaluation_ref: str,
    evaluation_hash: str,
) -> ExternalReadback:
    """Accept one exact AgentLoop verdict for the frozen evaluation set."""

    if not isinstance(receipt, QueryReceipt):
        raise SkillOpsError("AgentLoop observability receipt is required")
    required_matches = frozenset(receipt.correlation.as_dict())
    if (
        receipt.schema_version != "testweaver.observability-query/v1"
        or receipt.status != "VERIFIED"
        or receipt.backend != "agentloop"
        or receipt.operation != "evaluation_verdict"
        or receipt.http_method != "GET"
        or receipt.read_only is not True
        or receipt.response_status is None
        or not 200 <= receipt.response_status < 300
        or receipt.response_hash != _digest(raw)
        or not required_matches.issubset(receipt.matched_fields)
    ):
        raise SkillOpsError("AgentLoop readback lacks verified native provenance")
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SkillOpsError("AgentLoop verdict readback must be exact JSON") from error
    expected = {
        "schema_version": "testweaver.agentloop-verdict/v1",
        "dataset_ref": dataset_ref,
        "dataset_hash": dataset_hash,
        "evaluation_ref": evaluation_ref,
        "evaluation_hash": evaluation_hash,
    }
    if (
        not isinstance(result, dict)
        or set(result)
        != {
            *expected,
            "verdict",
            "authority_scope",
        }
        or result.get("verdict") not in {"PASS", "FAIL", "BLOCKED"}
        or any(result.get(key) != value for key, value in expected.items())
        or result.get("authority_scope") != receipt.correlation.as_dict()
    ):
        raise SkillOpsError("AgentLoop verdict is not bound to the frozen evaluation")
    for value, field in (
        (dataset_ref, "dataset_ref"),
        (evaluation_ref, "evaluation_ref"),
    ):
        _state_ref(value, field)
    for value, field in (
        (dataset_hash, "dataset_hash"),
        (evaluation_hash, "evaluation_hash"),
    ):
        _state_hash(value, field)
    return _external_readback(
        source="agentloop",
        ref=f"{receipt.endpoint}{receipt.path}",
        raw=raw,
        classification="AUTHORITY_RECEIPT",
        claims=tuple(
            sorted(
                {
                    **receipt.correlation.as_dict(),
                    "endpoint": receipt.endpoint,
                    "operation": receipt.operation,
                    "dataset_ref": dataset_ref,
                    "dataset_hash": dataset_hash,
                    "evaluation_ref": evaluation_ref,
                    "evaluation_hash": evaluation_hash,
                    "verdict": str(result["verdict"]),
                }.items()
            )
        ),
        verified=True,
    )


def verify_skill_operation_receipt(
    entry: SideEffectEntry,
    *,
    raw: bytes,
    receipt: SkillReceipt,
    proposal: SkillProposal,
) -> SkillOperationVerification:
    """Turn an observed AgentTeams write receipt into an exact close proof."""

    if not isinstance(entry, SideEffectEntry):
        raise SkillOpsError("AgentTeams side-effect receipt is required")
    if not isinstance(receipt, SkillReceipt) or not isinstance(proposal, SkillProposal):
        raise SkillOpsError("pending Skill receipt and proposal are required")
    try:
        entry.validate()
    except Exception as error:
        raise SkillOpsError("AgentTeams side-effect receipt is invalid") from error
    expected_operation = (
        "skill.promote" if receipt.action == "PROMOTE" else "skill.rollback"
    )
    if (
        entry.operation != expected_operation
        or entry.tool_ref != "official-agentspec-agt"
        or entry.target_ref != proposal.proposal_id
        or entry.decision != "allow"
        or entry.effect not in {"write", "external"}
        or entry.fencing != "passed"
        or entry.observed is not True
        or entry.provenance != "agentteams-native"
        or entry.result_hash != _digest(raw)
    ):
        raise SkillOpsError("AgentTeams receipt does not prove the requested operation")

    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SkillOpsError("Skill operation readback must be exact JSON") from error
    expected_fields = {
        "schema_version",
        "status",
        "operation_ref",
        "action",
        "active_version",
        "proposal_ref",
        "proposal_hash",
        "receipt_ref",
        "receipt_hash",
        "content_hash",
        "verified_at",
        "authority_scope",
    }
    if not isinstance(result, dict) or set(result) != expected_fields:
        raise SkillOpsError("Skill operation readback has an unsupported shape")
    scope = result.get("authority_scope")
    expected_result = {
        "schema_version": "testweaver.skill-operation-result/v1",
        "status": "APPLIED",
        "operation_ref": entry.call_ref,
        "action": receipt.action,
        "active_version": receipt.active_version,
        "proposal_ref": proposal.proposal_id,
        "proposal_hash": proposal.record_hash,
        "receipt_ref": receipt.receipt_id,
        "receipt_hash": receipt.record_hash,
        "content_hash": proposal.content_hash,
    }
    if any(result.get(key) != value for key, value in expected_result.items()):
        raise SkillOpsError("Skill operation result does not match pending close")
    if (
        not isinstance(scope, dict)
        or scope.get("campaign_id") != entry.campaign_id
        or scope.get("run_id") != entry.run_id
        or scope.get("trace_id") != entry.trace_id
        or set(scope) != {
            "campaign_id",
            "run_id",
            "trace_id",
            "pg_revision",
            "content_hash",
        }
    ):
        raise SkillOpsError("Skill operation result crosses the authority boundary")
    _state_ref(scope["pg_revision"], "authority_scope.pg_revision")
    _state_hash(scope["content_hash"], "authority_scope.content_hash")

    claims = {
        "action": receipt.action,
        "active_version": receipt.active_version,
        "content_hash": proposal.content_hash,
        "proposal_ref": proposal.proposal_id,
        "proposal_hash": proposal.record_hash,
        "receipt_ref": receipt.receipt_id,
        "receipt_hash": receipt.record_hash,
        "campaign_id": str(scope["campaign_id"]),
        "run_id": str(scope["run_id"]),
        "trace_id": str(scope["trace_id"]),
        "pg_revision": str(scope["pg_revision"]),
        "authority_content_hash": str(scope["content_hash"]),
    }
    token = _external_readback(
        source="agentteams",
        ref=entry.call_ref,
        raw=raw,
        classification="AUTHORITY_RECEIPT",
        claims=tuple(sorted(claims.items())),
        verified=True,
    )
    return SkillOperationVerification.create(
        verification_ref=f"skillops-close:{entry.entry_id}",
        operation_ref=entry.call_ref,
        operation_hash=token.raw_hash,
        receipt_ref=receipt.receipt_id,
        receipt_hash=receipt.record_hash,
        proposal_ref=proposal.proposal_id,
        proposal_hash=proposal.record_hash,
        run_id=entry.run_id,
        action=receipt.action,
        active_version=receipt.active_version,
        content_hash=proposal.content_hash,
        verified_at=result["verified_at"],
        verified_readback=token,
    )


__all__ = [
    "agentloop_readback_from_observability",
    "matrix_readback_from_authority",
    "verify_skill_operation_receipt",
]
