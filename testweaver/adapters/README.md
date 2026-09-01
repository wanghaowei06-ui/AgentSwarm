# TestWeaver heterogeneous worker adapter boundary

This directory is a source-only, non-executing product-difference layer.  It
normalizes external results, approved usage limits, evidence references, and
protected configuration locations around AgentTeams-native work.

## Reused native boundaries

- AgentTeams Controller owns Worker runtime selection, identity, storage, and
  lifecycle through its native backend interface.
- TeamHarness owns native room/project/task transport and delegation.
- The committed PR1139 Codex remote-member bridge owns app-server protocol,
  environment allowlisting, MCP capability wiring, and process handling.
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

`codex_cli.py` records the fixed lowercase `codex-cc` app-server entrypoint,
model `gpt-5.6-luna`, reasoning `max`, and only the protected
`HOME`/`CODEX_HOME` environment names.  Local `codex-cc` 0.152.0 help
confirmed that `app-server --listen stdio://` is the real transport, `-m`
and `-c key=value` are global options, and there is no separate `config`
subcommand.  The launch contract therefore places `-m gpt-5.6-luna` and
`-c model_reasoning_effort=max` before `app-server`.  It never resolves the
executable, reads those locations, copies login material, or starts an
external process.

`native_worker.py` is the only lifecycle-facing seam: a native Leader-provided
assignment is carried as opaque project/task/room/Leader/Worker references;
the native Worker supplies an already-produced result; and the adapter returns
the shared result projection with provider, model reference, usage, elapsed
latency, evidence, and provenance.  AgentTeams remains the owner of assignment
and result collection.

The tests use explicit `TEST_FIXTURE_ONLY_NOT_LIVE` values.  They exercise
configuration and result contracts only; they do not call a provider, execute
the external worker, or prove a live run.
