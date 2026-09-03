# AgentSwarm 第三方依赖与许可证说明

## 1. 阅读方式

AgentSwarm 的依赖分为三类：

1. **仓库内可审计的构建输入**：源码、manifest、lockfile、Dockerfile 和 Helm Chart；
2. **构建时从公共 registry 获取的第三方包或基础镜像**：由对应上游项目的许可证和发布条款约束；
3. **运行时外部服务**：评委自己的模型 API、Docker/Kubernetes、Matrix、网关和对象存储。

本文件提供依赖入口和复核方法，不复制容易过期的完整传递依赖清单。安装或评测前请先固定 Git tag，再按表格中的机器可读文件检查实际版本。

## 2. 组件依赖清单

| 组件 | 机器可读事实来源 | 版本与解析方式 | 构建/运行前置 | 许可证边界 |
| --- | --- | --- | --- | --- |
| AgentTeams Controller | [`agentteams-controller/go.mod`](../agentteams-controller/go.mod)、[`go.sum`](../agentteams-controller/go.sum) | Go module 版本和 checksum；Go 版本见 go.mod | Go、Docker/BuildKit | Controller 代码遵循本仓库许可证；每个 Go 依赖遵循其上游许可证 |
| Dashboard | [`dashboard/package.json`](../dashboard/package.json)、[`package-lock.json`](../dashboard/package-lock.json) | `npm ci` 按 lockfile 安装；Node 版本要求见 Dockerfile/文档 | Node.js、npm、真实 Controller/Matrix | npm 包按各自 package metadata 和许可证使用 |
| CoPaw Worker | [`copaw/pyproject.toml`](../copaw/pyproject.toml)、[`copaw/Dockerfile`](../copaw/Dockerfile) | 包含 `copaw==1.0.2` 和 Matrix/Markdown 依赖；其他传递依赖由 pip 解析 | Python、pip、网络和模型 API | CoPaw 及 Python 依赖按各自上游许可证 |
| QwenPaw Worker | [`qwenpaw/pyproject.toml`](../qwenpaw/pyproject.toml)、[`qwenpaw/Dockerfile`](../qwenpaw/Dockerfile) | 包含 `qwenpaw==2.0.1`；Python 版本范围和其他约束见 pyproject | Python、pip、网络和模型 API | QwenPaw、ACP 和 Python 依赖按各自上游许可证 |
| Hermes Worker | [`hermes/pyproject.toml`](../hermes/pyproject.toml)、[`hermes/Dockerfile`](../hermes/Dockerfile) | Matrix、mautrix、HTTP、CLI 等依赖由 pyproject 约束；`hermes-agent` 的 Git ref 由 Dockerfile 控制 | Python、pip、网络和模型 API | Hermes 及其 Git 依赖按各自上游许可证 |
| OpenClaw base/Manager/Worker | [`openclaw-base/Dockerfile`](../openclaw-base/Dockerfile)、[`manager/`](../manager/)、[`worker/`](../worker/) | 基础镜像、Node 包和构建参数由 Dockerfile 与根 Makefile 控制 | Docker BuildKit、公共镜像 registry | OpenClaw、Ubuntu、Node 和基础镜像按各自条款 |
| OpenHuman Worker | [`openhuman/Dockerfile`](../openhuman/Dockerfile) | Rust 构建输入和基础镜像由 Dockerfile 控制 | Docker、Rust 构建环境、网络 | OpenHuman 和 Rust crate 按各自上游许可证 |
| Plugins/CLI | [`plugins/cli/pyproject.toml`](../plugins/cli/pyproject.toml)、[`plugins/`](../plugins/) | Python package metadata 和各插件 Dockerfile | Python、pip 或 Docker | 插件依赖按各自上游许可证 |
| Kubernetes | [`helm/agentteams/Chart.yaml`](../helm/agentteams/Chart.yaml)、[`values.yaml`](../helm/agentteams/values.yaml) | Chart、子 Chart、镜像 tag 和 values 控制部署 | Kubernetes、Helm、公共 chart/镜像 registry | Chart、镜像及其子服务按各自许可证 |
| Embedded 安装 | [`install/`](../install/)、根 [`Makefile`](../Makefile) | 从当前 checkout 构建或调用 Docker/Compose 依赖 | Docker Engine、Compose 兼容能力、Bash、Make | 安装脚本由本仓库许可证覆盖；外部服务不重新许可 |

## 3. 运行时外部服务

完整复现还需要以下不随源码仓库重新分发的服务：

- 一个可联网访问的 Qwen 或 OpenAI-compatible 大模型 API；
- Docker Engine 或 Docker Desktop；Kubernetes 路径还需要 Helm 和集群；
- Matrix Homeserver（默认部署使用 Tuwunel）、Element Web、Higress AI Gateway 和 MinIO/OSS；
- 公共 Docker registry、Go module proxy、npm registry、PyPI 或 Docker build 所需的 Git 源；
- GitHub PAT 仅在运行需要 GitHub 权限的特定集成测试时使用。

模型 API Key、管理员密码、Matrix token、GitHub PAT 和内部 endpoint 只能通过本地环境变量或私密配置传入，不能写入 Git、镜像层、网页响应、Issue 或测试证据。

## 4. 版本锁定和可复现性边界

- `go.sum` 和 `dashboard/package-lock.json` 提供可复核的 Go/npm 解析结果。
- Python `pyproject.toml`、Dockerfile 和 Helm values 提供直接依赖、基础镜像和发布版本约束；部分 Python 依赖使用范围约束，不能声称所有传递依赖已经完全离线锁定。
- `competition-v1.2` tag 固定本仓库源码，但不能固定外部模型服务的响应、公共 registry 的可用性或第三方服务的行为。
- 评委应在验证记录中保存 Git commit、Docker 版本、模型 provider/model、构建参数和实际测试输出。

## 5. 许可证检查原则

根目录 [`LICENSE`](../LICENSE) 是 Apache License 2.0；[`NOTICE`](../NOTICE) 解释了 AgentSwarm 与 AgentTeams 的来源关系。任何目录中的独立许可证或来源说明优先适用于其对应文件，例如
[`testweaver/evaluation/openworker_pr161/SOURCE-LICENSE.md`](../testweaver/evaluation/openworker_pr161/SOURCE-LICENSE.md)。

本仓库不把所有第三方依赖汇总成 Apache-2.0，也不保证外部依赖的许可证、服务条款或安全响应会随本仓库版本自动变化。
