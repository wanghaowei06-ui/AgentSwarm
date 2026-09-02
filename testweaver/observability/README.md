# Read-only AgentLoop / OTel query preparation

This directory contains the thinnest query-side preparation for a real
TestWeaver run. It does not emit spans, create or update AgentLoop resources,
start containers, control an AgentTeams run, or make an Oracle decision.

`readonly_query.py` accepts only bounded `GET` requests. It keeps a
location-only protected-config reference, never opens that file, and accepts
secret-aware headers only from an external runtime callback. Headers and
response bodies are never placed in `QueryReceipt`.

One response is `VERIFIED` only when a successful JSON readback contains all
four run anchors: `campaign_id`, `run_id`, PostgreSQL revision, and the exact
content hash. An OTel readback must also contain the requested trace ID.
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
  are not part of this read-only adapter. Only the previously observed GET
  shapes are retained: EvaluationTask, EvaluationTask runs, and AgentLoop
  dataset readback.

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

At audit time the old local OTLP health/export ports were not listening and the
LoongSuite Pilot service was inactive. No AgentLoop query endpoint or
secret-aware header binding was therefore verified. The current LIVE status is
`NOT_VERIFIED`; this package does not upgrade that status by itself.
