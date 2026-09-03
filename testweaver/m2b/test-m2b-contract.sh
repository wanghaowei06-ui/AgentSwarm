#!/usr/bin/env bash
set -euo pipefail

# RED first: this test intentionally fails until the M2-B contract and
# read-only preflight are added.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFLIGHT="$ROOT_DIR/m2b-preflight.sh"
CONTRACT="$ROOT_DIR/m2b-contract.example.json"
RECEIPT_SCHEMA="$ROOT_DIR/m2b-receipt.schema.json"

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

[[ -x "$PREFLIGHT" ]] || fail "preflight is not executable"
[[ -f "$CONTRACT" ]] || fail "example contract is missing"
[[ -f "$RECEIPT_SCHEMA" ]] || fail "receipt schema is missing"

for json_file in "$CONTRACT" "$RECEIPT_SCHEMA"; do
  python3 - "$json_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    json.load(handle)
PY
done

output="$($PREFLIGHT --config "$CONTRACT" --dry-run)" || fail "valid dry-run contract was rejected"
for expected in \
  "M2B_PREFLIGHT_OK" \
  "dry_run=true" \
  "native_chain=manager>leader>worker" \
  "human_gate=external_manual_resume" \
  "fault_policy=real_native_recovery" \
  "oracle_separation=required" \
  "task_takeover=NOT_IMPLEMENTED"; do
  rg -Fq "$expected" <<<"$output" || fail "dry-run omitted $expected"
done

if "$PREFLIGHT" --config "$CONTRACT" >/dev/null 2>&1; then
  fail "preflight exposed a live mode"
fi

bad_config="$(mktemp "$ROOT_DIR/.m2b-invalid.XXXXXX")"
trap 'rm -f "$bad_config"' EXIT
python3 - "$CONTRACT" "$bad_config" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    config = json.load(handle)
config["scope"]["runtime_mutation"] = True
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    json.dump(config, handle)
PY
if "$PREFLIGHT" --config "$bad_config" --dry-run >/dev/null 2>&1; then
  fail "unsafe runtime mutation flag was accepted"
fi

python3 - "$RECEIPT_SCHEMA" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    schema = json.load(handle)
required = set(schema["required"])
expected = {
    "schema_version",
    "run_id",
    "native_refs",
    "observations",
    "oracle_observations",
    "evidence_bundle_hash",
}
missing = expected - required
if missing:
    raise SystemExit("receipt schema missing required fields: " + ",".join(sorted(missing)))
PY

# The preflight may validate declarations, but it must not contain a live
# execution path or a second orchestration surface.
for forbidden in \
  "curl " \
  "wget " \
  "docker " \
  "kubectl " \
  "mcporter" \
  "room_send" \
  "create_project" \
  "delegate_task" \
  "submit_task" \
  "accept_task_result" \
  "model_call" \
  "send_human"; do
  if rg -n -F "$forbidden" "$PREFLIGHT" >/dev/null; then
    fail "preflight contains forbidden live/orchestration marker: $forbidden"
  fi
done

if rg -n -i 'task-[0-9]{6,}|project-[0-9]{6,}|run-[0-9]{6,}' "$CONTRACT" >/dev/null; then
  fail "example contract is bound to a concrete run"
fi

if rg -n -i 'Bearer[[:space:]]|\bsk-[A-Za-z0-9]{8,}\b|password[[:space:]]*=' \
  "$PREFLIGHT" "$CONTRACT" "$RECEIPT_SCHEMA" "$ROOT_DIR/README.md" >/dev/null; then
  fail "M2-B contract tree contains credential-like material"
fi

printf 'PASS: M2-B contract RED→GREEN checks passed\n'
