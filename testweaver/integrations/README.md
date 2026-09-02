# TestWeaver native integration edge

This package is a thin, post-run edge around AgentTeams. AgentTeams remains
the only owner of Manager/Leader/Worker coordination, Matrix rooms, Projects,
Tasks, retries, and lifecycle state.

- `projector.py` accepts a strict normalized finished native fact, binds its
  exact input-byte hash and native reference, and appends metadata to the
  existing authority store. It cannot create or update native resources.
- `matrix_readback.py` performs one injected Matrix room/event GET plus an
  injected read-only sender-to-identity lookup, then verifies exact sender,
  external identity, run, revision, decision, action, and action
  fingerprint before producing a sealed Human readback attestation. It cannot
  send or resume anything.
- `heterogeneity.py` seals the candidates, evidence, Manager's already-made
  choice, and the runtime/provider/model/usage observation. It does not rank,
  choose, or dispatch candidates.
- `agentloop_client.py` retains the inherited official request shapes for
  Dataset create/add/get, Evaluator create/get, and EvaluationTask create with
  backfill plus task/run get. Credentials come from a callback. Receipts retain
  hashes and classifications, not credential values, request bodies, response
  bodies, resource names, or request IDs. Endpoint and permission failures are
  `BLOCKED`. There is no delete, lifecycle controller, Observer, or synthetic
  `LIVE` assertion.

The normalized native fact types are `manager_choice`, `accepted_result`,
`handoff`, `skill_invocation`, `dsh_call`, `recovery_generation`,
`late_result_rejection`, `oracle_ref`, and `agentloop_ref`. Their exact required
fields are enforced in `projector.py`; unknown fields and unfinished events are
rejected rather than guessed.
