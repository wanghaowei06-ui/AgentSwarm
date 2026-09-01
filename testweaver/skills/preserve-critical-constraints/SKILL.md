---
name: preserve-critical-constraints
description: Preserve action-critical policy constraints and pending state across context compaction or restart.
assign_when: A Worker or Leader may compact or replace context that contains safety constraints, pending actions, or recovery state.
---

# Preserve critical constraints

## Native AgentTeams contract

AgentTeams discovers this directory through its native Skill inventory, loads this `SKILL.md` when
the frontmatter matches the role, and invokes the method with task-scoped native references. This
Skill describes a continuation manifest proposal; it does not implement context storage, resume
logic, or another runtime.

## Inputs

- The native task and checkpoint references at the compaction or restart boundary.
- Policy references, action-critical constraints, pending subgoals, and external action fingerprints.
- Hashes of summarized tool outputs and the current context/evidence revision.

## Method and output

1. Select only constraints and references that are critical to safe continuation; do not copy a
   second transcript or hidden reasoning.
2. Build a durable continuation manifest containing policy refs, pending subgoals, action
   fingerprints, checkpoint revision, and summarized-output hashes.
3. Hash the manifest independently of its natural-language summary.
4. On continuation, validate the manifest against the exact task and checkpoint revision before
   proposing another action.
5. Return `RESTORE`, `BLOCKED_MISSING_FIELD`, or `BLOCKED_HASH_MISMATCH` with public evidence refs.

## Permissions and failure boundary

The invocation may read native task, checkpoint, policy, room, and evidence references and may
propose a continuation manifest. It must not infer missing constraints, read credentials, expose
hidden context, or authorize a new action from a summary alone.

An absent required field, missing hash, task mismatch, or revision mismatch is a fail-closed blocked
outcome that requests reconstruction from authoritative references.

## Evidence references

- `CONTEXT-EVIDENCE-HANDOFF-011` — versioned context, evidence, provenance, and handoff authority.
- `REAL-AGENTLOOP-OTEL-010` — trace/usage correlation must remain an evidence reference, not a control input.
- `BASELINE-SKILL-CONTRACT-013` — Skill invocation, permission, and redaction contract.
