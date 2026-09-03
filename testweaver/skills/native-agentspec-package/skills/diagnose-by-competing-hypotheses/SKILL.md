---
name: diagnose-by-competing-hypotheses
description: Resolve material diagnostic ambiguity with the smallest discriminating experiment.
assign_when: A Leader or Worker investigates evidence-backed causes that imply materially different repairs.
---

# Diagnose by competing hypotheses

## Native AgentTeams contract

AgentTeams discovers this directory through its native Skill inventory, loads this `SKILL.md` when
the frontmatter matches the role, and invokes the method with task-scoped native references. This
Skill returns a diagnosis proposal; it does not create tasks, alter policy, accept results, or run a
second coordination path.

## Inputs

- A public failure or observation capsule reference for the current native task.
- Minimal reproduction, source, trace, state, and prior evidence references.
- At least two evidence-backed causes whose repairs or observable predictions differ.

## Method and output

1. State each hypothesis, fault domain, supporting evidence, falsification condition, and expected
   observation separately.
2. Treat a single-trace interpretation as a signal, not a confirmed cause.
3. Choose the smallest experiment that produces different outcomes for the leading hypotheses, and
   record changed, held, and uncontrolled dimensions.
4. Reject hypotheses contradicted by the observation; retain uncertainty when the experiment does
   not discriminate.
5. Stop when one actionable cause remains or escalation is cheaper than another experiment.
6. Return `DIAGNOSIS_PROPOSED` with the surviving cause, evidence refs, experiment record, and
   unresolved questions, or `BLOCKED_INSUFFICIENT_EVIDENCE`.

## Permissions and failure boundary

The invocation may read native task, room, source, trace, and evidence references and may propose a
diagnostic experiment. It must not read credentials or hidden validation data, write a patch, change
task authority, or turn a hypothesis into an accepted fact.

Do not create ceremonial branches for a deterministic cause. If causes have identical predictions,
or evidence is insufficient, return the bounded blocked disposition instead.

## Evidence references

- `REAL-AGENTLOOP-OTEL-010` — trace and usage evidence must be correlated to the same run.
- `CONTEXT-EVIDENCE-HANDOFF-011` — evidence and provenance remain versioned and addressable.
- `BASELINE-SKILL-CONTRACT-013` — native Skill invocation and redaction boundary.
