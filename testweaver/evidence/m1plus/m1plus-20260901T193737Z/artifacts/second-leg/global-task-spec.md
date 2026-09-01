# M1 Leg 2 — Independent Convergence / Cross-Validation (native-m1-verify-team)

## Objective
This is the SECOND functional team leg of the M1 dual-team vertical chain. Your function is DIFFERENT from the first team (which produced a runtime/provenance inventory). Your job is INDEPENDENT convergence / cross-validation: independently re-derive the same class of non-sensitive runtime facts and verify they are internally consistent — WITHOUT copying the first team's result.

## Scope (non-sensitive only — NO credential values, NO keys, NO host-file contents)
Independently collect and validate (do NOT read or copy any prior team's output file):
1. Current UTC timestamp (`date -u`) — must be recent (within ~5 min of now)
2. Container hostname (`hostname`)
3. The set of `AGENTTEAMS_*` environment variable NAMES (names only, NO values)
4. Model id used for this run (from your runtime config)
Then perform a convergence check: verify these facts are self-consistent (e.g. timestamp is current, env-name set is non-empty and plausible, model id matches your actual runtime).

## Method
- Leader: use ONLY official TeamHarness roomflow/projectflow/taskflow to create a project + a bounded DAG single-node task, and delegate it to the real Worker via taskflow.
- Worker: execute with your real provider using the official task-execution/filesync or available TeamHarness tools. Read the task, collect the non-sensitive runtime facts INDEPENDENTLY, write them to `result.md` in the task directory, and `submit_task`. Do NOT read or copy the first team's (native-m0-clean-team) result files — verify independently.
- Leader: genuinely run `check_task` and `accept_task_result`.

## Deliverable — Accepted Report with minimal structured handoff (fields from REAL results)
- `task_id`, `project_id`, `provider_run_id`, `conclusion`, `evidence_ref`, `provenance`, `unresolved_items`

## Completion
Post the accepted report (with the handoff block) to the Manager via the Manager/Leader Room → Manager relay path. Do NOT attempt to join the private admin DM (you are not a member there). No intermediate progress messages — deliver the final accepted report directly.
