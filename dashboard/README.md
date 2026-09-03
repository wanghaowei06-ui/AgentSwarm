# AgentTeams Dashboard

AgentTeams 的产品化 workspace 前端：把现有 Matrix room 中的消息、workflow、tool call、artifact 和 system observation 聚合到一个当前会话界面，并通过 Controller API 补充运行状态。

这个目录只负责前端与 server-side adapter。它不修改 AgentTeams 核心运行时，也不生成演示数据：页面展示的内容必须来自 Matrix 或 Controller 的真实接口。

## 本地运行

```bash
cp .env.example .env.local
# 编辑 .env.local，填入真实 Controller / Matrix 地址和凭证
npm ci
npm run dev
```

打开 <http://localhost:3000>。Dashboard 服务端会读取 `.env.local`，凭证不会进入浏览器；Matrix 可以使用固定 `AGENTTEAMS_MATRIX_TOKEN`，也可以使用现有 AgentTeams 的 `AGENTTEAMS_ADMIN_USER` / `AGENTTEAMS_ADMIN_PASSWORD` 登录获取 token。

生产构建后可用 `npm run start` 启动 standalone server。

从 AgentTeams 根目录构建本目录时，使用现有 context seam：

```bash
DASHBOARD_CONTEXT=dashboard make build-dashboard
```

本实现不改根目录 Makefile、安装脚本或 AgentTeams 核心目录。

## 生产容器

```bash
docker build -t agentteams-dashboard:local .
docker run --rm -p 3000:3000 \
  --env-file .env.local \
  -v agentteams-dashboard-db:/app/db \
  agentteams-dashboard:local
```

`/app/db/state.json` 保存事件游标、有限长度事件投影、Dashboard 项目房间记录和最近 Controller snapshot。生产环境应挂载持久卷，避免重启后重新 hydration 全部 room history。项目记录只在真实 Matrix `createRoom` 返回 room ID 后逐步写入；多房间创建失败会保留已创建的真实 room，并标记为 `failed`。

## 数据路径

- `GET /api/workspace`：返回原生 Manager conversations、Dashboard projects、可邀请的真实 Manager/Leader/Worker participants、关联 rooms、runs、attention、sync 和 Controller 状态。
- `POST /api/projects`：创建 Dashboard 项目空间或复用 Manager 私聊。请求体只能是以下两种真实操作：

  ```json
  { "kind": "manager-dm" }
  { "kind": "project", "name": "材料核验", "roomNames": ["主讨论", "交付"], "inviteUserIds": ["@worker:example.test"] }
  ```

  Manager 和邀请对象由服务端从当前 Controller 快照校验；服务端随后调用 Matrix `createRoom`，浏览器不会接触任何 Matrix 或 Controller 凭证。
- `GET /api/projects/:projectId`：返回项目已持久化真实 room 的聊天、Agent 协作、Skill/工具调用、异常证据、产物和 sync 状态。
- `POST /api/projects/:projectId/messages`：将消息发送到该项目真实 Manager room；只有 `active` 项目可以发送。
- `GET /api/conversations/:conversationId`：返回一次 Manager 对话的消息、Agent 协作、Skill/工具调用、异常证据、产物和关联 rooms。
- `POST /api/conversations/:conversationId/messages`：将用户消息写入该对话的 Manager primary Matrix room。
- `GET /api/runs/:runId`：返回单个 run 的聊天消息、完整 observation timeline、workflow、artifact 和 attention。
- `POST /api/runs/:runId/messages`：将用户消息写入该 run 对应的 Matrix room。
- `GET /api/rooms/:roomId`：返回没有明确 runId 的真实 Matrix room timeline，不把它猜测成 run。
- `POST /api/rooms/:roomId/messages`：向已同步发现的真实 Matrix room 发送消息。
- `GET /api/events`：SSE；转发持久化后的真实 observation、run、Controller 和 sync 更新。
- `GET /api/matrix/media?mxc=...`：在服务端代理 Matrix artifact 下载，不把 Matrix token 暴露给浏览器。

Matrix structured event 目前识别 `agentteams.workflow`、`agentteams.tool` / `agentteams.tool_call`、`agentteams.skill` / `agentteams.skill_call`，普通 `m.room.message` 和媒体事件也会保留；未知事件会以 system observation 记录。敏感字段在写入观测详情前会被裁剪或脱敏。页面默认优先显示协作、Skill、工具和异常证据，普通聊天消息作为上下文保留。

## 验证

```bash
npm test
npm run typecheck
npm run lint
npm run build
```

如果没有配置真实上游，页面会明确显示未连接状态，不会退回 mock 数据。
