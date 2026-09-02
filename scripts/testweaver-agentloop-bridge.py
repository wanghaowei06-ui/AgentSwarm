#!/usr/bin/env python3
"""Project one sealed native provider turn into a bounded AgentLoop receipt.

The input is a hash-sealed, externally attested export from a Hero collector.
This command has no AgentTeams control-plane API and exposes no create/update
operation.  It emits one OTLP GenAI span, reads the resulting XTrace at most
three times, and optionally reads an existing AgentLoop evaluation task.  All
receipts are hash-only and ``PROJECTED_LIVE_TRACE`` is deliberately distinct
from native instrumentation.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import stat
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from testweaver.authority import digest_bytes, validate_ref
from testweaver.contracts.validator import canonical_hash
from testweaver.integrations.agentloop_client import (
    AgentLoopClient,
    AgentLoopCredentialLease,
    AgentLoopEndpoint,
    AgentLoopQueryVerification,
    AgentLoopScope,
)
from testweaver.integrations.tea_transport import (
    TeaAgentLoopTransport,
    load_protected_csv_credential,
)
from testweaver.integrations.xtrace_readback import (
    XTraceCorrelation,
    XTraceReadbackClient,
    TeaXTraceTransport,
)
from testweaver.observability.otlp_genai import (
    EvidenceRef,
    GenAIContext,
    OtlpReceipt,
    OtlpTransport,
    emit_genai_span,
    load_loongsuite_otlp_binding,
)
from testweaver.observability.readonly_query import Correlation


_SCHEMA_VERSION = "testweaver.provider-turn/v1"
_RECEIPT_SCHEMA = "testweaver.agentloop-bridge-receipt/v1"
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_MAX_INPUT_BYTES = 1024 * 1024
_MAX_RECEIPT_BYTES = 256 * 1024

_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "campaign_id",
        "run_id",
        "trace_id",
        "pg_revision",
        "content_hash",
        "agent",
        "task",
        "skill",
        "provider",
        "model",
        "usage",
        "latency_ms",
        "source_ref",
        "source_hash",
        "attestation_ref",
        "attestation_hash",
        "record_hash",
        "synthetic",
    }
)
_AGENT_FIELDS = frozenset({"id"})
_TASK_FIELDS = frozenset({"id"})
_SKILL_FIELDS = frozenset({"name", "version", "hash", "invoke_ref"})
_USAGE_FIELDS = frozenset({"input_tokens", "output_tokens", "total_tokens"})
_SELF_CLAIM_FIELDS = frozenset({"classification", "live_claim", "native_live_claim"})


class BridgeInputError(ValueError):
    """A stable, non-content error category for an untrusted collector export."""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


@dataclass(frozen=True, slots=True)
class ProviderTurn:
    campaign_id: str
    run_id: str
    trace_id: str
    pg_revision: int
    content_hash: str
    agent_id: str
    task_id: str
    skill_name: str
    skill_version: str
    skill_hash: str
    skill_invoke_ref: str
    provider: str
    model: str
    usage: dict[str, int]
    latency_ms: float
    source_ref: str
    source_hash: str
    attestation_ref: str
    attestation_hash: str
    record_hash: str

    def context(self) -> GenAIContext:
        return GenAIContext(
            correlation=Correlation(
                self.campaign_id,
                self.run_id,
                str(self.pg_revision),
                self.content_hash,
            ),
            agent_id=self.agent_id,
            task_id=self.task_id,
            skill=self.skill_name,
            skill_version=self.skill_version,
            provider=self.provider,
            model=self.model,
            evidence_refs=(
                EvidenceRef(self.source_ref, self.source_hash),
                EvidenceRef(self.skill_invoke_ref, self.skill_hash),
                EvidenceRef(self.attestation_ref, self.attestation_hash),
            ),
            usage=self.usage,
            latency_ms=self.latency_ms,
            observation_kind="attested_provider_turn_projection",
        )


def parse_provider_turn(raw_bytes: bytes) -> ProviderTurn:
    """Parse and validate one strict, hash-sealed collector document."""

    if not isinstance(raw_bytes, bytes) or not raw_bytes:
        raise BridgeInputError("INPUT_INVALID")
    if len(raw_bytes) > _MAX_INPUT_BYTES:
        raise BridgeInputError("INPUT_TOO_LARGE")
    try:
        value = json.loads(raw_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise BridgeInputError("INPUT_INVALID") from None
    if not isinstance(value, dict):
        raise BridgeInputError("INPUT_INVALID")
    if _SELF_CLAIM_FIELDS & set(value):
        raise BridgeInputError("CALLER_LIVE_CLAIM_REJECTED")
    if set(value) - _TOP_LEVEL_FIELDS:
        raise BridgeInputError("UNSUPPORTED_FIELD")

    anchors = {
        "campaign_id",
        "run_id",
        "trace_id",
        "pg_revision",
        "content_hash",
        "agent",
        "task",
        "skill",
        "provider",
        "model",
        "usage",
        "latency_ms",
        "source_ref",
        "source_hash",
        "attestation_ref",
        "attestation_hash",
        "record_hash",
    }
    if not anchors.issubset(value):
        raise BridgeInputError("MISSING_ANCHOR")
    if value.get("schema_version") != _SCHEMA_VERSION:
        raise BridgeInputError("SCHEMA_INVALID")
    if value.get("synthetic", False) is not False:
        raise BridgeInputError("SYNTHETIC_INPUT")

    for field in ("campaign_id", "run_id", "provider", "model", "source_ref", "attestation_ref"):
        try:
            validate_ref(value[field], field)
        except Exception:
            raise BridgeInputError("ANCHOR_FORMAT_INVALID") from None
    if not isinstance(value["trace_id"], str) or not _TRACE_ID.fullmatch(value["trace_id"]):
        raise BridgeInputError("ANCHOR_FORMAT_INVALID")
    if (
        isinstance(value["pg_revision"], bool)
        or not isinstance(value["pg_revision"], int)
        or value["pg_revision"] < 1
    ):
        raise BridgeInputError("ANCHOR_FORMAT_INVALID")
    if not isinstance(value["content_hash"], str) or not _HASH.fullmatch(value["content_hash"]):
        raise BridgeInputError("ANCHOR_FORMAT_INVALID")
    for field in ("source_hash", "attestation_hash"):
        if not isinstance(value[field], str) or not _HASH.fullmatch(value[field]):
            raise BridgeInputError("ATTESTATION_INVALID")

    agent = value["agent"]
    task = value["task"]
    skill = value["skill"]
    if not isinstance(agent, Mapping) or set(agent) != _AGENT_FIELDS:
        raise BridgeInputError("ANCHOR_FORMAT_INVALID")
    if not isinstance(task, Mapping) or set(task) != _TASK_FIELDS:
        raise BridgeInputError("ANCHOR_FORMAT_INVALID")
    if not isinstance(skill, Mapping) or set(skill) != _SKILL_FIELDS:
        raise BridgeInputError("ANCHOR_FORMAT_INVALID")
    try:
        agent_id = validate_ref(agent["id"], "agent.id")
        task_id = validate_ref(task["id"], "task.id")
        skill_name = validate_ref(skill["name"], "skill.name")
        skill_version = validate_ref(skill["version"], "skill.version")
        skill_invoke_ref = validate_ref(skill["invoke_ref"], "skill.invoke_ref")
    except Exception:
        raise BridgeInputError("ANCHOR_FORMAT_INVALID") from None
    if not isinstance(skill["hash"], str) or not _HASH.fullmatch(skill["hash"]):
        raise BridgeInputError("ANCHOR_FORMAT_INVALID")

    usage = value["usage"]
    if not isinstance(usage, Mapping) or not usage or set(usage) - _USAGE_FIELDS:
        raise BridgeInputError("USAGE_INVALID")
    for number in usage.values():
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise BridgeInputError("USAGE_INVALID")
    latency = value["latency_ms"]
    if (
        isinstance(latency, bool)
        or not isinstance(latency, (int, float))
        or not math.isfinite(float(latency))
        or latency < 0
    ):
        raise BridgeInputError("LATENCY_INVALID")

    expected_record_hash = canonical_hash(
        {key: child for key, child in value.items() if key != "record_hash"}
    )
    if value["record_hash"] != expected_record_hash:
        raise BridgeInputError("RECORD_NOT_SEALED")
    return ProviderTurn(
        campaign_id=value["campaign_id"],
        run_id=value["run_id"],
        trace_id=value["trace_id"],
        pg_revision=value["pg_revision"],
        content_hash=value["content_hash"],
        agent_id=agent_id,
        task_id=task_id,
        skill_name=skill_name,
        skill_version=skill_version,
        skill_hash=skill["hash"],
        skill_invoke_ref=skill_invoke_ref,
        provider=value["provider"],
        model=value["model"],
        usage={str(key): number for key, number in usage.items()},
        latency_ms=float(latency),
        source_ref=value["source_ref"],
        source_hash=value["source_hash"],
        attestation_ref=value["attestation_ref"],
        attestation_hash=value["attestation_hash"],
        record_hash=value["record_hash"],
    )


def _hash_text(value: str) -> str:
    return digest_bytes(value.encode("utf-8"))


def _hash_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and _HASH.fullmatch(value) else None


def _input_metadata(turn: ProviderTurn) -> dict[str, object]:
    return {
        "record_hash": turn.record_hash,
        "source_hash": turn.source_hash,
        "source_ref_hash": _hash_text(turn.source_ref),
        "attestation_hash": turn.attestation_hash,
        "attestation_ref_hash": _hash_text(turn.attestation_ref),
        "campaign_id_hash": _hash_text(turn.campaign_id),
        "run_id_hash": _hash_text(turn.run_id),
        "trace_id_hash": _hash_text(turn.trace_id),
        "pg_revision_hash": _hash_text(str(turn.pg_revision)),
        "agent_id_hash": _hash_text(turn.agent_id),
        "task_id_hash": _hash_text(turn.task_id),
        "skill_name_hash": _hash_text(turn.skill_name),
        "skill_version_hash": _hash_text(turn.skill_version),
        "skill_hash": turn.skill_hash,
        "skill_invoke_ref_hash": _hash_text(turn.skill_invoke_ref),
        "provider_hash": _hash_text(turn.provider),
        "model_hash": _hash_text(turn.model),
        "usage_hash": canonical_hash(turn.usage),
        "latency_ms": turn.latency_ms,
    }


def _safe_otlp(receipt: OtlpReceipt) -> dict[str, object]:
    return {
        "status": receipt.status,
        "endpoint_hash": _hash_text(receipt.endpoint),
        "http_method": receipt.http_method,
        "response_status": receipt.response_status,
        "response_hash": receipt.response_hash,
        "response_bytes": receipt.response_bytes,
        "request_hash": receipt.request_hash,
        "trace_id_hash": _hash_text(receipt.trace_id),
        "span_id_hash": _hash_text(receipt.span_id),
        "reason": receipt.reason,
    }


def _safe_xtrace(receipt: object) -> dict[str, object]:
    anchors = getattr(receipt, "authority_anchor_matches", {})
    if not isinstance(anchors, Mapping):
        anchors = {}
    status = getattr(receipt, "status", "BLOCKED")
    if status not in {"API_QUERY_VERIFIED", "NOT_VERIFIED", "BLOCKED"}:
        status = "BLOCKED"
    reason = getattr(receipt, "reason", None)
    if reason not in {
        None,
        "TRACE_OR_AUTHORITY_ANCHORS_NOT_OBSERVED",
        "CREDENTIAL_UNAVAILABLE",
        "ENDPOINT_UNAVAILABLE",
        "PERMISSION_DENIED",
        "API_REJECTED",
        "ELAPSED_BUDGET_EXHAUSTED",
    }:
        reason = "XTRACE_RESULT_INVALID"
    attempt_count = getattr(receipt, "attempt_count", 0)
    if isinstance(attempt_count, bool) or not isinstance(attempt_count, int):
        attempt_count = 0
    response_status = getattr(receipt, "response_status", None)
    if isinstance(response_status, bool) or not isinstance(response_status, int):
        response_status = None
    span_count = getattr(receipt, "span_count", 0)
    if isinstance(span_count, bool) or not isinstance(span_count, int) or span_count < 0:
        span_count = 0
    return {
        "status": status,
        "attempt_count": attempt_count,
        "response_status": response_status,
        "response_hash": _hash_or_none(getattr(receipt, "response_hash", None)),
        "request_id_hash": _hash_or_none(getattr(receipt, "request_id_hash", None)),
        "trace_id_hash": _hash_or_none(getattr(receipt, "trace_id_hash", None)),
        "span_count": span_count,
        "trace_id_matched": bool(getattr(receipt, "trace_id_matched", False)),
        "authority_anchor_matches": {
            field: bool(anchors.get(field, False))
            for field in ("campaign_id", "run_id", "pg_revision", "content_hash")
        },
        "receipt_hash": _hash_or_none(getattr(receipt, "content_hash", None)),
        "reason": reason,
    }


def _safe_agentloop(result: AgentLoopQueryVerification) -> dict[str, object]:
    return {
        "status": result.status,
        "task_receipt_hash": result.task_receipt_hash,
        "runs_receipt_hash": result.runs_receipt_hash,
        "ownership_verified": bool(result.ownership_verified),
        "scope_verified": bool(result.scope_verified),
        "terminal": bool(result.terminal),
        "result_count": result.result_count,
        "successful_result_count": result.successful_result_count,
        "receipt_hash": result.content_hash,
    }


def _seal_receipt(values: Mapping[str, object]) -> dict[str, object]:
    result = dict(values)
    result["receipt_hash"] = canonical_hash(result)
    return result


def _blocked_input(raw_bytes: bytes, reason: str) -> dict[str, object]:
    return _seal_receipt(
        {
            "schema_version": _RECEIPT_SCHEMA,
            "classification": "BLOCKED",
            "live_claim": False,
            "reason": reason,
            "input_hash": digest_bytes(raw_bytes),
        }
    )


def project_provider_turn(
    raw_bytes: bytes,
    *,
    otlp_endpoint: str | None,
    otlp_header_provider: Callable[[], Mapping[str, str]] | None = None,
    otlp_transport: OtlpTransport | None = None,
    xtrace_client: object | None = None,
    agentloop_query: Callable[[ProviderTurn], AgentLoopQueryVerification] | None = None,
    clock: Callable[[], str] | None = None,
) -> dict[str, object]:
    """Project one validated turn without mutating AgentTeams or AgentLoop."""

    try:
        turn = parse_provider_turn(raw_bytes)
    except BridgeInputError as error:
        return _blocked_input(raw_bytes, error.category)
    if otlp_endpoint is None:
        return _seal_receipt(
            {
                "schema_version": _RECEIPT_SCHEMA,
                "classification": "BLOCKED",
                "live_claim": False,
                "reason": "OTLP_CONFIG_UNAVAILABLE",
                "input": _input_metadata(turn),
            }
        )

    now = clock or (lambda: datetime.now(timezone.utc).isoformat())
    try:
        otlp = emit_genai_span(
            endpoint=otlp_endpoint,
            context=turn.context(),
            trace_id=turn.trace_id,
            header_provider=otlp_header_provider,
            transport=otlp_transport,
        )
    except Exception:
        return _seal_receipt(
            {
                "schema_version": _RECEIPT_SCHEMA,
                "classification": "BLOCKED",
                "live_claim": False,
                "reason": "OTLP_EXPORT_FAILED",
                "input": _input_metadata(turn),
            }
        )
    receipt: dict[str, object] = {
        "schema_version": _RECEIPT_SCHEMA,
        "classification": "BLOCKED",
        "live_claim": False,
        "reason": None,
        "input": _input_metadata(turn),
        "otlp": _safe_otlp(otlp),
        "xtrace": None,
        "agentloop": None,
        "observed_at_hash": _hash_text(now()),
    }
    if otlp.status != "EXPORT_ACCEPTED":
        receipt["reason"] = "OTLP_EXPORT_FAILED"
        return _seal_receipt(receipt)
    if xtrace_client is None:
        receipt["reason"] = "XTRACE_CONFIG_UNAVAILABLE"
        return _seal_receipt(receipt)

    try:
        xtrace = xtrace_client.get_trace(
            trace_id=turn.trace_id,
            correlation=XTraceCorrelation(
                campaign_id=turn.campaign_id,
                run_id=turn.run_id,
                pg_revision=turn.pg_revision,
                content_hash=turn.content_hash,
            ),
            max_attempts=3,
            max_elapsed_seconds=90.0,
        )
    except Exception:
        receipt["reason"] = "XTRACE_QUERY_BLOCKED"
        return _seal_receipt(receipt)
    safe_xtrace = _safe_xtrace(xtrace)
    receipt["xtrace"] = safe_xtrace
    xtrace_anchors = safe_xtrace["authority_anchor_matches"]
    xtrace_verified = (
        safe_xtrace["status"] == "API_QUERY_VERIFIED"
        and safe_xtrace["trace_id_matched"]
        and safe_xtrace["trace_id_hash"] == _hash_text(turn.trace_id)
        and isinstance(xtrace_anchors, Mapping)
        and all(xtrace_anchors.values())
    )
    if not xtrace_verified:
        receipt["classification"] = (
            "BLOCKED"
            if safe_xtrace["status"] == "BLOCKED"
            else "NOT_VERIFIED"
        )
        receipt["reason"] = (
            "XTRACE_QUERY_BLOCKED"
            if safe_xtrace["status"] == "BLOCKED"
            else "XTRACE_NOT_VERIFIED"
        )
        return _seal_receipt(receipt)

    if agentloop_query is not None:
        try:
            agentloop = agentloop_query(turn)
            if not isinstance(agentloop, AgentLoopQueryVerification):
                raise TypeError
        except Exception:
            receipt["reason"] = "AGENTLOOP_QUERY_BLOCKED"
            return _seal_receipt(receipt)
        receipt["agentloop"] = _safe_agentloop(agentloop)
        agentloop_verified = (
            agentloop.status == "API_QUERY_VERIFIED"
            and agentloop.ownership_verified
            and agentloop.scope_verified
            and agentloop.terminal
            and agentloop.result_count > 0
            and agentloop.successful_result_count > 0
        )
        if not agentloop_verified:
            receipt["classification"] = (
                "BLOCKED" if agentloop.status == "BLOCKED" else "NOT_VERIFIED"
            )
            receipt["reason"] = (
                "AGENTLOOP_QUERY_BLOCKED"
                if agentloop.status == "BLOCKED"
                else "AGENTLOOP_NOT_VERIFIED"
            )
            return _seal_receipt(receipt)

    receipt["classification"] = "PROJECTED_LIVE_TRACE"
    receipt["reason"] = None
    return _seal_receipt(receipt)


def _read_input(path: Path) -> bytes:
    if str(path) == "-":
        raw = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
        if len(raw) > _MAX_INPUT_BYTES:
            raise BridgeInputError("INPUT_TOO_LARGE")
        return raw
    if not path.is_absolute():
        raise BridgeInputError("INPUT_PATH_INVALID")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_INPUT_BYTES:
            raise BridgeInputError("INPUT_PATH_INVALID")
        raw = os.read(descriptor, _MAX_INPUT_BYTES + 1)
    except BridgeInputError:
        raise
    except OSError:
        raise BridgeInputError("INPUT_UNAVAILABLE") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(raw) > _MAX_INPUT_BYTES:
        raise BridgeInputError("INPUT_TOO_LARGE")
    return raw


def _credential_callback(path: Path) -> Callable[[], AgentLoopCredentialLease]:
    def load() -> AgentLoopCredentialLease:
        credential = load_protected_csv_credential(path)
        return AgentLoopCredentialLease(str(path), credential)

    return load


def _agentloop_query_callback(args: argparse.Namespace) -> Callable[[ProviderTurn], AgentLoopQueryVerification] | None:
    values = (
        args.agentloop_endpoint,
        args.agentloop_agent_space,
        args.agentloop_region,
        args.agentloop_task_id,
    )
    if not any(values):
        return None
    if not all(values) or args.credential_ref is None:
        def unavailable(_turn: ProviderTurn) -> AgentLoopQueryVerification:
            raise BridgeInputError("AGENTLOOP_CONFIG_UNAVAILABLE")

        return unavailable

    credential = _credential_callback(args.credential_ref)
    client = AgentLoopClient(
        AgentLoopEndpoint(args.agentloop_endpoint, args.agentloop_agent_space),
        TeaAgentLoopTransport(args.agentloop_region),
        credential,
        lambda: datetime.now(timezone.utc).isoformat(),
    )

    def query(turn: ProviderTurn) -> AgentLoopQueryVerification:
        return client.verify_evaluation_task_run(
            AgentLoopScope(turn.campaign_id, turn.run_id, turn.pg_revision),
            task_id=args.agentloop_task_id,
        )

    return query


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Project one sealed Hero provider turn; no AgentTeams mutations"
    )
    parser.add_argument("--input", type=Path, required=True, help="absolute JSON path or -")
    parser.add_argument(
        "--loongsuite-config",
        type=Path,
        default=Path("/root/.loongsuite-pilot/config.json"),
        help="owner-only LoongSuite config containing the protected OTLP endpoint",
    )
    parser.add_argument("--xtrace-region", default=None)
    parser.add_argument(
        "--credential-ref",
        type=Path,
        default=None,
        help="protected AccessKey CSV path; values are loaded only in memory",
    )
    parser.add_argument("--agentloop-endpoint", default=None)
    parser.add_argument("--agentloop-agent-space", default=None)
    parser.add_argument("--agentloop-region", default=None)
    parser.add_argument("--agentloop-task-id", default=None)
    parser.add_argument("--receipt", type=Path, default=None)
    return parser.parse_args()


def _write_receipt(path: Path, value: Mapping[str, object]) -> None:
    if not path.is_absolute():
        raise BridgeInputError("RECEIPT_PATH_INVALID")
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if len(encoded) > _MAX_RECEIPT_BYTES:
        raise BridgeInputError("RECEIPT_TOO_LARGE")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
        descriptor = -1
        os.replace(temporary, path)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def run() -> int:
    args = _args()
    try:
        raw = _read_input(args.input)
    except BridgeInputError as error:
        receipt = _blocked_input(b"", error.category)
    else:
        endpoint: str | None = None
        headers: Callable[[], Mapping[str, str]] | None = None
        try:
            binding = load_loongsuite_otlp_binding(args.loongsuite_config)
            endpoint = binding.endpoint
            headers = binding.headers
        except Exception:
            pass
        xtrace_client = None
        if args.xtrace_region and args.credential_ref is not None:
            try:
                credentials = _credential_callback(args.credential_ref)
                xtrace_client = XTraceReadbackClient(
                    args.xtrace_region,
                    TeaXTraceTransport(),
                    credentials,
                    lambda: datetime.now(timezone.utc).isoformat(),
                )
            except Exception:
                xtrace_client = None
        receipt = project_provider_turn(
            raw,
            otlp_endpoint=endpoint,
            otlp_header_provider=headers,
            xtrace_client=xtrace_client,
            agentloop_query=_agentloop_query_callback(args),
        )
    if args.receipt is not None:
        _write_receipt(args.receipt, receipt)
    sys.stdout.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
    return 0 if receipt["classification"] == "PROJECTED_LIVE_TRACE" else 1


if __name__ == "__main__":
    raise SystemExit(run())
