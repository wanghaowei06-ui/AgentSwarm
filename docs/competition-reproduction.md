# AgentSwarm 比赛版复现指南

本文是 AgentSwarm 比赛提交版本的唯一复现入口。评委应从指定 tag 克隆源码，并在联网的 Docker 环境中从本仓库构建镜像、安装真实系统、使用真实的大模型 API 完成验证。

本指南解释如何复现系统；仓库来源、许可证、依赖和公开/排除范围分别见 [`NOTICE`](../NOTICE)、[`docs/dependencies.md`](dependencies.md) 和 [`docs/open-source-boundary.md`](open-source-boundary.md)。AgentSwarm 基于上游 [AgentTeams](https://github.com/agentscope-ai/AgentTeams)，但评委应以本仓库固定 tag 的源码和本次实时输出为准。

本版本的发行范围和已知限制见[competition-v1.3 发布说明](releases/competition-v1.3.md)。

本流程不使用 mock、离线回放或预录证据。大模型 API Key 只通过环境变量传入，不要写入仓库文件。

## 0. 评委执行顺序

评委可以按下面的顺序完成一次端到端复现：

1. 克隆仓库并切换到 `competition-v1.3`，确保评测使用固定源码，而不是会继续变化的 `main`；
2. 配置一个可联网调用的 Qwen 或 OpenAI-compatible LLM；
3. 构建本仓库的基础镜像和 embedded 真实系统；
4. 启动 Dashboard，并从 Element Web 登录；
5. 执行 `make verify` 和 `make test-installed TEST_FILTER="01"`；
6. 若要验证更高层能力，再运行完整集成测试并保存本次运行输出。

源码构建、服务启动和实时模型调用是同一条复现路径。只阅读静态文档或检查历史文件，不能替代实际运行。

## 1. 版本与复现边界

- 比赛快照：`competition-v1.3`
- 运行方式：源码构建 + embedded 部署
- 核心服务：AgentTeams Controller、Higress、Tuwunel、MinIO、Element Web、Manager
- 可选管理界面：从本仓库 `dashboard/` 源码构建的 AgentTeams Dashboard
- 外部依赖：一个可访问的 Qwen 或 OpenAI-compatible LLM API
- 可选测试依赖：GitHub PAT，仅在运行 GitHub 集成测试时需要
- 许可证：根目录 Apache License 2.0；第三方依赖按各自许可证使用
- 发行版身份：AgentSwarm 比赛发行版；运行时代码保留 AgentTeams 的真实命名契约
- 历史版本：`competition-v1.2`、`competition-v1.1` 仍保留为不可移动的旧比赛快照

仓库中的 `testweaver/evidence/` 是本地运行产物，`testweaver/config/runtime.env` 是受保护的部署配置；两者都不属于干净评委环境的启动输入，也不会提交到公开快照。评委应以本次启动和测试产生的实时结果为准。

公开快照保留真实 AgentTeams 源码、Dockerfile、Helm chart、安装脚本、Dashboard 源码和测试；不保留依赖目录、容器日志、运行时密钥、历史证据包或本地工作区。这样评委可以从一个干净克隆重新生成运行数据，并能明确区分源码能力与某次历史运行结果。

## 2. 环境要求

建议使用 Linux 或 macOS。Windows 评委可使用 WSL2，但以下步骤假定 Bash 环境。

需要安装并启动：

- Git
- Docker Engine 或 Docker Desktop，支持 BuildKit、`docker build` 和 Compose 兼容运行
- GNU Make、Bash、`curl`、`openssl`
- Ruby（构建 QwenPaw Worker 插件时由 Makefile 调用）
- Node.js 22+ 与 npm（仅在执行 Dashboard 前端源码检查时需要；Dashboard 镜像自身也使用 Node.js 22）

最低资源是 2 CPU / 4 GB RAM；建议 4 CPU / 8 GB RAM。源码构建和首次启动会下载多个基础镜像、npm/Python/Rust 依赖，需要稳定的外网访问和足够磁盘空间。

默认主机端口如下：

| 服务 | 端口 |
| --- | ---: |
| Higress Gateway | `18080` |
| Higress Console | `18001` |
| Element Web | `18088` |
| AgentTeams Dashboard | `13000` |

端口被占用时，在安装前设置对应的 `AGENTTEAMS_PORT_*` 环境变量即可。

## 3. 获取比赛源码

```bash
git clone https://github.com/wanghaowei06-ui/AgentSwarm.git
cd AgentSwarm
git checkout competition-v1.3
```

请不要使用仓库上游 README 中面向正式发布版的 `curl | bash` 安装命令来复现比赛快照；该命令会获取发布镜像，而不是构建当前提交中的源码。

## 4. 配置真实 LLM

下面以 Qwen 为例。将 API Key 放在当前终端的环境变量中，不要把真实值写入 `.env`、脚本或 Git。

```bash
export AGENTTEAMS_LLM_PROVIDER=qwen
export AGENTTEAMS_DEFAULT_MODEL=qwen3.5-plus
export AGENTTEAMS_LLM_API_KEY='替换为评委自己的模型 API Key'

export AGENTTEAMS_ADMIN_USER=admin
export AGENTTEAMS_ADMIN_PASSWORD='judge-local-password'

export AGENTTEAMS_NON_INTERACTIVE=1
export AGENTTEAMS_MOUNT_SOCKET=1
export AGENTTEAMS_MATRIX_E2EE=0
```

如果使用其他 OpenAI-compatible 服务，改为设置服务商要求的地址和模型：

```bash
export AGENTTEAMS_LLM_PROVIDER=openai-compat
export AGENTTEAMS_OPENAI_BASE_URL='https://your-provider.example/v1'
export AGENTTEAMS_DEFAULT_MODEL='your-model-id'
export AGENTTEAMS_LLM_API_KEY='替换为评委自己的模型 API Key'
```

API Key、管理员密码和第三方服务地址都属于本地运行配置，不应提交到 GitHub。

## 5. 从当前源码构建并安装真实系统

比赛版本使用统一的本地 tag，避免 Manager/Worker 误使用远程 `latest` 基础镜像：

```bash
export VERSION=competition-v1.3
export OPENCLAW_BASE_IMAGE=agentteams/openclaw-base
export OPENCLAW_BASE_VERSION=competition-v1.3

# 先构建本仓库中的 OpenClaw 基础镜像
make build-openclaw-base

# 构建 embedded 安装所需的真实镜像并安装系统
export AGENTTEAMS_DASHBOARD=0
make install-embedded
make wait-ready-embedded
make verify
```

`make install-embedded` 会从当前 checkout 构建 Controller、embedded 基础设施、Manager 以及 Worker 运行时所需镜像，然后启动 `agentteams-controller` 和 `agentteams-manager`。安装过程需要联网拉取公开基础镜像和依赖，也需要访问上面配置的 LLM API。

## 6. 构建并安装 Dashboard

Dashboard 与主系统分开构建，但使用同一份源码快照：

```bash
export DASHBOARD_CONTEXT=dashboard
export DASHBOARD_VERSION=competition-v1.3
export DASHBOARD_IMAGE=agentteams/agentteams-dashboard:competition-v1.3

make build-dashboard
make install-dashboard
make wait-dashboard-ready
```

访问：

- Element Web：<http://127.0.0.1:18088/#/login>
- Higress Console：<http://127.0.0.1:18001>
- AgentTeams Dashboard：<http://127.0.0.1:13000>

使用第 4 节设置的管理员账号登录 Element Web。Dashboard 的安装脚本会从已运行的 AgentTeams 安装中读取所需连接配置。

## 7. 验证清单

先确认容器状态：

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | \
  grep -E 'agentteams-controller|agentteams-manager|agentteams-dashboard'
```

然后执行快速真实集成测试：

```bash
make test-installed TEST_FILTER="01"
```

该测试会通过 Matrix API 与真实 Manager 交互，并检查核心服务健康状态和登录链路。需要更完整的验收时运行：

```bash
make test-installed
```

完整测试中的 GitHub 相关用例需要额外设置：

```bash
export AGENTTEAMS_GITHUB_TOKEN='评委自己的 GitHub PAT'
make test-installed
```

不设置 GitHub PAT 不影响核心系统启动；不要为了提交代码而把 PAT 放入仓库。

Dashboard 前端源码检查可以独立执行：

```bash
cd dashboard
npm ci
npm test
npm run lint
npm run typecheck
npm run build
cd ..
```

### 7.1 评委应保存的验证结果

为了让结果可复核，建议至少保存以下命令的完整终端输出，并记录执行时间、源码 commit、LLM provider/model 和 Docker 版本：

```bash
git rev-parse HEAD
docker version
docker compose version
make verify
make test-installed TEST_FILTER="01"
```

如果运行了 Worker 创建、任务分派、人工干预或 GitHub 集成测试，还应同时保存对应 Matrix 房间结果、容器状态和测试命令输出；不要只保存截图或手工描述。

## 8. 清理环境

评委完成验证后，可以删除本次安装的容器、网络、卷和工作区：

```bash
make uninstall-dashboard
make uninstall-embedded
```

这不会删除 Git checkout 本身。Docker 镜像可能仍保留在本机，如需释放磁盘空间，请由评委按自己的 Docker 管理策略处理。

## 9. 常见问题

### Manager 或 Worker 构建时拉取了错误的基础镜像

确认以下变量仍然指向本地、同一个比赛 tag，然后重新构建：

```bash
echo "$VERSION $OPENCLAW_BASE_IMAGE $OPENCLAW_BASE_VERSION"
make build-openclaw-base
make install-embedded
```

### 服务还没有 ready

```bash
docker ps -a | grep agentteams
docker logs agentteams-controller
docker logs agentteams-manager
make wait-ready-embedded
```

首次启动包含 Matrix、MinIO、Higress 和 Manager 初始化，可能需要数分钟。

### LLM 请求失败

检查 API Key、模型 ID、Base URL 和网络出口。OpenAI-compatible 服务通常要求 Base URL 包含 `/v1`，但具体路径以服务商文档为准。系统本身不会内置可离线替代模型。

### Dashboard 无法连接

先确认 `agentteams-controller` 已运行，再确认 Dashboard 使用了本地构建的 `DASHBOARD_IMAGE`：

```bash
docker image inspect agentteams/agentteams-dashboard:competition-v1.3
docker logs agentteams-dashboard
```

### TestWeaver 运行时预检

`scripts/testweaver-config-preflight.sh` 面向已有 TestWeaver 部署的维护者，需要外部受保护的 `runtime.env` 和对应容器/配置源。干净的公开克隆不包含这些私有配置，因此该预检不是本指南的启动前置条件。相关边界和当前实时观测状态见 `testweaver/docs/runtime-config.md` 与 `testweaver/docs/semifinal-control.md`；静态文档不能替代本次评委运行结果。

## 10. 复现结论标准

一次有效的比赛复现至少应满足：

1. 所有比赛所需镜像都由当前 checkout 构建成功；
2. `agentteams-controller`、`agentteams-manager` 和 Dashboard（若启用）保持运行；
3. Element Web 可以使用管理员账号登录；
4. `make verify` 无失败项；
5. `make test-installed TEST_FILTER="01"` 通过；
6. 需要声明更高层能力时，必须提供对应的本次实时测试输出，不能把历史证据文件当成当前运行证明。
