"""One-shot, non-LIVE OTLP/SLS readiness receipt.

This command is intentionally outside AgentTeams execution.  It may send one
OTLP-shaped readiness probe to an already-running Collector, but it never
claims a Hero run and it never creates or updates an AgentLoop resource.
SLS credentials, when supplied by a caller, must come from a protected
runtime callback; they are not accepted as command-line arguments.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .otlp_genai import EvidenceRef, GenAIContext, emit_genai_span
from .readonly_query import Correlation, ProtectedConfigRef
from .sls_query import SlsBinding, SlsReadOnlyQueryClient, load_sls_binding


_PROBE_HASH = "sha256:" + hashlib.sha256(b"testweaver-observability-readiness-probe").hexdigest()


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one non-LIVE observability readiness probe")
    parser.add_argument(
        "--collector-endpoint",
        default="http://127.0.0.1:54318/v1/traces",
        help="existing local OTLP/HTTP Collector endpoint",
    )
    parser.add_argument(
        "--loongsuite-config",
        default="/root/.loongsuite-pilot/config.json",
        type=Path,
    )
    parser.add_argument("--agent-space", default=None)
    parser.add_argument("--sls-credential-ref", type=Path, default=None)
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("testweaver/observability/agentloop-readiness-receipt.json"),
    )
    return parser.parse_args()


def _sls_preflight(config_path: Path, agent_space: str | None, credential_ref: Path | None) -> dict[str, object]:
    try:
        binding = load_sls_binding(config_path, agent_space=agent_space)
    except Exception as error:
        kind = "sls_binding_shape_invalid"
        if "host does not match project" in str(error):
            kind = "sls_endpoint_project_mismatch"
        elif "config" in str(error).lower() and "section" in str(error).lower():
            kind = "sls_binding_missing"
        return {
            "status": "BLOCKED",
            "reason": kind,
            "read_only": True,
            "live_claim": False,
        }
    ref = (
        ProtectedConfigRef(
            path=credential_ref,
            variable_names=("ALIBABA_CLOUD_ACCESS_KEY_ID", "ALIBABA_CLOUD_ACCESS_KEY_SECRET"),
        )
        if credential_ref is not None
        else None
    )
    client = SlsReadOnlyQueryClient(binding=binding, credential_ref=ref)
    return client.preflight()


def run() -> int:
    args = _args()
    correlation = Correlation(
        campaign_id="observability-readiness",
        run_id="observability-readiness",
        pg_revision="static-readiness",
        content_hash=_PROBE_HASH,
    )
    context = GenAIContext(
        correlation=correlation,
        agent_id="observability-probe",
        task_id="readiness-probe",
        skill="otel-genai-readiness",
        skill_version="source",
        provider="not-a-provider-call",
        model="not-a-model-call",
        evidence_refs=(EvidenceRef("observability/readiness-probe", _PROBE_HASH),),
        observation_kind="readiness_probe",
    )
    otlp = emit_genai_span(endpoint=args.collector_endpoint, context=context)
    sls = _sls_preflight(args.loongsuite_config, args.agent_space, args.sls_credential_ref)
    receipt = {
        "schema_version": "testweaver.agentloop-readiness-receipt/v1",
        "classification": "BLOCKED" if sls.get("status") == "BLOCKED" else "NOT_LIVE_PROBE",
        "live_claim": False,
        "source_kind": "bounded_readiness_probe",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "collector": otlp.as_dict(),
        "agentspace_sls": sls,
        "scope": {
            "read_only_queries_only": True,
            "agentteams_control": False,
            "model_or_provider_call": False,
            "synthetic_not_live": True,
            "config_paths": {
                "loongsuite": str(args.loongsuite_config),
                "sls_credential_ref": str(args.sls_credential_ref) if args.sls_credential_ref else None,
            },
        },
    }
    _write_json(args.receipt, receipt)
    return 0 if otlp.status == "EXPORT_ACCEPTED" and sls.get("status") != "BLOCKED" else 1


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=False)
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    raise SystemExit(run())
