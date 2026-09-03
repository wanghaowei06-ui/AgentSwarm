# TestWeaver runtime configuration reference

本文件只收口 `REAL-AGENTLOOP-OTEL-010` 的配置前置。它不迁入旧
adapter，不启动 M0，不调用模型，不查询 AgentLoop，也不发送 Trace。

## 受控引用

路径引用集中在
[`testweaver/config/runtime.env`](../config/runtime.env)，该文件
只含非敏感的宿主路径和已存在容器名：

- AgentTeams 核心环境：`/etc/agentteams/agentteams.env`
- AgentTeams provider：`/etc/agentteams/providers.env`
- AgentLoop-facing LoongSuite 配置：`/root/.loongsuite-pilot/config.json`
- 旧部署已验证的 OTel 配置路径：
  `/root/projects/muti-agent/deploy/otel/g9-collector.yaml`
- Nacos 变量来源：现有 `agentteams-controller` 容器
- AgentTeams Manager 端点来源：现有 `agentteams-manager` 容器

两份 `/etc/agentteams/*.env` 与 LoongSuite 配置均由部署持有，当前权限为
`root:root`、`0600`。preflight 只检查文件元数据和变量名；不会复制、解析、
打印或写回其中的值。OTel 文件只作为只读外部引用，不在本仓库保存副本。

## 官方 AgentTeams 对齐

当前 Manager 启动入口是
[`start-manager-agent.sh`](../../manager/scripts/init/start-manager-agent.sh)：

- `AGENTTEAMS_MANAGER_RUNTIME` 只沿用官方的 `openclaw` 或 `copaw` 运行时
  选择；本次不改它。
- `AGENTTEAMS_RUNTIME` 沿用部署现有的运行模式；本次不改它。
- OpenClaw 分支最终执行 `openclaw gateway run --verbose --force`。
- CoPaw 分支由同一入口转到 `start-copaw-manager.sh`。

本次 names-only M0 合同见
[`agentteams-required-vars.txt`](../config/agentteams-required-vars.txt)。
它只列出当前启动所需的变量名，包括 Matrix、AI Gateway、provider、Manager
凭据和注册前置；不包含任何值，也不新增模型、推理强度或账号配置。

## Preflight

默认检查已存在 Manager/Controller 容器的端点可达性；检查是 HTTP 只读探测，
只输出端点逻辑名和可达性/原因，不输出 URL、Header、Token 或响应正文：

```bash
./scripts/testweaver-config-preflight.sh
```

仅做元数据和变量名检查时：

```bash
./scripts/testweaver-config-preflight.sh --no-network
```

需要对未来获准的 M0 Manager 容器做同样检查时，传入容器名即可；脚本不会启动
或重启该容器：

```bash
./scripts/testweaver-config-preflight.sh --manager-container <existing-manager-container>
```

退出码 `0` 只表示 AgentTeams 的 M0 引用前置通过；`2` 表示核心引用、变量名或
端点前置缺失。`DEFERRED` 不会被伪装成 `READY`。

## AgentLoop / OTel / Nacos 边界

- LoongSuite 配置路径可复用，但 preflight 不读取其正文；只有查询前置被验证，
  不执行 AgentLoop query。
- 旧 `tw-g9-otel-collector` 仅留下只读配置路径，collector 未运行时报告
  `DEFERRED`；脚本不会启动它。
- Nacos 只从已有 Controller 容器的
  `AGENTTEAMS_NACOS_REGISTRY_URI` 或 `AGENTTEAMS_NACOS_HOST`/
  `AGENTTEAMS_NACOS_PORT` 变量名定位，并做无正文的只读可达性检查；不读取或
  回显认证值。
- 只有同一真实 Hero 完成允许的 M0 闭环后，才可进入 AgentLoop query/Trace
  阶段。Trace 必须来自该真实运行；synthetic、fixture、旧收据或未绑定 live
  事件都不能冒充 LIVE。

当前 preflight 的输出应按 `REUSED`、`GAP`、`DEFERRED` 和
`READY scope=m0-reference` 解读；它不是 M0 执行器，也不是 Trace 发送器。
