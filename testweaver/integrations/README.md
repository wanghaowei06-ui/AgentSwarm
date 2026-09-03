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
  `BLOCKED`. A successful request is only `API_ACCEPTED`; only task and run GET
  readback proving exact AgentSpace ownership, Campaign/Run/revision scope,
  terminal state, and a non-empty successful result becomes
  `API_QUERY_VERIFIED`. Dataset-backed evaluation is intentionally limited to
  one `content` row and exposes no hidden Gold. `create_trace_evaluation_task_run`
  uses the official trace-native `CreateEvaluationTask` shape (`dataType=trace`,
  trace variable mapping, bounded trace filter, and optional backfill window)
  for a real Hero Trace; it has the same non-empty-result/readback gate and can
  never turn an accepted-but-empty task into a LIVE claim. Use
  `verify_trace_evaluation_task_run` for the corresponding readback: it also
  requires `dataType=trace`, `config.dataScope=trace`, and an exact TraceID
  filter, so a same-tag Dataset task cannot satisfy the Hero gate.
- `tea_transport.py` loads an owner-only protected AccessKey CSV at runtime and
  signs AgentLoop requests through the installed Alibaba Cloud Tea SDK. Secret
  material is neither dataclass-expandable nor printable.
- `xtrace_readback.py` performs bounded `XTrace/2019-08-08 GetTrace` reads for a
  caller-supplied TraceID. Its sealed receipt retains only response/request
  hashes, span count, and exact Campaign/Run/PostgreSQL-revision/content-hash
  anchor matches. HTTP 401/403 remains `BLOCKED`; a successful export or an
  OTLP HTTP 200 is never upgraded without this server-side readback.

There is no delete, lifecycle controller, Observer, synthetic `LIVE` assertion,
or autonomous cloud write probe in this package. A real run must supply the
known TraceID and matching authority tuple; tests use injected transports only.

The normalized native fact types are `manager_choice`, `accepted_result`,
`handoff`, `skill_invocation`, `dsh_call`, `recovery_generation`,
`late_result_rejection`, `oracle_ref`, and `agentloop_ref`. Their exact required
fields are enforced in `projector.py`; unknown fields and unfinished events are
rejected rather than guessed.
