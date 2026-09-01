# M1 Leg 1 — Bounded Runtime/Provenance Inventory

**Team:** native-m0-clean-team (native worker: `native-m0-clean-worker`)
**Task:** task-20260901-193754
**Collected at (UTC):** 2026-09-01 19:39:10 UTC

## Inventory (non-sensitive facts only)

### 1. Current UTC timestamp
```
Tue Sep  1 19:39:10 UTC 2026
```

### 2. Container hostname
```
8c16d7eac460
```

### 3. `AGENTTEAMS_*` environment variable NAMES (names only — no values)
39 variables found (sorted):

```
AGENTTEAMS_AGENT_HOME
AGENTTEAMS_AGENT_NAME
AGENTTEAMS_AGENT_ROLE
AGENTTEAMS_AI_GATEWAY_DOMAIN
AGENTTEAMS_AI_GATEWAY_URL
AGENTTEAMS_AUTH_TOKEN_FILE
AGENTTEAMS_CMS_ENDPOINT
AGENTTEAMS_CMS_LICENSE_KEY
AGENTTEAMS_CMS_METRICS_ENABLED
AGENTTEAMS_CMS_PROJECT
AGENTTEAMS_CMS_SERVICE_NAME
AGENTTEAMS_CMS_TRACES_ENABLED
AGENTTEAMS_CMS_WORKSPACE
AGENTTEAMS_CONSOLE_PORT
AGENTTEAMS_CONTAINER_SOCKET
AGENTTEAMS_CONTROLLER_URL
AGENTTEAMS_EMBEDDING_MODEL
AGENTTEAMS_FS_ACCESS_KEY
AGENTTEAMS_FS_BUCKET
AGENTTEAMS_FS_DOMAIN
AGENTTEAMS_FS_ENDPOINT
AGENTTEAMS_FS_SECRET_KEY
AGENTTEAMS_MATRIX_DEBUG
AGENTTEAMS_MATRIX_DOMAIN
AGENTTEAMS_MATRIX_URL
AGENTTEAMS_RUNTIME
AGENTTEAMS_SHARED_DIR
AGENTTEAMS_SHARED_STORAGE_PREFIX
AGENTTEAMS_STORAGE_ALIAS
AGENTTEAMS_STORAGE_PREFIX
AGENTTEAMS_STORAGE_PROVIDER
AGENTTEAMS_WORKER_CR_NAME
AGENTTEAMS_WORKER_GATEWAY_KEY
AGENTTEAMS_WORKER_HOME
AGENTTEAMS_WORKER_MATRIX_TOKEN
AGENTTEAMS_WORKER_NAME
AGENTTEAMS_WORKER_ROLE
AGENTTEAMS_WORKER_ROOM_ID
AGENTTEAMS_YOLO
```

### 4. Provider/model info
- Model id used for this run: `deepseek-v4-flash`
- Provider id (from runtime config `active_model`): `agentteams-gateway`

---

## Structured minimal handoff block

- `task_id`: task-20260901-193754
- `project_id`: m1-leg1-20260901-193754
- `provider_run_id`: deepseek-v4-flash (via provider `agentteams-gateway`)
- `conclusion`: ACCEPTED — bounded non-sensitive runtime/provenance inventory collected and persisted per spec.
- `evidence_ref`: shared/tasks/task-20260901-193754/result.md
- `provenance`:
  - UTC timestamp: `date -u` (output: `Tue Sep  1 19:39:10 UTC 2026`)
  - Hostname: `hostname` (output: `8c16d7eac460`)
  - Env var names: `env | grep -o '^AGENTTEAMS_[A-Za-z0-9_]*' | sort` (names only; no values collected/persisted)
  - Provider/model: parsed runtime config `agent.json` `active_model` via Python (scrubbed for sensitive keys); model id `deepseek-v4-flash`, provider id `agentteams-gateway`
  - Spec read via TeamHarness filesync + task-execution skill from `shared/tasks/task-20260901-193754/spec.md` and `meta.json`
- `unresolved_items`: none
