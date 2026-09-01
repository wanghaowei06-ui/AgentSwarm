# M2-B native shortest-path contract

This directory is preparation only. It is an unbound, dry-run contract based on control-document commit `eb0364d`; it does not start an M2 run, change a package or runtime, send a Matrix event, call a model, or create native work.

Run the local checks with:

```bash
bash testweaver/m2b/test-m2b-contract.sh
bash testweaver/m2b/m2b-preflight.sh \
  --config testweaver/m2b/m2b-contract.example.json --dry-run
```

The preflight accepts only `--dry-run`. It reads one non-secret contract file located inside this directory and prints field-level status names; it does not read runtime environment, protected configuration, logs, or object storage.

## Native path to prove in one future run

The external coordinator supplies one real Human event. Native AgentTeams then owns the following chain and returns native identifiers and event references for the receipt:

1. Manager receives the Human event and dynamically selects a Team and its Leader.
2. Leader uses the native TeamHarness `roomflow`, `projectflow`, and `taskflow` path to create/resolve the Project, plan ready work, delegate a Task, and notify the Worker in the native Team Room.
3. Worker acknowledges and submits through native task state. Leader checks the Task, accepts the result, reports through the native project reply route, and Manager makes the follow-up decision.
4. Leader emits a native PAUSE state/event. The external Codex coordinator is the Human and makes the later resume decision manually. The agent must not resume from a timer, a receipt, or its own request.
5. The external coordinator performs exactly one real, approved Worker process/container fault through the existing lifecycle/controller path. It records only operation metadata. No Matrix event or task result is injected. The Leader recovers from the native Project/Task state, and any continuation is a new/replanned native node; a late result from the old Task is input only.
6. Outcome and Boundary Oracle are separate by Agent identity or process (the example requires both), each reads the same Run evidence root read-only, and each emits an independent result reference. The runner records those references and hashes; it does not calculate either conclusion.

The receipt binds every observation to the same `run_id`, native `project_id`/`task_id`/`room_id`, actor reference, source reference, timestamp, event reference where present, content hash, and ref-only provider/model/usage facts. `NOT_OBSERVED` and `BLOCKED` are first-class values. Protected values are never part of the contract or receipt.

## Audit-backed reuse and explicit gaps

No new control layer is needed for these existing capabilities:

- Controller owns Team/Manager/Worker/Human desired state, Matrix identities and rooms, container convergence, and CR generation/observed-generation.
- TeamHarness owns native Room/Project/Task state, Leader delegation, Worker acknowledgement/submission, Leader checking/acceptance, and requester handoff.
- QwenPaw owns runtime desired-state application; `metadata.generation` and package identity are usable as runtime recovery evidence without restarting the QwenPaw process for an unchanged package.
- Matrix already supplies sender, room, event ID, and origin timestamp; readback/log evidence is the event source because TeamHarness has no separate event-reader tool.
- Existing TestWeaver contract validation, frozen evidence conventions, and the five domain Skill documents remain references. This directory does not copy or schedule them.

The read-only audit used these source surfaces: `plugins/teamharness/mcp/server.py` for the native tool and state boundaries; `plugins/teamharness/docs/teamharness-project-task-runtime-design.md` and the Team Leader project/task skills for pause/resume, check/accept, and handoff order; `agentteams-controller/internal/controller/worker_controller.go` and `qwenpaw/src/qwenpaw_worker/update.py` for runtime generation/reconciliation; `plugins/agentteams-matrix-channel/agentteams_matrix/channel.py` for event identity and timestamp evidence; and `testweaver/contracts/validator.py`, `testweaver/contracts/README.md`, and the existing domain Skills for ref-only evidence conventions. The total-control baseline remains read-only.

The following are deliberately not implemented or implied:

- Current TeamHarness has no task lease, task takeover, or task-level generation/fencing. The contract records Controller/runtime generation only and marks task takeover `NOT_IMPLEMENTED`.
- The TeamHarness design documents `INTERRUPTED`, but its current result-status allowlist does not accept it. A future run must record the native status actually returned and mark this mismatch as a gap; no synthetic status may repair it.
- There is no checked-in independent HITL/Policy service or executable Outcome/Boundary Oracle pair in the current TestWeaver tree. The preflight verifies only the separation declaration; a future run must provide real identity/process/source references or remain `NOT_OBSERVED`.
- Runtime fault restoration and business continuation are different observations. Controller/QwenPaw restoration does not itself prove Task recovery, acceptance, or Manager follow-up.

## Script boundary

The contract permits only configuration validation, read-only observation, recording an externally performed fault reference, and redacted receipt writing. A future coordinator must call native AgentTeams/TeamHarness interfaces as the actors that own those operations. No TestWeaver script may create a Room/Project/Task, delegate or accept work, send Human input, parse model text into a decision, resume without the external Human event, or write an Oracle conclusion.

The current `m2b-preflight.sh` implements only the first boundary: configuration validation and dry-run output. It is intentionally not a live runner.
