# M1 Leg 1 — Bounded Runtime/Provenance Inventory (native-m0-clean-team)

## Objective
Produce a bounded, non-sensitive runtime/provenance inventory for this isolated AgentTeams environment. This is a functional team leg of the M1 dual-team vertical chain.

## Scope (non-sensitive only)
Collect ONLY the following runtime facts. DO NOT collect, echo, or persist any credential values, API keys, tokens, passwords, or host file contents:
1. Current UTC timestamp (`date -u`)
2. Container hostname (`hostname`)
3. The set of environment variable NAMES in the `AGENTTEAMS_*` family (names only, NO values)
4. Provider/model info available to you (model id used for this run, e.g. from your runtime config) — report the model id string only.

## Deliverable
Write your result to `result.md` in the task directory, then submit via taskflow (`submit_task`). The result must include a structured minimal handoff block with these EXACT fields, populated from REAL collected data:
- `task_id`: your task id
- `project_id`: the project id you created for this task
- `provider_run_id`: a real identifier for this run (e.g. model id / run identifier you actually used)
- `conclusion`: one-line acceptance conclusion
- `evidence_ref`: path to the result/evidence file(s)
- `provenance`: how each fact was collected (the real commands/tools used)
- `unresolved_items`: list or "none"

## Method
- Use the official task-execution/filesync Skill and TeamHarness tools to read this spec from the task directory, collect facts, write result.md, and submit.
- Execute with your real provider/runtime.

## Completion Report
After `taskflow submit_task` returns `ok: true`, reply in the current assignment room and mention the exact Leader Matrix user from this task context:

@native-m0-clean-leader:matrix-native-m0-20260901.agentteams.local:28080 TASK_COMPLETED: task-20260901-193754 - Result: shared/tasks/task-20260901-193754/result.md

Do not use `NO_REPLY` after a successful task submission.

