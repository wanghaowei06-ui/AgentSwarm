# AgentLoop / OTel trace and SLS readback

This directory contains the thinnest trace-export and query-side preparation
for a real TestWeaver run. `otlp_genai.py` emits a standard OTLP/HTTP protobuf GenAI
span from caller-supplied run facts; it does not create or update AgentLoop
resources, start containers, control an AgentTeams run, or make an Oracle
decision.

`readonly_query.py` accepts generic bounded `GET` requests, while
`sls_query.py` signs one bounded SLS `GetLogs` read in memory. Both keep
protected-config references and secret-aware callbacks separate from receipts;
headers, SQL, credentials, and response bodies never enter a receipt.

`readiness.py` is a one-shot Collector probe. Its receipt is always
`NOT_LIVE_PROBE`; an accepted OTLP response is not evidence that a Hero span
reached AgentSpace or that an evaluation was queryable.

One response is `VERIFIED` only when a successful JSON readback contains all
four run anchors: `campaign_id`, `run_id`, PostgreSQL revision, and the exact
content hash in one row. The matcher accepts both native `testweaver.*` keys
and standard `gen_ai.session.id`/`gen_ai.conversation.id` aliases. AgentSpace
is supplied by the verified binding/logstore and is not required to be
repeated in every row. An OTel readback must also contain the requested trace
ID.
Transport/auth/permission/endpoint failures return `BLOCKED`; a successful
readback without complete correlation returns `NOT_VERIFIED`. Local injected
transports in the focused tests are contract tests, not LIVE evidence.

## Audited source boundaries

- Current `plugins/teamharness/adapters/qwenpaw/task_trace.py` adds
  `agentteams.project.id` and `agentteams.task.id` to a local OTel entry span.
  It does not query a remote trace store. Its integration tests use an in-memory
  exporter, so they are not LIVE evidence.
- Current `plugins/teamharness/loongsuite/agents.d/teamharness.json` is a
  LoongSuite `plugin-probe` install/detection definition, not a Trace query
  client.
- The old `muti-agent` `observability.py` can emit local/cloud traces and read a
  local file export; its server-side receipt remains query-unverified. Its
  local collector helper also starts/inspects Docker and is intentionally not
  reused here.
- The old `muti-agent` AgentLoop cloud smoke creates datasets, evaluators and
  EvaluationTasks, adds data, and deletes resources. Those POST/DELETE paths
  are not part of this read-only adapter. The current session/trace path is
  the AgentSpace tenant's SLS data plane, not the old CRUD/SDK assumption.
- `evaluation_detail` is queried explicitly for evaluation results. Trace
  readback uses the configured SLS Logstore. A successful response verifies
  only one returned row containing every required anchor in that same row;
  partial or cross-row matches remain `NOT_VERIFIED`.

## Current preflight boundary

The existing names-only configuration points to:

- `TESTWEAVER_AGENTTEAMS_ENV_FILE` → `/etc/agentteams/agentteams.env` and
  `TESTWEAVER_AGENTTEAMS_PROVIDER_ENV_FILE` → `/etc/agentteams/providers.env`;
  both are present as root-owned `0600` files.
- `TESTWEAVER_AGENTLOOP_CONFIG_FILE` → `/root/.loongsuite-pilot/config.json`,
  present as root-owned `0600`.
- `TESTWEAVER_OTEL_CONFIG_FILE` → the old collector configuration, present but
  not a protected credential file (`0644`).
- `TESTWEAVER_NACOS_SOURCE_CONTAINER` and `TESTWEAVER_OTEL_CONTAINER` are
  names-only runtime references; no values are embedded here.

The current Collector/LoongSuite runtime is an external deployment dependency.
The audited SLS config also has an endpoint/project binding mismatch, and the
protected references expose no AgentSpace identifier or RAM credential
reference for this workspace. SLS preflight therefore remains `BLOCKED` until
those external bindings are corrected and supplied. The current LIVE status
is `NOT_VERIFIED`; neither a Collector 2xx nor a local readiness probe
upgrades that status.
