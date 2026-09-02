# TestWeaver heterogeneous worker adapter boundary

This directory is a thin product-difference layer around AgentTeams-native
work. It has one bounded MCP tool for one-shot external execution; native
assignment, state, transport, and submission remain outside this directory.

## Reused native boundaries

- AgentTeams Controller owns Worker runtime selection, identity, storage, and
  lifecycle through its native backend interface.
- TeamHarness owns native room/project/task transport and delegation.
- The committed PR1139 Codex capability is reused only for the fixed CLI
  identity; this bridge uses the CLI's non-interactive `exec` entrypoint and
  does not copy an app-server protocol.
- The DSH source assets remain reference material for provider-neutral usage,
  receipt binding, transition normalization, and bounded termination facts; no
  DSH process loop or source export parser is copied here.

`testweaver/adapters/config.py` accepts one generic `ProviderRoute`.  The
provider identifier is not restricted to a single vendor, while endpoint,
model, and credential fields are location-only references (`env` or absolute
protected `file`).  `native_worker.py` makes DeepSeek and Alibaba Bailian
explicit DSH profiles while retaining the generic provider path; neither
profile resolves its references.  Thus the same DSH contract covers both
providers without embedding either endpoint or any credential.

`result.py` is shared by both adapter kinds.  It keeps native project/task/room
IDs as read-only opaque correlation references, records only evidence pointers,
represents unavailable usage as `null` rather than zero, and seals the result
with a canonical SHA-256.  A reported limit overrun changes an otherwise
completed projection into a terminated budget result; it does not stop or
retry anything.

`codex_cli.py` records the fixed lowercase `codex-cc` non-interactive `exec`
entrypoint, model `gpt-5.6-luna`, reasoning `max`, and only the protected
`HOME`/`CODEX_HOME` environment names. The prompt is sent on stdin; no
interactive session, approval protocol, or login material is copied.

`native_worker.py` remains the lifecycle-facing contract: a native
Leader-provided assignment is carried as opaque project/task/room/Leader/Worker
references. `executor.py` starts at most one fixed external process, returns the
shared result projection with provider, model reference, usage, elapsed latency,
evidence, and provenance, and explicitly reports that native state and result
submission were not mutated. AgentTeams remains the owner of assignment and
result collection.

The tests use explicit fake executables and `TEST_FIXTURE_ONLY_NOT_LIVE`
values. They exercise the process safety contract without calling a provider,
using a real external Worker, or proving a live run.

## Deployment preflight and rollback

`preflight_reference` and `preflight_native_worker_invocation` remain
names-only checks. The execution seam additionally validates the fixed three
profiles (`deepseek`, `aliyun-bailian`, and `codex-cc`), resolves only
allowlisted reference names, bounds one process and its process group, limits
output, and writes only redacted artifacts. A `BLOCKED` result leaves native
state unchanged.

The QwenPaw AgentSpec package is under `qwenpaw-package/`; it registers only
the one stdio tool and one Skill through the existing package updater. The
`Dockerfile.qwenpaw` and `build-qwenpaw-native-extension.sh` entrypoint add the
adapter, fixed `codex-cc` CLI wrapper, and an explicitly supplied DSH binary to
an immutable base image. The build entry refuses a missing or unsafe DSH
artifact and never synthesizes provider capability. Roll back by restoring the
prior immutable image/package reference through normal AgentTeams reconciliation;
do not change native task state. LIVE remains `NOT_VERIFIED` until a real
native Leader delegation produces and collects a Worker result.
