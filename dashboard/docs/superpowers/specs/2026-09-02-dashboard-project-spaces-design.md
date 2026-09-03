# AgentTeams Dashboard 项目空间与 Manager 私聊设计

**状态：** 已在 2026-09-02 由用户确认方向与方案。

## 目标

在不修改 AgentTeams 核心运行时的前提下，让 Dashboard 能够：

1. 用简短、可读的摘要呈现 Manager Inbox，不把 `PHASE-REPORT`、`NO_REPLY`、`room.meta` 等内部噪音直接铺在列表里。
2. 区分 Controller 管理的原生 Manager 会话与 Dashboard 用户创建的项目空间。
3. 通过真实 Matrix Client-Server API 创建 Manager 私聊和一个包含多个自定义房间的项目。
4. 在刷新或 Dashboard 重启后保留用户创建的项目，并继续从真实 Matrix timeline 读取消息。

## 范围与约束

- 所有实现只位于 `dashboard/`；不修改 Controller、Manager、Worker、TeamHarness、根目录 Makefile 或部署脚本。
- 不创建 mock server、seed data、示例消息或虚假的 Agent/Project/Task 状态。页面上的新项目记录只代表用户实际发起并由 Matrix 返回的房间创建操作。
- Dashboard 项目是 Dashboard 的组织层，不等同于 AgentTeams 原生 `projectflow` Project。第一版不调用 TeamHarness 工具，也不自动创建 Task、Team 或 Worker。
- Manager 和可邀请 Agent 必须来自当前真实 Controller 数据；服务端拒绝未知 Matrix 用户，避免界面成为任意邀请代理。
- Matrix access token、Controller token、管理员密码只停留在服务端；项目元数据可以写入 Dashboard 已有的 `state.json`。

## 用户模型

### Manager Inbox

左侧使用 `项目与私聊` 作为可读标题，副文案为“按项目查看 Manager 与协作房间”。列表分成两个来源：

- `Projects`：Dashboard 用户创建的项目空间，显示项目名、状态、房间数、Agent 数和最近一条可读消息。
- `Manager inbox`：从 Controller 投影出的原生 Manager 会话，保留当前 AgentTeams 的真实关联 rooms。

每条列表项的摘要优先选择关联房间中最近的普通消息，跳过以下内容：

- 以 `PHASE-REPORT` 开头的阶段报告；
- 去掉空白后等于 `NO_REPLY` 的消息；
- `room.meta event` 等结构化 room 状态事件；
- 仅包含内部心跳或系统标记的事件。

如果没有可读消息，显示短状态文案，例如“等待 Manager 消息”或“正在创建房间”。摘要统一折叠空白并截断到 96 个字符，完整内容仍只在中央时间线中查看。

### 新建 Manager 私聊

点击“Manager 私聊”后，服务端使用当前真实 Manager 的 Matrix user ID 查找当前用户与该 Manager 的已加入房间。若存在恰好包含双方的私聊则复用；否则调用 Matrix `createRoom`，使用 `trusted_private_chat`、`is_direct: true` 并邀请 Manager。成功后将其作为 `manager-dm` Dashboard project 显示在 Inbox 中。

### 新建项目

创建表单只要求项目名称和一个或多个房间名称，并可从 Controller 当前返回的 Manager/Worker/Leader Matrix user ID 中选择邀请对象。服务端始终把当前 Manager 邀请到项目的 Manager 私聊和项目房间；创建者（当前 Dashboard Matrix 账号）由 Matrix 自动作为创建成员。

项目创建顺序如下：

1. 生成 Dashboard-local project ID，并写入 `provisioning` 项目记录。
2. 创建一个 `is_direct: true` 的 Manager 私聊房间。
3. 按用户输入顺序创建项目房间，设置真实房间名并邀请 Manager 与选中的真实 Agent。
4. 每得到 Matrix 返回的 `room_id` 就持久化对应房间，全部成功后将项目状态改为 `active`。

Matrix 没有跨多个 `createRoom` 调用的事务。如果中途失败，Dashboard 保留已返回的真实 room ID，将项目标为 `failed`，显示失败原因和已创建房间数量；不会把它伪装成 active，也不会静默丢弃可能需要人工处理的真实房间。此次不自动删除或离开房间，因为那不是可靠的跨服务器回滚。

## 数据模型

在现有 `EventStoreSnapshot` 中增加可向后兼容的 `projects` 数组。旧的 `state.json` 缺少该字段时按空数组读取。

```ts
type DashboardProjectStatus = "provisioning" | "active" | "failed";
type DashboardProjectKind = "project" | "manager-dm";

type DashboardProjectRoom = {
  roomId: string;
  name: string;
  kind: "manager" | "project";
  inviteUserIds: string[];
  createdAt: string;
};

type DashboardProject = {
  id: string;
  kind: DashboardProjectKind;
  name: string;
  status: DashboardProjectStatus;
  managerUserId: string;
  managerRoomId?: string;
  rooms: DashboardProjectRoom[];
  createdAt: string;
  updatedAt: string;
  error?: string;
};
```

`WorkspaceSnapshot` 增加 `projects` 的轻量摘要；项目详情使用独立的 `/api/projects/:projectId`，但返回的消息、证据、artifact 和 attention 结构与现有 Manager conversation detail 保持一致，中央聊天组件可以复用。

项目的事件范围只包含其已持久化的 room ID。项目 Manager room 是中央发送消息的目标；其他项目房间作为关联协作时间线和证据来源。事件关联依赖真实 room ID，不通过消息文本猜测项目归属。

## 服务端接口

### Matrix client 扩展

`MatrixClient` 增加以下服务端方法：

- `whoAmI()`：调用 `GET /_matrix/client/v3/account/whoami`，在固定 token 未提供用户名时确定当前账号。
- `roomMembers(roomId)`：从已读取的 room state 中提取真实 `m.room.member` 成员。
- `createRoom(options)`：调用 `POST /_matrix/client/v3/createRoom`，支持 `name`、`invite`、`preset`、`is_direct`，严格校验返回的 `room_id`。

请求路径使用现有安全编码和错误映射；不把 token 写入返回值、项目记录或日志。

### Dashboard routes

- `GET /api/workspace`：在已有响应中增加 `projects` 摘要。
- `POST /api/projects`：接受以下两种请求：

  ```json
  { "kind": "manager-dm", "managerUserId": "optional-real-id" }
  { "kind": "project", "name": "项目名称", "roomNames": ["主讨论", "交付"], "inviteUserIds": ["optional-real-ids"], "managerUserId": "optional-real-id" }
  ```

  服务端从 Controller 验证 Manager 与可邀请 Agent，创建真实房间并返回 `{ project, reused }`。无 Manager 时返回明确的 409/503；输入不合法返回 400；Matrix 鉴权/上游错误沿用现有 401/403/502 映射。

- `GET /api/projects/:projectId`：返回项目及其真实房间聚合的消息、observations、evidence、artifacts、attention 和 sync 状态。
- `POST /api/projects/:projectId/messages`：将用户输入发送到该项目的真实 Manager room；项目尚未 active 或没有 Manager room 时拒绝发送。

新建操作必须在服务端执行，浏览器只发送名称、选择和消息文本，不接触 Matrix 凭证。

## 前端结构

`WorkspaceShell` 的 selection 扩展为 `conversation` 或 `project`。左侧新增两个动作按钮和项目列表；创建成功后自动选中新项目并刷新真实 workspace snapshot。创建过程中按钮禁用并显示状态，失败时保留错误提示而不清空已有会话。

现有 `ConversationThread` 抽取或复用为同时消费 `ConversationDetail` 与项目详情的中央消息流。项目中央输入框仍只向 Manager room 发送，关联项目房间的消息以真实 actor、room 标签和时间线证据展示。

项目创建弹窗使用现有 CSS 和 Lucide 图标，不引入新 UI 依赖。房间名称输入支持增删行；邀请列表只渲染服务端快照中可验证的 Matrix user ID 和已有 display name。所有 loading、empty、degraded、failed 状态均来自真实请求结果。

## 测试与验收

新增或扩展以下测试：

- Inbox 摘要测试：阶段报告、`NO_REPLY`、结构化 room event 不会进入摘要；普通消息会折叠空白并在超过 96 字符时截断。
- Matrix client 测试：`whoAmI`、room state 成员解析、`createRoom` 的准确 HTTP method/path/body、鉴权失败和缺少 `room_id` 的错误。
- Event store 测试：旧 state 无 `projects` 时迁移为空数组；provisioning、逐房间持久化、active/failed 状态可恢复。
- Project projection 测试：只聚合记录中的真实 room ID，项目之间不会串消息；Manager room 是发送目标。
- API 测试：非法名称、未知邀请人、无 Manager、Matrix 失败、重复 DM 复用和成功创建的状态码/响应。

真实环境验收标准：

1. 左侧不再显示完整 `PHASE-REPORT` 或 `NO_REPLY`，普通最新消息最多 96 个字符。
2. 点击 Manager 私聊后，已有双方 DM 被复用；没有时 Matrix 新增一个真实 direct room，并在页面出现独立条目。
3. 创建包含两个房间的项目后，Matrix 返回两个真实项目 room ID，Dashboard 刷新后仍显示同一项目和房间数。
4. 从项目条目发送消息后，消息通过真实 Matrix 返回并最终由 sync timeline 显示。
5. Dashboard 重启不丢项目；Matrix/Controller 不可用时显示真实失败或降级状态，不显示演示数据。
