#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf '%s\n' 'usage: m2b-preflight.sh --config PATH --dry-run' >&2
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_PATH=''
DRY_RUN=false
while (($# > 0)); do
  case "$1" in
    --config)
      if (($# < 2)) || [[ "$2" == -* ]]; then
        usage
        exit 2
      fi
      CONFIG_PATH="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$CONFIG_PATH" || "$DRY_RUN" != true ]]; then
  printf '%s\n' 'M2B_PREFLIGHT_REQUIRES_DRY_RUN' >&2
  usage
  exit 2
fi

if [[ ! -f "$CONFIG_PATH" || ! -r "$CONFIG_PATH" ]]; then
  printf '%s\n' 'M2B_PREFLIGHT_CONFIG_UNREADABLE' >&2
  exit 2
fi

CONFIG_REALPATH="$(realpath -e -- "$CONFIG_PATH" 2>/dev/null || true)"
case "$CONFIG_REALPATH" in
  "$SCRIPT_DIR"/*) ;;
  *)
    printf '%s\n' 'M2B_PREFLIGHT_CONFIG_OUTSIDE_CONTRACT_DIR' >&2
    exit 2
    ;;
esac

exec python3 - "$CONFIG_REALPATH" <<'PY'
import json
import sys
from pathlib import Path


def fail(field, reason):
    print(f"M2B_PREFLIGHT_INVALID field={field} reason={reason}", file=sys.stderr)
    raise SystemExit(1)


def obj(parent, key):
    if not isinstance(parent, dict) or key not in parent:
        fail(key, "missing")
    value = parent[key]
    if not isinstance(value, dict):
        fail(key, "object_required")
    return value


def list_value(parent, key):
    if not isinstance(parent, dict) or key not in parent:
        fail(key, "missing")
    value = parent[key]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        fail(key, "string_list_required")
    return value


def exact(parent, key, expected):
    if not isinstance(parent, dict) or parent.get(key) != expected:
        fail(key, "unexpected")


def ref(parent, key, prefix):
    value = parent.get(key) if isinstance(parent, dict) else None
    if not isinstance(value, str) or not value.startswith(prefix) or len(value) <= len(prefix):
        fail(key, "opaque_reference_required")
    return value


config_path = Path(sys.argv[1])
try:
    with config_path.open(encoding="utf-8") as handle:
        config = json.load(handle)
except (OSError, ValueError):
    fail("contract", "json_unreadable")

if not isinstance(config, dict):
    fail("contract", "object_required")

required_top = {
    "schema_version",
    "contract_version",
    "control_baseline",
    "scope",
    "native_chain",
    "human_gate",
    "recovery",
    "oracles",
    "receipt",
    "allowed_script_operations",
    "forbidden_script_operations",
    "known_gaps",
}
if set(config) != required_top:
    fail("top_level", "contract_fields_mismatch")

exact(config, "schema_version", "testweaver.m2b.runner/v1")
exact(config, "contract_version", 1)

baseline = obj(config, "control_baseline")
exact(baseline, "document_commit", "eb0364d")
exact(baseline, "binding", "unbound-template")
if "case_binding" not in baseline or baseline["case_binding"] is not None:
    fail("control_baseline.case_binding", "must_be_unbound")

scope = obj(config, "scope")
exact(scope, "mode", "preflight-only")
for scope_key in (
    "live_run_allowed",
    "runtime_mutation",
    "package_mutation",
    "model_invocations",
    "human_input",
):
    if scope.get(scope_key) is not False:
        fail(f"scope.{scope_key}", "must_be_false")

chain = obj(config, "native_chain")
identity_refs = []
for member, role in (
    ("manager", "manager"),
    ("leader", "team_leader"),
    ("worker", "worker"),
):
    member_obj = obj(chain, member)
    exact(member_obj, "role", role)
    identity_refs.append(ref(member_obj, "identity_ref", "native-ref://"))
if len(set(identity_refs)) != 3:
    fail("native_chain.identity_ref", "identities_must_be_distinct")
if set(list_value(chain, "required_tools")) != {"roomflow", "projectflow", "taskflow"}:
    fail("native_chain.required_tools", "native_tools_mismatch")
required_edges = set(list_value(chain, "required_edges"))
for edge in (
    "manager_selects_team_and_leader",
    "leader_creates_project_and_delegates_task",
    "worker_acknowledges_and_submits",
    "leader_checks_and_accepts",
    "leader_handoffs_to_manager",
    "manager_makes_followup_decision",
):
    if edge not in required_edges:
        fail("native_chain.required_edges", "chain_edge_missing")

human = obj(config, "human_gate")
ref(human, "actor_ref", "human-ref://")
exact(human, "transport", "matrix")
exact(human, "decision", "external-manual")
exact(human, "auto_resume", False)
exact(human, "agent_auto_approval", False)
exact(human, "same_model_request_and_approval", False)

recovery = obj(config, "recovery")
fault = obj(recovery, "fault")
exact(fault, "kind", "worker-process-or-container")
exact(fault, "source", "external-approved-lifecycle-operation")
exact(fault, "real_only", True)
exact(fault, "event_injection", False)
exact(fault, "repeat_count", 1)
native_sequence = set(list_value(recovery, "native_sequence"))
for step in (
    "observe_task_before_fault",
    "observe_runtime_generation_before_fault",
    "observe_native_fault",
    "observe_controller_runtime_recovery",
    "observe_task_and_project_after_recovery",
    "leader_replans_or_redelegates",
):
    if step not in native_sequence:
        fail("recovery.native_sequence", "recovery_step_missing")
generation = obj(recovery, "generation")
exact(generation, "required", True)
if set(list_value(generation, "evidence_sources")) != {
    "controller.metadata.generation",
    "controller.status.observedGeneration",
    "runtime.metadata.generation",
}:
    fail("recovery.generation.evidence_sources", "generation_sources_mismatch")
exact(generation, "task_fencing", "not_available_in_current_teamharness")
exact(recovery, "late_result_rule", "old_task_result_is_input_only")

oracles = obj(config, "oracles")
ref(oracles, "same_evidence_root_ref", "run-evidence-ref://")
oracle_identity_refs = []
oracle_process_refs = []
for oracle_name in ("outcome", "boundary"):
    oracle = obj(oracles, oracle_name)
    oracle_identity_refs.append(ref(oracle, "identity_ref", "oracle-agent-ref://"))
    oracle_process_refs.append(ref(oracle, "process_ref", "oracle-process-ref://"))
    ref(oracle, "source_ref", "evidence-source-ref://")
    exact(oracle, "read_only", True)
if oracle_identity_refs[0] == oracle_identity_refs[1] and oracle_process_refs[0] == oracle_process_refs[1]:
    fail("oracles", "identity_or_process_must_be_distinct")

receipt = obj(config, "receipt")
exact(receipt, "record_mode", "append-only-observed-facts")
if set(list_value(receipt, "required_observation_fields")) != {
    "stage",
    "status",
    "run_id",
    "native_refs",
    "actor_ref",
    "source_ref",
    "observed_at",
    "event_ref",
    "content_hash",
    "runtime_facts",
}:
    fail("receipt.required_observation_fields", "receipt_fields_mismatch")
if set(list_value(receipt, "required_native_refs")) != {"project_id", "task_id", "room_id"}:
    fail("receipt.required_native_refs", "native_refs_mismatch")
if set(list_value(receipt, "allowed_statuses")) != {"OBSERVED", "NOT_OBSERVED", "BLOCKED"}:
    fail("receipt.allowed_statuses", "status_set_mismatch")
exact(receipt, "secret_handling", "variable-names-and-content-hashes-only")
exact(receipt, "result_authority", "native-events-and-oracle-records")
exact(receipt, "bundle_hash", "computed-after-run")

if set(list_value(config, "allowed_script_operations")) != {
    "validate_configuration",
    "observe_existing_state",
    "record_external_fault_reference",
    "write_redacted_receipt",
}:
    fail("allowed_script_operations", "operation_set_mismatch")
if len(list_value(config, "forbidden_script_operations")) < 6:
    fail("forbidden_script_operations", "guard_set_too_small")
if len(list_value(config, "known_gaps")) < 4:
    fail("known_gaps", "gap_register_incomplete")

print("M2B_PREFLIGHT_OK")
print("dry_run=true")
print("native_chain=manager>leader>worker")
print("human_gate=external_manual_resume")
print("fault_policy=real_native_recovery")
print("oracle_separation=required")
print("task_takeover=NOT_IMPLEMENTED")
print("receipt=observed_refs_and_hashes_only")
print("run_start=not_started")
PY
