#!/usr/bin/env bash
# Focused static contract for the generic Manager delegation invariant.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE="${ROOT_DIR}/manager/agent/AGENTS.md"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

grep -Fq "## Complex multi-agent delegation invariant" "${SOURCE}" \
  || fail "delegation invariant heading is missing"
grep -Fq "team-management/SKILL.md" "${SOURCE}" \
  || fail "team-management Skill load requirement is missing"
grep -Fq "references/team-task-delegation.md" "${SOURCE}" \
  || fail "team-task-delegation reference requirement is missing"
grep -Fq "references/finite-tasks.md" "${SOURCE}" \
  || fail "finite-tasks reference requirement is missing"
grep -Fq "agt get" "${SOURCE}" \
  || fail "dynamic agt roster read requirement is missing"
grep -Fq "manage-state.sh" "${SOURCE}" \
  || fail "manage-state requirement is missing"
grep -Fq -- "--delegated-to-team" "${SOURCE}" \
  || fail "delegated-to-team requirement is missing"
grep -Fq "message" "${SOURCE}" \
  || fail "Leader message requirement is missing"
grep -Fq "TEXT_PLAN" "${SOURCE}" \
  || fail "TEXT_PLAN prohibition is missing"
grep -Fq "ordinary Worker" "${SOURCE}" \
  || fail "direct ordinary Worker prohibition is missing"

# The invariant must remain generic and cannot name a test case, run, team, or worker.
if grep -Eiq 'm2g|stageb|native-m0|native-m1|run-[0-9]{8}' "${SOURCE}"; then
  fail "case/team/worker/run-specific identifier leaked into Manager source"
fi

echo "PASS: generic Manager delegation invariant is present"
