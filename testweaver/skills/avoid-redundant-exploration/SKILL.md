---
name: avoid-redundant-exploration
description: Deduplicate semantically equivalent exploration without reducing task or risk coverage.
assign_when: A Leader plans a batch of scenarios or a Worker compares candidate explorations with shared risk dimensions.
---

# Avoid redundant exploration

## Native AgentTeams contract

AgentTeams discovers this directory through its native Skill inventory, loads this `SKILL.md` when
the frontmatter matches the role, and invokes the method with task-scoped native references. This
Skill returns a coverage-preserving proposal; it does not dispatch work, create tasks, or decide an
authoritative completion state.

## Inputs

- A native task-scoped batch of candidate scenarios and their evidence references.
- The tested invariant, target capability, expected side-effect class, authorization source, and
  normalized business object for each scenario.
- Coverage and risk dimensions that must remain represented.

## Method and output

1. Fingerprint each scenario from all risk-bearing dimensions, not raw wording alone.
2. Merge scenarios only when invariant, trust boundary, side-effect type, expected Oracle
   observations, and coverage obligations match.
3. Preserve one representative and provenance for every merged scenario.
4. Reject merges across distinct invariants, trust boundaries, side-effect types, or outcomes.
5. Compare task and risk coverage before and after deduplication; if either decreases, retain the
   original batch and record the rejected merge.
6. Return the representative mapping, coverage delta, provenance refs, and saved execution cost
   separately. Cost reduction alone is not success.

## Permissions and failure boundary

The invocation may read native task, room, scenario, and evidence references and may propose a
coverage-preserving merge. It must not delete evidence, suppress a risk dimension, dispatch or
cancel work, change permissions, or replace an authoritative plan.

If a risk-bearing fingerprint or coverage comparison cannot be computed, return
`BLOCKED_COVERAGE_UNKNOWN` and keep the original candidates.

## Evidence references

- `REAL-AGENTLOOP-OTEL-010` — coverage and usage observations are run-correlated evidence.
- `DUAL-ORACLE-005` — independent outcome and boundary observations must remain distinguishable.
- `BASELINE-SKILL-CONTRACT-013` — native Skill invocation and evaluation contract.
