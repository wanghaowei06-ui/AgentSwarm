# Native external Worker execution

Use this skill only after the native Leader has assigned you a real
AgentTeams Task and supplied the opaque `assignment` references. The native
TeamHarness remains responsible for task state, room messages, delegation,
submission, and acceptance.

Call the single `testweaver-native-worker` MCP tool once for one-shot external
work. Pass only these four fields:

- `assignment`: the native project, task, room, Worker, Leader, and task
  references from the current assignment; keep `read_only` true.
- `config`: the existing `AdapterConfig` shape (`adapter_kind`, protected
  route references, and approved limits). For DSH, use only `deepseek` or
  `aliyun-bailian`; for the CLI use `codex-cli` with provider `codex-cc`.
- `provenance`: the source, revision, and method for this Worker result.
- `prompt`: the bounded, non-interactive instruction for this one execution.

The DSH route receives endpoint, model, and credential locations only; never
place a resolved value in the request. The Codex route is fixed to
`codex-cc`, model `gpt-5.6-luna`, and reasoning `max`, with the protected
`HOME` and `CODEX_HOME` environment. Do not override its executable, argv,
working directory, environment, or sandbox.

The tool returns the shared `NormalizedResult` plus non-secret process
observations. Missing upstream usage stays unavailable; do not convert it to
zero or infer provider output. Use the returned artifact and provenance as
evidence, then use the native TeamHarness task contract to report your result.

This tool has no native task, project, room, lease, scheduling, or Matrix
permission. Do not use it to create work, delegate work, change status, or
submit on another actor's behalf. Fake-process tests are local contract tests,
not LIVE provider evidence.
