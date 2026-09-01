---
name: reconcile-before-retry
description: Reconcile an unknown external result before retrying so a committed effect is not duplicated.
assign_when: A Worker handles an external action whose response may be lost while durable status can be queried.
---

# Reconcile before retry

## Native AgentTeams contract

AgentTeams discovers this directory through its native Skill inventory, loads this `SKILL.md` when
the frontmatter matches the role, and invokes the method with task-scoped native references. This
Skill proposes a recovery disposition only; it does not create tasks, dispatch work, or replace the
native task and room lifecycle.

## Inputs

- The native task/run reference and durable `ACTION_PENDING` evidence.
- The stable business/action fingerprint, original request hash, and original idempotency key.
- A documented status query or idempotent replay contract for the referenced external action.

## Method and output

1. Preserve the fingerprint, request hash, original key, and pending state before any invocation.
2. Query durable external status before issuing another mutating call.
3. If a matching effect exists, return `ADOPT` with the effect reference and completion evidence.
4. If absence is authoritative, return `RETRY_WITH_ORIGINAL_KEY`; never create a fresh key.
5. If status is unavailable or contradictory, return `STOP_UNCERTAIN` with the unresolved evidence.
6. Report both task disposition and effective external commit count when the durable ledger exposes it.

## Permissions and failure boundary

The invocation may read native task, room, action-status, idempotency, and evidence references and
may propose one of the three dispositions. It must not read credentials, issue an unapproved external
mutation, alter durable authority, or claim exactly-once behavior for a non-queryable target.

Missing fingerprints, missing idempotency semantics, contradictory status, or an unavailable
reconciliation query are fail-closed `STOP_UNCERTAIN` outcomes.

## Evidence references

- `PG-RECOVERY-FENCING-002` — durable generation, lease, CAS, and late-result boundary.
- `CONTEXT-EVIDENCE-HANDOFF-011` — versioned context, evidence, provenance, and handoff references.
- `BASELINE-SKILL-CONTRACT-013` — Skill invocation and permission contract.
