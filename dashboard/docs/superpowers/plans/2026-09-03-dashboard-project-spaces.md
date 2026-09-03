# Dashboard project spaces and Manager DMs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Dashboard 中把 Manager Inbox 压缩成可读的项目/私聊列表，并通过真实 Matrix 创建、持久化和使用 Dashboard 项目空间。

**Architecture:** 保留现有 Controller conversation projection，同时在 Dashboard event store 中增加用户创建的 `DashboardProject` 记录。服务端通过 Matrix `whoami`、room state 和 `createRoom` 完成真实的 Manager DM 与项目房间生命周期；项目的消息详情继续复用现有 conversation timeline 结构，浏览器只调用 Dashboard API，不接触凭证。

**Tech Stack:** Next.js App Router、React 19、TypeScript、原生 Matrix Client-Server API、现有 EventStore/SSE、Vitest、现有 CSS 和 lucide-react。

**Spec:** `dashboard/docs/superpowers/specs/2026-09-02-dashboard-project-spaces-design.md`

## Global Constraints

- 所有实现只能修改或新增 `dashboard/` 文件；不得修改 AgentTeams Controller、Manager、Worker、TeamHarness、根目录 Makefile、安装脚本或并行推进的 Testweaver 文件。
- 不添加 mock server、seed data、demo project、默认房间或虚假消息；页面只能展示 Controller 返回、Matrix 返回或用户真实创建并持久化的项目记录。
- Matrix access token、Controller token、管理员密码只在 Dashboard 服务端使用，不能进入浏览器状态、HTML、SSE payload 或项目记录。
- Dashboard project 只是 Dashboard 组织层；第一版不调用 TeamHarness `projectflow`，不创建原生 AgentTeams Project/Task/Team/Worker。
- Manager 和可邀请 Agent 必须来自当前真实 Controller 数据；未知 Matrix user ID 返回 400，不向任意地址发邀请。
- Matrix 的多房间创建不是事务；中途失败必须保留已返回的真实 room ID 并标记项目 `failed`，不能把部分创建伪装成 `active`。
- 每个任务先写失败测试并观察正确的 RED，再实现最小代码使其 GREEN；每个任务结束运行该任务列出的验证命令。

---

### Task 1: Compact inbox previews and persist Dashboard projects

**Files:**
- Create: `dashboard/lib/inbox/preview.ts`
- Modify: `dashboard/lib/types.ts`
- Modify: `dashboard/lib/events/store.ts`
- Modify: `dashboard/lib/conversations/projection.ts`
- Test: `dashboard/tests/inbox-preview.test.ts`
- Test: `dashboard/tests/store.test.ts`
- Test: `dashboard/tests/conversation-projection.test.ts`

**Interfaces:**
- Produces `compactInboxPreview(events: AgentTeamsEvent[], fallback: string): string` and `isInboxNoise(event: AgentTeamsEvent): boolean`.
- Produces `DashboardProject`, `DashboardProjectRoom`, `DashboardProjectStatus`, `DashboardProjectKind`, and `ConversationSource` types in `lib/types.ts`.
- `EventStoreSnapshot` gains `projects: DashboardProject[]`; `EventStore.init()` reads old state files with a missing `projects` field as `[]`.
- `EventStore` exposes `getProject(projectId)`, `createProject(project)`, and `updateProject(projectId, patch)`; `updateProject` returns the updated project or throws `project ... was not found`.
- Controller conversations set `source: "controller"`; project projections will set `source: "dashboard-project"` in later tasks.

- [ ] **Step 1: Write the failing inbox preview test**

```ts
it("omits internal phase and reply markers and truncates a readable message", () => {
  const result = compactInboxPreview([
    event("[PHASE-REPORT run-1] 13:02Z — worker is active\nNO_REPLY"),
    event("Manager   needs   the   final   receipt   " + "x".repeat(140)),
  ], "等待 Manager 消息");

  expect(result).toBe("Manager needs the final receipt xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx…");
  expect(result).not.toContain("PHASE-REPORT");
  expect(result).not.toContain("NO_REPLY");
  expect(result.length).toBeLessThanOrEqual(96);
});
```

- [ ] **Step 2: Run the focused test and verify it fails for the missing helper**

Run: `cd dashboard && npm test -- --run tests/inbox-preview.test.ts`

Expected: FAIL because `../lib/inbox/preview` and `compactInboxPreview` do not exist yet.

- [ ] **Step 3: Implement the minimal preview helper**

Implement `isInboxNoise` by returning true for `phaseReportInfo(event)`, `isStructuralRoomEvent(event)`, exact `NO_REPLY`, and system summaries matching internal heartbeat markers. For remaining events, collapse whitespace, remove a trailing standalone `NO_REPLY`, discard an empty result, and return at most 96 characters including the final ellipsis. Use the fallback only when no readable event remains.

- [ ] **Step 4: Run the focused preview test and verify it passes**

Run: `cd dashboard && npm test -- --run tests/inbox-preview.test.ts`

Expected: PASS with the phase report and `NO_REPLY` absent from the returned preview.

- [ ] **Step 5: Write the failing project persistence test**

```ts
it("loads projects as an empty list when reading a pre-project state file", async () => {
  await writeFile(statePath, JSON.stringify({ version: 1, events: [], sync: { state: "stopped" } }));
  const store = new EventStore({ dataDir });

  expect((await store.snapshot()).projects).toEqual([]);
});
```

- [ ] **Step 6: Run the focused persistence test and verify it fails for the missing field/methods**

Run: `cd dashboard && npm test -- --run tests/store.test.ts`

Expected: FAIL because `snapshot.projects` is not defined in the current store contract.

- [ ] **Step 7: Add the backward-compatible project state and mutation methods**

Add the exact project shape from the approved spec, initialize `projects: []` in `emptySnapshot`, merge `loaded.projects` only when it is an array, and implement `getProject`, `createProject`, and `updateProject` through the existing atomic `persist()` chain. `updateProject` must update `updatedAt` and must not accept a project ID that is not already present.

- [ ] **Step 8: Make controller conversation summaries use the compact helper**

Replace the direct `latestConversationEvent.summary` assignment in `conversationSummary` with `compactInboxPreview(scopedEvents, latest ? "最新执行进度已移到右侧证据栏" : "等待新的 Manager 会话事件")`, preserving the existing evidence-first fallback behavior. Add `source: "controller"` to the returned summary without changing existing room correlation.

- [ ] **Step 9: Run the persistence and projection tests**

Run: `cd dashboard && npm test -- --run tests/store.test.ts tests/conversation-projection.test.ts tests/inbox-preview.test.ts`

Expected: all focused tests PASS, including the existing assertion that a raw phase report does not become the Manager subtitle.

- [ ] **Step 10: Commit only the Dashboard model/projection task**

```bash
git add dashboard/lib/inbox/preview.ts dashboard/lib/types.ts dashboard/lib/events/store.ts dashboard/lib/conversations/projection.ts dashboard/tests/inbox-preview.test.ts dashboard/tests/store.test.ts dashboard/tests/conversation-projection.test.ts
git commit -m "feat(dashboard): compact inbox previews and store projects"
```

### Task 2: Add real Matrix room lifecycle and project provisioning

**Files:**
- Modify: `dashboard/lib/matrix/client.ts`
- Modify: `dashboard/lib/matrix/types.ts`
- Create: `dashboard/lib/projects/participants.ts`
- Create: `dashboard/lib/projects/provisioning.ts`
- Modify: `dashboard/lib/runtime.ts`
- Test: `dashboard/tests/matrix-client.test.ts`
- Create: `dashboard/tests/project-provisioning.test.ts`

**Interfaces:**
- `MatrixClient.whoAmI(): Promise<string>` calls `GET /_matrix/client/v3/account/whoami` and caches only the user ID in memory.
- `MatrixClient.roomMembers(roomId: string): Promise<MatrixRoomMember[]>` parses `m.room.member` state events into `{ userId, membership, displayName? }`.
- `MatrixClient.createRoom(options: { name: string; invite: string[]; preset?: string; isDirect?: boolean }): Promise<{ roomId: string }>` calls Matrix `POST /_matrix/client/v3/createRoom` and requires a non-empty returned `room_id`.
- `projectParticipants(controllerData, events): MatrixParticipant[]` returns deduplicated real Manager/Worker/Leader IDs with display names when observed.
- `DashboardProjectProvisioner.create(input)` returns `{ project: DashboardProject; reused: boolean }` and uses an injected Matrix client, EventStore, and current Controller data.

- [ ] **Step 1: Write the failing Matrix client tests**

Add tests that assert:

```ts
const result = await client.createRoom({
  name: "主讨论",
  invite: ["@manager:matrix.local"],
});

expect(result.roomId).toBe("!created:matrix.local");
expect(request.method).toBe("POST");
expect(request.url).toBe("/_matrix/client/v3/createRoom");
expect(request.body).toMatchObject({
  name: "主讨论",
  invite: ["@manager:matrix.local"],
  preset: "trusted_private_chat",
  is_direct: false,
});
```

Also add a `whoAmI` response test and a room-member state test with one joined member and one invite member.

- [ ] **Step 2: Run the Matrix focused tests and verify they fail for missing methods**

Run: `cd dashboard && npm test -- --run tests/matrix-client.test.ts`

Expected: FAIL because `MatrixClient` has no `createRoom`, `whoAmI`, or `roomMembers` methods.

- [ ] **Step 3: Implement the Matrix room methods with existing error handling**

Reuse `requestJson`, `encodePathSegment`, `MatrixUpstreamError`, and server-only bearer authentication. Map `isDirect` to `is_direct`, always use `trusted_private_chat` unless an explicit preset is passed by the service, and return only the Matrix room ID. Do not include the access token in errors or results.

- [ ] **Step 4: Run the Matrix focused tests and verify they pass**

Run: `cd dashboard && npm test -- --run tests/matrix-client.test.ts`

Expected: all Matrix tests PASS, including method/path/body, auth failure, invalid JSON, and missing `room_id` cases.

- [ ] **Step 5: Write the failing provisioning tests**

Cover these real behaviors with an in-memory fake Matrix source that records calls, not fake UI data:

```ts
it("creates one Manager DM and each requested project room", async () => {
  const result = await provisioner.create({
    kind: "project",
    name: "材料核验",
    roomNames: ["主讨论", "交付"],
    inviteUserIds: ["@worker:matrix.local"],
  });

  expect(result.project.status).toBe("active");
  expect(result.project.rooms.map((room) => room.name)).toEqual(["Manager 私聊", "主讨论", "交付"]);
  expect(matrix.createdRoomNames).toEqual(["Manager 私聊", "主讨论", "交付"]);
});

it("reuses an existing two-member Manager DM", async () => {
  const result = await provisioner.create({ kind: "manager-dm" });

  expect(result.reused).toBe(true);
  expect(matrix.createRoomCalls).toHaveLength(0);
});
```

Also cover an unknown invite ID returning a validation error and a second room creation failure producing a persisted `failed` project with the first room ID retained.

- [ ] **Step 6: Run the provisioning tests and verify they fail for the missing service**

Run: `cd dashboard && npm test -- --run tests/project-provisioning.test.ts`

Expected: FAIL because `DashboardProjectProvisioner` and the participant validator do not exist.

- [ ] **Step 7: Implement participant extraction and validation**

Read `/api/v1/managers`, `/api/v1/workers`, and `/api/v1/teams` records using the existing field aliases (`matrixUserID`/`matrixUserId`, `roomID`/`roomId`, `leaderDMRoomID`/`leaderDmRoomId`, and leader user ID aliases). Deduplicate by Matrix user ID. The Manager selected for a request must be one of the current Manager records; invite IDs must be in the participant set. Return a 409-level service error when no Manager exists.

- [ ] **Step 8: Implement DM reuse and multi-room provisioning**

Resolve the current Dashboard Matrix user through `whoAmI`, inspect joined rooms with `roomMembers`, and reuse only a room whose joined members are exactly the current user and the selected Manager. Persist a `provisioning` project before creating rooms, append each returned room through `updateProject`, mark `active` after all calls, and on any Matrix failure store the real error text and mark `failed`. The Manager must be included in every project room invite list; duplicate invite IDs must be removed before the Matrix request.

- [ ] **Step 9: Run provisioning tests and typecheck**

Run: `cd dashboard && npm test -- --run tests/matrix-client.test.ts tests/project-provisioning.test.ts && npm run typecheck`

Expected: PASS with no credential values in test output.

- [ ] **Step 10: Commit the Matrix/provisioning task**

```bash
git add dashboard/lib/matrix/client.ts dashboard/lib/matrix/types.ts dashboard/lib/projects/participants.ts dashboard/lib/projects/provisioning.ts dashboard/lib/runtime.ts dashboard/tests/matrix-client.test.ts dashboard/tests/project-provisioning.test.ts
git commit -m "feat(dashboard): provision real project rooms"
```

### Task 3: Project projection and real Dashboard API routes

**Files:**
- Create: `dashboard/lib/projects/projection.ts`
- Modify: `dashboard/lib/api/contracts.ts`
- Modify: `dashboard/lib/types.ts`
- Modify: `dashboard/lib/runs/projection.ts`
- Create: `dashboard/app/api/projects/route.ts`
- Create: `dashboard/app/api/projects/[projectId]/route.ts`
- Create: `dashboard/app/api/projects/[projectId]/messages/route.ts`
- Modify: `dashboard/app/api/workspace/route.ts`
- Test: `dashboard/tests/project-projection.test.ts`
- Create: `dashboard/tests/project-api-contracts.test.ts`

**Interfaces:**
- `projectConversation(project: DashboardProject, events: AgentTeamsEvent[], controllerData?: JsonObject): ConversationDetail & { project: DashboardProject }` aggregates only the project’s persisted room IDs and sends through `project.managerRoomId`.
- `projectConversationSummary(project, events, controllerData)` returns a `ConversationSummary` with `source: "dashboard-project"`, `projectId`, project status, room counts, real event counts, and `compactInboxPreview`.
- `buildWorkspaceSnapshot(snapshot)` returns `projects` as project summaries in addition to the existing Controller conversations.
- `POST /api/projects` returns `{ project, reused }`; `GET /api/projects/:projectId` returns project detail plus sync; `POST /api/projects/:projectId/messages` returns `{ accepted, eventId, txnId }`.

- [ ] **Step 1: Write the failing project projection test**

```ts
it("keeps project timelines isolated by persisted room IDs", () => {
  const detail = projectConversation(project, [
    event({ roomId: "!manager-project:matrix.local", summary: "Manager reply" }),
    event({ roomId: "!project-main:matrix.local", summary: "Project update" }),
    event({ roomId: "!other-project:matrix.local", summary: "Must not leak" }),
  ]);

  expect(detail.messages.map((item) => item.summary)).toEqual(["Manager reply", "Project update"]);
  expect(detail.conversation.managerRoomId).toBe("!manager-project:matrix.local");
});
```

- [ ] **Step 2: Run the focused projection test and verify it fails for missing projection**

Run: `cd dashboard && npm test -- --run tests/project-projection.test.ts`

Expected: FAIL because the project projection module does not exist.

- [ ] **Step 3: Implement project room summaries and detail projection**

Build `ConversationRoom` entries from the persisted Manager/project room records, use the existing event evidence classification and attention logic, sort observations chronologically, and use `compactInboxPreview` for the list summary. Add the `project` room role to `ConversationRoomRole` and existing room-role label maps. Never add events from unlisted room IDs.

- [ ] **Step 4: Run the focused projection test and verify it passes**

Run: `cd dashboard && npm test -- --run tests/project-projection.test.ts`

Expected: PASS, including the no-cross-project assertion.

- [ ] **Step 5: Write the failing API contract tests**

Add contract tests for `parseProjectBody`:

```ts
expect(() => parseProjectBody({ kind: "project", name: "", roomNames: ["主讨论"] })).toThrow("project name");
expect(() => parseProjectBody({ kind: "project", name: "P", roomNames: [] })).toThrow("at least one room");
expect(parseProjectBody({ kind: "manager-dm" })).toEqual({ kind: "manager-dm" });
```

Add route tests that assert unknown project IDs return 404, inactive projects reject message sends with 409, and successful sends call the project Manager room and return the real Matrix IDs.

- [ ] **Step 6: Run the API focused tests and verify they fail for missing contracts/routes**

Run: `cd dashboard && npm test -- --run tests/project-api-contracts.test.ts`

Expected: FAIL because project request parsing and routes do not exist.

- [ ] **Step 7: Implement strict project request parsing**

Accept `manager-dm` or `project`. For projects, require a trimmed name of 1–120 characters and 1–12 unique trimmed room names of 1–80 characters. Accept optional `managerUserId` and `inviteUserIds` only as strings; reject other values and return the existing `invalid_request` mapping. Keep response payloads free of credentials.

- [ ] **Step 8: Implement workspace and project routes with live Controller data**

For `POST /api/projects`, call the existing Controller client for current managers/workers/teams, pass the returned data into `DashboardProjectProvisioner`, and return the actual project record. For `GET /api/workspace`, include persisted project summaries and a real participant directory for the creation form. For project detail, call `projectConversation` from the store snapshot and return `sync`.

- [ ] **Step 9: Implement project message sending**

Parse the existing message body contract, resolve the project from the store, reject non-active or missing-Manager-room projects with 409, and call `runtime.matrix.sendMessage(project.managerRoomId, text, { threadRootEventId })`. Return only `accepted`, Matrix `eventId`, and `txnId`; publish a `project.updated` hub event after provisioning so other open clients refresh.

- [ ] **Step 10: Run projection/API tests and typecheck**

Run: `cd dashboard && npm test -- --run tests/project-projection.test.ts tests/project-api-contracts.test.ts tests/conversation-projection.test.ts && npm run typecheck`

Expected: PASS; existing Controller conversation behavior remains unchanged.

- [ ] **Step 11: Commit project projection/API task**

```bash
git add dashboard/lib/projects/projection.ts dashboard/lib/api/contracts.ts dashboard/lib/types.ts dashboard/lib/runs/projection.ts dashboard/app/api/projects dashboard/app/api/workspace/route.ts dashboard/tests/project-projection.test.ts dashboard/tests/project-api-contracts.test.ts
git commit -m "feat(dashboard): expose project workspace APIs"
```

### Task 4: Add compact Inbox UI and project creation flow

**Files:**
- Create: `dashboard/components/project-create-dialog.tsx`
- Modify: `dashboard/components/workspace-shell.tsx`
- Modify: `dashboard/components/conversation-thread.tsx`
- Modify: `dashboard/components/activity-rail.tsx`
- Modify: `dashboard/app/globals.css`
- Modify: `dashboard/lib/ui/actor.ts`
- Test: `dashboard/tests/navigation.test.ts`

**Interfaces:**
- `Selection` becomes `{ type: "conversation" | "project"; id: string }`.
- `ProjectCreateDialog` consumes `participants`, `submitting`, `error`, `onClose`, and `onSubmit({ name, roomNames, inviteUserIds })`.
- `WorkspaceShell` fetches `/api/conversations/:id` or `/api/projects/:id` based on selection and sends to the matching `/messages` route.
- The left Inbox uses `conversation.summary` and `project.summary` from the server; no client-side raw event concatenation is allowed.

- [ ] **Step 1: Write the failing UI data-shape test**

Extend the navigation test with the source labels used by the Inbox:

```ts
expect(conversationSourceLabels).toEqual({
  controller: "Manager inbox",
  "dashboard-project": "Projects",
});
```

- [ ] **Step 2: Run the focused UI contract test and verify it fails**

Run: `cd dashboard && npm test -- --run tests/navigation.test.ts`

Expected: FAIL because `conversationSourceLabels` is not defined.

- [ ] **Step 3: Implement the minimal source labels and compact Inbox markup**

Change the sidebar heading to `项目与私聊` and `按项目查看 Manager 与协作房间`. Render project and Controller entries in separate labeled sections. Replace `linked evidence` with `${roomCount} 个关联房间`, show only the server-provided compact summary, and add short `新建项目` and `Manager 私聊` actions near the heading.

- [ ] **Step 4: Run the focused UI contract test and verify it passes**

Run: `cd dashboard && npm test -- --run tests/navigation.test.ts`

Expected: PASS.

- [ ] **Step 5: Implement project creation dialog with real participant choices**

Create a form with one project name input, at least one room-name row, add/remove room controls, and checkboxes for the participant directory returned by `/api/workspace`. Do not hardcode Agent names. Keep Manager selected and disabled as a required invite; submit only the form values to `WorkspaceShell`.

- [ ] **Step 6: Wire Manager DM and project creation to the real routes**

The `Manager 私聊` action posts `{ kind: "manager-dm" }`; the dialog posts `{ kind: "project", name, roomNames, inviteUserIds }`. On success, call `refreshWorkspace`, select the returned ID, and fetch its detail. On failure, retain the existing selection and show the API message inline. While pending, disable actions and show `正在创建真实 Matrix 房间…`.

- [ ] **Step 7: Reuse the central conversation thread for projects**

Allow the thread detail state to consume the project detail shape because both expose `rooms`, `messages`, `observations`, `evidence`, `artifacts`, `attention`, and `sync`. Send from a project to `/api/projects/:projectId/messages`, and keep its central target as the project Manager room. Add the `project` room-role label in the evidence rail.

- [ ] **Step 8: Apply focused styling for a readable Inbox and modal**

Keep the existing dark canvas and accent system. Shorten sidebar copy, cap summaries with CSS line clamping as a secondary guard, style project/source labels as quiet section markers, and give the creation dialog visible focus rings, disabled state, error state, and responsive one-column layout. Do not reintroduce the removed central `Manager 对话`/Evidence summary toolbar.

- [ ] **Step 9: Run UI checks**

Run: `cd dashboard && npm test -- --run tests/navigation.test.ts && npm run lint && npm run typecheck`

Expected: PASS with no unused imports and no credential-related browser code.

- [ ] **Step 10: Commit the UI task**

```bash
git add dashboard/components/project-create-dialog.tsx dashboard/components/workspace-shell.tsx dashboard/components/conversation-thread.tsx dashboard/components/activity-rail.tsx dashboard/app/globals.css dashboard/lib/ui/actor.ts dashboard/tests/navigation.test.ts
git commit -m "feat(dashboard): add project and manager inbox UI"
```

### Task 5: Real-environment verification and handoff

**Files:**
- Modify: `dashboard/README.md`
- Modify: only Dashboard files if a verified correction is required

**Interfaces:**
- README documents the actual `POST /api/projects` payloads and server-only variables without including live credentials or room IDs.
- The running app remains available at the configured Dashboard port and uses the existing real Controller/Matrix environment.

- [ ] **Step 1: Run the complete automated verification suite**

Run:

```bash
cd dashboard
npm test -- --run
npm run typecheck
npm run lint
npm run build
git diff --check
```

Expected: every test passes, TypeScript and ESLint exit 0, Next production build succeeds, and `git diff --check` emits no whitespace errors.

- [ ] **Step 2: Start the production server with the existing real environment**

Use the already configured Controller URL/token, Matrix URL, admin credentials, `AGENTTEAMS_DASHBOARD_DATA_DIR`, and an unused local port. Do not print any token or password. Confirm `GET /`, `GET /api/workspace`, all HTML JS/CSS assets, and `GET /api/events` return successfully.

- [ ] **Step 3: Verify compact Inbox behavior against real events**

Open the page with the current live event store and confirm that the left summary does not contain the full `PHASE-REPORT`, trailing `NO_REPLY`, `room.meta`, or raw event IDs; it contains a short readable message or a short status fallback.

- [ ] **Step 4: Verify real Manager DM reuse/creation**

Click `Manager 私聊`, verify the response contains a real Matrix `room_id`, verify a second click reuses the same two-member room, and confirm the item appears as a separate Inbox entry after refresh.

- [ ] **Step 5: Verify a real multi-room project**

Create a project with two room names and at least one real Controller-known participant. Confirm Matrix receives one Manager DM create call plus two project room create calls, the returned room count is three, the project remains visible after a page refresh/restart, and a message sent from the project is eventually visible from the sync timeline.

- [ ] **Step 6: Verify failure and isolation states**

Exercise an invalid invite and an unavailable Matrix response through the API boundary; confirm the UI retains the current conversation, reports the real error, and does not add an active fake project. Confirm events from another project do not appear in the selected project timeline.

- [ ] **Step 7: Check the concurrent worktree boundary**

Run `git status --short` and confirm this task has only Dashboard paths staged/changed; do not stage, revert, or format any `testweaver/` or other core files.

- [ ] **Step 8: Commit the README/verification corrections if needed**

```bash
git add dashboard/README.md
git commit -m "docs(dashboard): document project workspace verification"
```
