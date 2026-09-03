---
name: approval-intent-boundary-check
description: Check that task-scoped approval authorizes the exact external action before it is proposed.
assign_when: A Worker or Leader handles a task whose user approval must be bound to a specific external action.
---

# Approval intent boundary check

## Native AgentTeams contract

AgentTeams discovers this directory through its native Skill inventory, loads this `SKILL.md` when
the frontmatter matches the role, and invokes the method with task-scoped native references. This
Skill returns a bounded proposal and evidence references; it does not create tasks, route rooms, or
write authoritative state.

## Inputs

- The native room/event reference for the approval and the pending task/action reference.
- An action fingerprint that identifies the exact intended external effect.
- The applicable policy and permission references, without credential values or hidden data.

## Method and output

1. Confirm that the approval came from the authoritative native channel and is bound to the pending
   action and its fingerprint.
2. Normalize whitespace and case, then parse the whole intent. A substring that resembles an allow
   word is not authorization.
3. Treat explicit denial, mixed intent, missing intent, or an unbound reply as non-authorization.
4. Return exactly one bounded disposition: `ALLOW`, `DENY`, or `BLOCKED`, with a stable reason and
   public evidence references. An `ALLOW` disposition is only a proposal for the existing policy
   boundary to evaluate.

## Permissions and failure boundary

The invocation may read the native room, task, approval, permission, and side-effect evidence needed
for the binding. It may propose the binding and its evidence references. It must not read credentials,
invent approval, perform an external mutation, or broaden the approved action.

If any identity, action, fingerprint, policy, or evidence binding is absent or contradictory, return
`BLOCKED`; do not infer authorization and do not retry the side effect.

## Evidence references

- `POLICY-HITL-BASELINE-003` — native Human/Matrix interaction with policy authority retained.
- `SECURITY-BOUNDARY-018` — permission, sandbox, and side-effect boundary.
- `BASELINE-SKILL-CONTRACT-013` — Skill manifest, invocation, and redaction contract.
