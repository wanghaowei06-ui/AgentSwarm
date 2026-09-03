# AgentTeams Workspace Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在当前 AgentTeams 源仓库中新增一个位于 `dashboard/` 的、聊天优先的 Agent 产品界面。用户可以在一个工作台中查看并参与真实的 Matrix 会话，同时看到 WorkerFlow 工作流、工具调用、产物、审批/注意事项和系统健康状态，不再依赖切换 Matrix 房间。

**Architecture:** `dashboard/` 是一个独立的 Next.js 应用。它包含一个只服务于 Dashboard 的 BFF/数据适配层：服务端读取真实 Matrix 与 AgentTeams Controller 数据，归一化为 Dashboard 事件流，并通过 SSE 推送给浏览器。浏览器使用 assistant-ui 的自定义外部状态运行时渲染聊天，使用 React Flow 渲染工作流图。Dashboard 不向 AgentTeams 核心目录注入代码，也不替代 Matrix、Controller 或 Agent runtime。

**Tech Stack:** Next.js App Router、React、TypeScript、assistant-ui (`ExternalStoreRuntime`)、`@xyflow/react`、原生 `fetch`/Node 文件存储、Vitest。样式使用 Dashboard 自己的 CSS 变量与组件样式，不引入远程图片或运行时假数据。

**Spec:** `/root/projects/agentteams-dashboard-worktree/docs/superpowers/specs/2026-09-02-agentteams-workspace-dashboard-design.md`（已批准的产品设计；当前实现位置按最新约定改为本源仓库的 `dashboard/`）。

## Global Constraints

- 所有新增和修改只能位于 `/root/projects/agentteams/dashboard/`。不得修改 `agentteams-controller/`、`manager/`、`worker/`、`plugins/`、`testweaver/`、根目录 `Makefile`、安装脚本或其他现有文件。
- 不创建 mock server、seed data、demo run、默认假消息或静态示例运行记录。生产代码只能展示上游已返回或 Matrix 已收到的数据；上游不可用时显示明确的 degraded/error/empty 状态。
- `AGENTTEAMS_AUTH_TOKEN`、Matrix access token、管理员密码、S3/OSS secret 和任何 CMS 凭证只在 Dashboard 服务端使用，不能进入 `NEXT_PUBLIC_*`、HTML、SSE payload 或浏览器 localStorage。
- Matrix 的完整事件必须由 Dashboard 自己调用 Matrix Client-Server API 读取；不能使用 Controller 当前只返回 mentions 的 `SyncMessages` 简化结果作为聊天数据源。
- 会话/运行关联必须遵循：`agentteams.workflow.runId + roomId` → `m.replace` 指向的 workflow 根事件 → 明确的 Matrix thread root → 明确的 task/project metadata。无法唯一关联时保留为未归类 room timeline，不能猜测归属。
- WorkerFlow 卡片只展示结构化的阶段、状态、摘要、参与者和来源 event id。禁止在卡片或默认事件详情中显示完整 prompt、思维链、token、密码、密钥或未经裁剪的大型工具输出。
- 当前仓库能看到 CMS/OTLP 上报配置，但没有现成的 trace 查询 API。第一版不把 ingest endpoint 当成查询源，不伪造 span；只有在真实事件带有 trace id 时展示链接信息，否则右侧显示“暂无可查询 trace 来源”。
- 不因为本功能修改已有部署入口。应用可以通过已有 Dashboard context seam 手动使用 `DASHBOARD_CONTEXT=dashboard` 构建；如后续需要改 `Makefile`/Helm/安装脚本，必须另行说明并取得确认。
- 只保留与本功能直接相关的新增文件；实现过程中每个任务完成后检查 `git diff -- dashboard`，不得覆盖并行 Codex 正在推进的工作。

## Data Contracts

### 1. Upstream adapters

在 `dashboard/lib/controller/client.ts` 实现服务端 Controller client，读取以下只读接口：

- `GET /healthz`
- `GET /api/v1/status`
- `GET /api/v1/workers`
- `GET /api/v1/teams`
- `GET /api/v1/managers`
- `GET /api/v1/workers/{name}/status`

所有请求带服务端 `Authorization: Bearer ${AGENTTEAMS_AUTH_TOKEN}`。适配器返回带 `source`, `status`, `receivedAt` 的结果；Controller 失败时保留错误原因，不返回伪造的健康状态。

在 `dashboard/lib/matrix/client.ts` 实现服务端 Matrix client：

- 使用 `POST /_matrix/client/v3/login`、`m.login.password` 和已有 `AGENTTEAMS_ADMIN_USER`/`AGENTTEAMS_ADMIN_PASSWORD` 获取并缓存服务端 access token；若部署提供固定 Matrix token，则支持服务端环境变量作为优先 token 来源。
- 使用 `GET /_matrix/client/v3/joined_rooms` 发现可访问房间。
- 使用 `GET /_matrix/client/v3/sync` 做增量同步，并保存 `next_batch`。
- 使用 `GET /_matrix/client/v3/rooms/{roomId}/messages?dir=b&limit=...` 做选中房间的历史补齐。
- 使用 `POST /_matrix/client/v3/rooms/{roomId}/send/m.room.message/{txnId}` 发送用户消息；txn id 必须可重试且幂等。
- 对 `mxc://` 媒体只允许通过受限的 Dashboard media route 代理，不允许浏览器直接带 access token 请求 Matrix。

`dashboard/lib/matrix/types.ts` 维护最小完整事件类型：`event_id`, `room_id`, `sender`, `origin_server_ts`, `type`, `content`, `unsigned`，并保留 `m.relates_to`, `m.new_content`, `m.mentions`、媒体信息和 `agentteams.workflow` 等已存在字段。

### 2. Normalized observation model

`dashboard/lib/events/normalizer.ts` 输出统一的 `AgentTeamsEvent`：

```ts
type AgentTeamsEvent = {
  id: string;
  source: "matrix" | "controller";
  kind: "message" | "workflow" | "tool" | "artifact" | "room" | "system";
  occurredAt: string;
  roomId?: string;
  runId?: string;
  actor?: { id: string; label: string; role: "human" | "manager" | "worker" | "system" | "unknown" };
  summary: string;
  detail?: Record<string, unknown>;
  sourceRef: { eventId?: string; endpoint?: string };
};
```

归一化规则：

- 普通 `m.room.message` 映射为 message；保留可展示的 plain/formatted text，支持 `m.notice`、`m.text` 和 Matrix edit。
- `content["agentteams.workflow"]` 映射为 workflow；解析 `runId`, `status`, `title`, `summary`, `ownerRole`, `ownerAgentId`, `coordinator`, `sharedPath`, `subagents`, `steps`。
- 通过稳定字段、消息类型名或已有 Matrix 展示格式识别工具调用/结果；映射为 tool，并仅保存工具名、调用状态、截短且脱敏的参数/结果摘要。无法识别的事件保持 `system`，不做猜测。
- `m.image`、`m.file`、`m.audio`、`m.video` 映射为 artifact，保存 MXC 引用、文件名、MIME、大小和父 event id。
- Matrix `m.replace` 使用新内容更新同一逻辑消息，但事件源 id 仍全部记录，确保工作流演进可回放。
- `GET /api/v1/status`、worker status 等 Controller 结果转换为 system observation；轮询结果带真实 `receivedAt`，不将“未返回”解释成成功。
- 所有输入先经过字段级脱敏与大小限制；不记录 credential 字段、隐藏 reasoning、完整工具 payload 或任意未经验证的 HTML。

### 3. Persistence and stream

`dashboard/lib/events/store.ts` 使用 `AGENTTEAMS_DASHBOARD_DATA_DIR`（未设置时使用容器内 `/app/db`）保存：

- 增量 Matrix `next_batch`；
- 去重后的归一化 observation 记录；
- room/run 关联索引和最近一次 Controller snapshot。

采用可恢复的 append/atomic-replace 写入，事件 id 去重，进程重启后从 cursor 继续；首次没有 cursor 时只初始化可访问房间的最近历史，不把历史之外的数据当成已存在。`dashboard/lib/events/hub.ts` 为同一 Node 进程中的 SSE subscriber 提供有界队列，慢客户端被断开并可用 cursor 重连。

`dashboard/lib/events/sync-loop.ts` 在服务端单例运行长轮询：启动时发现 joined rooms，随后调用 Matrix sync，归一化、持久化、广播；Controller 状态以低频轮询补充。上游断开时记录 system error observation 并让 API/UI 进入 degraded 状态，恢复后继续从 cursor 同步。

### 4. Dashboard API

只在 `dashboard/app/api/` 新增这些 route：

| Route | Contract | Upstream action |
|---|---|---|
| `GET /api/workspace` | 返回 `{generatedAt, controller, rooms, runs, attention, capabilities}` | Controller snapshot + 已同步 Matrix projection |
| `GET /api/runs/{runId}` | 返回 `{run, messages, observations, workflow, artifacts, traceLinks}` | 根据确定的 room/run 关联返回真实数据 |
| `POST /api/runs/{runId}/messages` | 接收 `{text, threadRootEventId?}`，返回 `{accepted, eventId, txnId}` | 向该 run 的明确 Matrix room 发送消息 |
| `GET /api/rooms/{roomId}` | 返回未归类 room 的真实消息与 observation timeline | 展示尚未产生明确 workflow runId 的 Matrix room |
| `POST /api/rooms/{roomId}/messages` | 接收 `{text, threadRootEventId?}`，返回 `{accepted, eventId, txnId}` | 向已同步发现的真实 Matrix room 发送消息 |
| `GET /api/events` | SSE：`observation`, `run.updated`, `controller.updated`, `sync.status`；支持 `Last-Event-ID` | 订阅真实 sync loop/hub |
| `GET /api/matrix/media` | 接收一个经校验的 MXC URI，流式返回媒体 | 服务端带 Matrix token 下载，禁止任意 URL 代理 |

API 必须明确返回 401/403/502/503 以及上游错误，不用 200 空成功掩盖鉴权或连接问题。`POST` 发送成功只代表 Matrix 接收成功；消息最终显示以 sync 回来的 event 为准。

## File Map

实现会新增以下文件，全部位于 `dashboard/`：

```text
dashboard/
├── app/
│   ├── api/
│   │   ├── events/route.ts
│   │   ├── matrix/media/route.ts
│   │   ├── rooms/[roomId]/route.ts
│   │   ├── rooms/[roomId]/messages/route.ts
│   │   ├── runs/[runId]/route.ts
│   │   ├── runs/[runId]/messages/route.ts
│   │   └── workspace/route.ts
│   ├── globals.css
│   ├── layout.tsx
│   ├── page.tsx
│   └── loading.tsx
├── components/
│   ├── activity-rail.tsx
│   ├── room-thread.tsx
│   ├── assistant-runtime-provider.tsx
│   ├── attention-panel.tsx
│   ├── event-card.tsx
│   ├── run-list.tsx
│   ├── run-thread.tsx
│   ├── tool-call-card.tsx
│   ├── workflow-graph.tsx
│   └── workspace-shell.tsx
├── lib/
│   ├── config.ts
│   ├── types.ts
│   ├── controller/client.ts
│   ├── events/hub.ts
│   ├── events/normalizer.ts
│   ├── events/store.ts
│   ├── events/sync-loop.ts
│   ├── matrix/client.ts
│   ├── matrix/types.ts
│   └── runs/projection.ts
├── tests/
│   ├── controller-client.test.ts
│   ├── matrix-client.test.ts
│   ├── normalizer.test.ts
│   ├── projection.test.ts
│   ├── store.test.ts
│   └── fixtures/
├── Dockerfile
├── README.md
├── .env.example
├── next-env.d.ts
├── next.config.ts
├── package.json
├── tsconfig.json
└── vitest.config.ts
```

## Implementation Tasks

### Task 1: Scaffold the isolated Dashboard application

Files: `dashboard/package.json`, `dashboard/tsconfig.json`, `dashboard/next.config.ts`, `dashboard/vitest.config.ts`, `dashboard/next-env.d.ts`, `dashboard/app/layout.tsx`, `dashboard/app/page.tsx`, `dashboard/app/globals.css`, `dashboard/.env.example`, `dashboard/Dockerfile`, `dashboard/README.md`.

- [ ] Create the Next.js TypeScript app in `dashboard/` and pin a lockfile-compatible dependency set containing `next`, `react`, `react-dom`, `@assistant-ui/react`, `@xyflow/react`, `lucide-react`, and Vitest tooling.
- [ ] Set the container command to run the production Next server on port `3000`; document the existing deployment seam as `DASHBOARD_CONTEXT=dashboard`, without editing the root Makefile.
- [ ] Document required server-only variables: `AGENTTEAMS_CONTROLLER_URL`, `AGENTTEAMS_AUTH_TOKEN`, `NEXT_PUBLIC_MATRIX_API_URL` (read server-side), `AGENTTEAMS_ADMIN_USER`, `AGENTTEAMS_ADMIN_PASSWORD`, optional `AGENTTEAMS_MATRIX_TOKEN`, `AGENTTEAMS_DASHBOARD_DATA_DIR`, and existing storage/trace metadata variables. `.env.example` contains names and safe descriptions only.
- [ ] Add a minimal initial `/` shell that has no seeded conversation and clearly states when upstream data has not loaded.

Verify: `cd dashboard && npm install && npm run typecheck && npm run build`; `git diff --name-only -- dashboard` contains only Dashboard files.

### Task 2: Add server configuration and upstream clients

Files: `dashboard/lib/config.ts`, `dashboard/lib/types.ts`, `dashboard/lib/matrix/types.ts`, `dashboard/lib/matrix/client.ts`, `dashboard/lib/controller/client.ts`, `dashboard/tests/matrix-client.test.ts`, `dashboard/tests/controller-client.test.ts`.

- [ ] Implement strict environment parsing with descriptive startup/request errors and no credential logging.
- [ ] Implement Controller requests, response validation, auth header handling, timeout and upstream error mapping.
- [ ] Implement Matrix login/token caching, joined-room discovery, sync, history, send, media download and safe URL encoding. Keep the token in the server module only.
- [ ] Parse complete Matrix event envelopes, including edits, threads, workflow metadata, tool-like message payloads, and media metadata without throwing on unknown event types.
- [ ] Test exact request paths/methods, auth behavior, timeout/error mapping, token non-leakage, pagination, and send transaction id generation using local HTTP test servers only inside tests.

Verify: `cd dashboard && npm test -- tests/matrix-client.test.ts tests/controller-client.test.ts && npm run typecheck`.

### Task 3: Build normalization, correlation, persistence and live sync

Files: `dashboard/lib/events/normalizer.ts`, `dashboard/lib/events/store.ts`, `dashboard/lib/events/hub.ts`, `dashboard/lib/events/sync-loop.ts`, `dashboard/lib/runs/projection.ts`, `dashboard/tests/normalizer.test.ts`, `dashboard/tests/store.test.ts`, `dashboard/tests/projection.test.ts`, `dashboard/tests/fixtures/*`.

- [ ] Define the `AgentTeamsEvent` union and source references in `lib/types.ts`; keep the normalized shape stable for UI/API consumers.
- [ ] Implement redaction, body/summary size bounds, Matrix edit resolution, workflow parsing, tool-call/result parsing, artifact parsing and actor-role labeling.
- [ ] Implement the explicit room/run correlation order and an unclassified timeline path. Add tests for ambiguous project/task data proving that no run is guessed.
- [ ] Implement persistent cursor, atomic writes, idempotent event insertion, restart recovery and bounded retention of normalized observations. Test duplicate events and a failed write without corrupting the last good state.
- [ ] Implement a singleton long-poll loop that syncs Matrix, polls Controller health/status at a lower cadence, writes observations and broadcasts events to SSE subscribers. Expose connection state as `connecting`, `live`, `degraded`, or `stopped`.
- [ ] Derive run summaries, active workflow steps, attention items and artifact references from the normalized store; only include a run when its id/room relationship is explicit.

Verify: `cd dashboard && npm test -- tests/normalizer.test.ts tests/store.test.ts tests/projection.test.ts && npm run typecheck`.

### Task 4: Expose the real Dashboard API

Files: `dashboard/app/api/workspace/route.ts`, `dashboard/app/api/runs/[runId]/route.ts`, `dashboard/app/api/runs/[runId]/messages/route.ts`, `dashboard/app/api/events/route.ts`, `dashboard/app/api/matrix/media/route.ts`.

- [ ] Implement workspace snapshot from the controller client and event/run projections; return empty arrays only when the real source has no records.
- [ ] Implement run detail with chronological messages, workflow snapshots, observation timeline, artifacts and trace-link metadata that actually exists in the source.
- [ ] Validate outgoing message text, resolve the run to one explicit Matrix room, send through Matrix, and return the real Matrix event id/transaction id.
- [ ] Implement SSE event framing, heartbeat, `Last-Event-ID` replay from the store, cleanup on disconnect, and degraded sync status.
- [ ] Implement MXC media proxy with allowlisted Matrix host/path parsing, response content type forwarding and no arbitrary outbound URL support.
- [ ] Add route-level tests for empty/live/degraded states, 401/403/502/503 mapping, message validation, room resolution and media URL rejection.

Verify: `cd dashboard && npm test && npm run typecheck`; run the app with configured real endpoints and confirm `/api/workspace` reports actual upstream reachability.

### Task 5: Implement the chat-first product shell

Files: `dashboard/app/page.tsx`, `dashboard/components/workspace-shell.tsx`, `dashboard/components/run-list.tsx`, `dashboard/components/run-thread.tsx`, `dashboard/components/assistant-runtime-provider.tsx`, `dashboard/components/event-card.tsx`, `dashboard/components/tool-call-card.tsx`, `dashboard/components/attention-panel.tsx`, `dashboard/components/activity-rail.tsx`.

- [ ] Build a three-zone workspace: run/inbox rail, central conversation, and execution/attention rail. Room ids remain secondary metadata; the primary navigation is run/conversation selection.
- [ ] Map the normalized server state into assistant-ui `ThreadMessageLike` data and use `ExternalStoreRuntime`, because messages are owned by the Matrix/event store rather than by an assistant-ui model runtime.
- [ ] Send composer submissions through `POST /api/runs/{runId}/messages`; show a pending send state and reconcile the visible message only after the real Matrix event arrives through SSE.
- [ ] Render user, manager and worker messages with readable actor labels, timestamps, reply/thread indicators, Matrix edits, markdown-safe text, media artifacts and source event links.
- [ ] Render workflow and tool observations as compact expandable cards inside the conversation. Tool details default to a safe summary; raw args/results are never the default view.
- [ ] Add search/filter over loaded real observations, unread/attention markers, retry/reconnect controls, and clear empty/loading/degraded/error states.
- [ ] Keep client state local to the selected run and current snapshot; do not put tokens or raw upstream credentials in the client store.

Verify: `cd dashboard && npm run lint && npm run typecheck && npm run build`; manually verify that a browser with no upstream data shows an honest empty state rather than sample messages.

### Task 6: Implement execution graph and observability presentation

Files: `dashboard/components/workflow-graph.tsx`, `dashboard/app/globals.css`, and the event card files from Task 5.

- [ ] Convert explicit WorkerFlow `steps`, `subagents` and `dependsOn` data into React Flow nodes/edges with stable ids; do not infer edges from message order.
- [ ] Highlight current, waiting, done, failed and retrying states; clicking a node filters the activity rail to source observations for that node/run.
- [ ] Show controller health, active workers, sync lag/last event time, source type, and attention items with real values or “unavailable” labels.
- [ ] Show event timeline entries with source (`Matrix`/`Controller`), event id/endpoint, actor, phase, status and timestamp. Trace id is shown only when received; no fabricated duration/token/cost numbers.
- [ ] Apply the approved visual direction: quiet dark canvas, high-contrast readable typography, restrained amber/lime accent, thin borders, compact density, deliberate status colors, keyboard-visible focus and reduced-motion support. Avoid generic dashboard card grids and decorative charts with no source data.

Verify: `cd dashboard && npm run lint && npm run typecheck && npm run build`; inspect the UI with workflow data from a real Matrix room and with a room that has no workflow card.

### Task 7: Real-environment acceptance and handoff

Files: `dashboard/README.md` and only Dashboard files if a correction is required.

- [ ] Add a documented smoke procedure that requires real `AGENTTEAMS_CONTROLLER_URL`, Matrix URL and credentials; the procedure must fail fast when variables are absent and must not fall back to fixtures.
- [ ] Exercise: initial workspace load, room/run history, live Matrix event arrival, workflow edit (`m.replace`), tool call/result rendering, artifact media access, user message send, controller degradation and reconnect.
- [ ] Run `npm test`, `npm run lint`, `npm run typecheck`, `npm run build`, and `git diff --check` from `dashboard/`.
- [ ] Confirm `git status --short` shows no modifications to the existing Testweaver files or any core directory; report any required integration change instead of making it.
- [ ] Do not claim trace coverage beyond the real source fields observed during acceptance; document any missing upstream read API as a bounded limitation.

## Definition of Done

- A user can open one Dashboard page, select a real active run/conversation, read the Matrix history, send a message, and see the sent event reconciled from Matrix.
- The same page shows real WorkerFlow progress, tool-call summaries/results, artifacts, controller status, attention items and an event timeline without room switching.
- A browser refresh and Dashboard process restart preserve cursor/normalized observations without duplicate messages.
- Controller/Matrix outage is visible as degraded state and never appears as a successful empty run.
- No runtime mock data exists; all visible run/message/workflow/tool data is sourced from the configured AgentTeams interfaces.
- Only `dashboard/` is changed, and all checks pass before handoff.
