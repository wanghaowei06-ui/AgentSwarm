# AgentSwarm

[English](./README.en.md) | 中文

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](./LICENSE)
[![Competition snapshot](https://img.shields.io/badge/competition-v1.2-6f42c1.svg)](./docs/competition-reproduction.md)

> AgentSwarm 是本次比赛提交的公开发行版，基于上游开源项目 [AgentTeams](https://github.com/agentscope-ai/AgentTeams)。它保留 AgentTeams 的真实运行时代码、镜像名、环境变量、API 和安装契约，并在本仓库中提供比赛复现入口、公开边界说明、测试/评测规范和治理文件。

本仓库不是把上游代码重新声明为 AgentSwarm 独立原创项目。源码中的 `AgentTeams` 名称是运行时接口的一部分；文档中的 AgentSwarm 表示本次比赛发行版和整理后的公开交付物。

## 先看这里

- [比赛版复现指南](./docs/competition-reproduction.md)：从固定 tag、源码构建、在线模型配置到实时验证。
- [开源范围与来源边界](./docs/open-source-boundary.md)：哪些内容开放，哪些本地材料明确排除。
- [第三方依赖清单](./docs/dependencies.md)：Go、npm、Python、Docker、Helm 和外部服务依赖。
- [贡献指南](./CONTRIBUTING.md)：如何提交 Issue、Pull Request 和文档改动。
- [安全响应](./SECURITY.md)：凭证泄露、权限绕过和远程执行等问题的私密报告方式。
- [版本记录](./CHANGELOG.md)：AgentSwarm 发行版变更，不等同于 AgentTeams 上游历史。
- [可运行示例](./examples/README.md)：启动真实系统后向 Manager 发送第一条任务。

## AgentSwarm 与 AgentTeams 的关系

| 内容 | 归属和说明 |
| --- | --- |
| AgentTeams Controller、Manager、Worker、Matrix、Helm 和安装契约 | 上游 AgentTeams 的真实开源系统内容，本仓库保留其目录和接口名称 |
| AgentSwarm 比赛入口 | 本仓库的中文/英文 README、固定版本复现指南、依赖与开放边界说明 |
| Dashboard 与 TestWeaver 公开部分 | 本仓库快照中的可运行源码、接口/Trace 规范和可重复执行的测试辅助代码 |
| 本地运行证据、日志、密钥和个人环境材料 | 明确不公开，也不作为源码能力或评测结果提交 |
| 上游贡献、第三方采用和共同维护 | 只在存在公开 URL 证据时声明；当前版本不作未经核验的声明 |

如果你要了解 AgentTeams 的上游路线、完整历史和社区活动，请直接访问 [AgentTeams 上游仓库](https://github.com/agentscope-ai/AgentTeams)。如果你要复现本次比赛提交，请使用本仓库的固定比赛 tag 和[比赛版复现指南](./docs/competition-reproduction.md)。

## 公开的核心内容

本仓库开放的是可以从干净 checkout 重新构建和验证的系统内容：

| 路径 | 内容 |
| --- | --- |
| `agentteams-controller/` | Go Controller、CRD、REST API、`agt` CLI 和控制器测试 |
| `manager/` | Manager 镜像、启动脚本、配置模板、Prompt 和 Manager Skills |
| `worker/`、`qwenpaw/`、`copaw/`、`hermes/`、`openhuman/` | 不同 Worker 运行时和镜像入口 |
| `openclaw-base/` | OpenClaw Manager/Worker 使用的基础镜像 |
| `plugins/` | TeamHarness、WorkerFlow 和运行时扩展 |
| `helm/`、`install/`、`shared/` | Kubernetes Chart、本地 embedded 安装和共享脚本 |
| `dashboard/` | 基于真实 Matrix/Controller 数据的可选管理界面 |
| `tests/`、`testweaver/` | 集成测试、适配器、评测/Trace 合约和复现辅助代码 |
| `docs/`、`design/` | 架构、部署、接口、运行时和比赛复现文档 |

## 比赛版快速复现

当前公开发行版是 `competition-v1.2`。此前的 `competition-v1.1` 仍作为不可移动的历史快照保留；评委应始终使用固定 tag，而不是持续变化的 `main`。

下面的命令会从本仓库构建真实镜像并安装 embedded 系统，不使用 mock、离线回放或预录证据：

~~~bash
git clone https://github.com/wanghaowei06-ui/AgentSwarm.git
cd AgentSwarm
git checkout competition-v1.2

export VERSION=competition-v1.2
export OPENCLAW_BASE_IMAGE=agentteams/openclaw-base
export OPENCLAW_BASE_VERSION=competition-v1.2
export AGENTTEAMS_DASHBOARD=0

make build-openclaw-base
make install-embedded
make wait-ready-embedded
make verify
~~~

模型 API、管理员账号、端口、资源需求、Windows/Linux 差异、实时任务和测试结果保存方式见[比赛版复现指南](./docs/competition-reproduction.md)。API Key 只应通过环境变量传入，不能写入仓库文件。

## 正式安装与部署入口

本仓库提供两类真实安装交付物：

- **Docker embedded**：适合评委和本地体验，使用根目录 `Makefile`、`install/` 和 embedded 镜像。
- **Kubernetes Helm**：适合团队或生产式部署，Chart 位于 `helm/agentteams/`，包含 Controller、网关、Matrix、存储和 Manager 配置。

详细文档：

- [中文快速开始](./docs/zh-cn/quickstart.md)
- [中文架构说明](./docs/zh-cn/architecture.md)
- [中文 Windows 部署](./docs/zh-cn/windows-deploy.md)
- [中文开发指南](./docs/zh-cn/development.md)
- [中文 FAQ](./docs/zh-cn/faq.md)
- [Helm Chart](./helm/agentteams/)
- [安装脚本说明](./install/README.md)

公开仓库提供源码安装和部署文件；它不声称已经发布一个独立的 PyPI/npm 包，也不保证外部镜像 registry、模型服务或第三方 SaaS 永久可用。

## 系统结构

AgentTeams 的核心通信模型是 Matrix 房间中的 Manager、Worker 和人类共同协作：

~~~text
Human
  │ Element Web / Matrix Client
  ▼
Matrix Homeserver (Tuwunel) ─── shared files (MinIO / OSS)
  │
  ▼
Manager Agent ─── AI Gateway (Higress) ─── online LLM provider
  │
  ├── OpenClaw Worker
  ├── QwenPaw / CoPaw Worker
  ├── Hermes Worker
  └── OpenHuman Worker
~~~

Manager 负责拆解和协调任务，Worker 负责执行；Matrix 房间保留可见的协作上下文，人类可以观察和介入。Worker 运行时由部署配置或 Worker 资源选择，具体边界见[架构文档](./docs/zh-cn/architecture.md)。

## Dashboard、测试与 Trace

Dashboard 是可选的真实数据界面，不生成 demo project、seed data 或伪造消息；它只读取 Controller 和 Matrix 返回的数据。进入 [Dashboard README](./dashboard/README.md) 查看本地构建、配置和验证方式。

可复现验证入口包括：

~~~bash
make verify
make test-installed TEST_FILTER="01"
python3 -m unittest discover -s testweaver/adapters/tests -p 'test_*.py'
~~~

TestWeaver 的公开部分提供 adapter、contract、Skill/Schema 和 Trace 规范；历史 evidence 目录、容器日志和本地运行状态不作为本仓库公开交付物。

## 版本与维护

- `competition-v1.2` 是当前公开发行版；`competition-v1.1` 是此前已发布且不可移动的比赛快照。
- 后续公开改动先在 `main` 完成验证，再创建新的不可变版本 tag。
- 版本记录见 [CHANGELOG.md](./CHANGELOG.md)，来源和开放边界见 [NOTICE](./NOTICE) 与[开放范围文档](./docs/open-source-boundary.md)。
- 当前仓库维护者、支持范围和未声明事项见 [MAINTAINERS.md](./MAINTAINERS.md)。
- Bug、功能建议和 Pull Request 入口见 [GitHub Issues](https://github.com/wanghaowei06-ui/AgentSwarm/issues) 与 [贡献指南](./CONTRIBUTING.md)。

## 上游贡献和第三方采用声明

本仓库不会把自己的提交记录、比赛评测记录或静态截图包装成 AgentTeams 上游贡献、第三方采用或共同维护证据。若未来有已合并上游 PR、公开 Issue、第三方部署反馈或共同维护者，会在发布说明中附上可直接访问的公开 URL。

## 许可证

本仓库遵循 Apache License 2.0，许可证正文见 [LICENSE](./LICENSE)，来源和归属说明见 [NOTICE](./NOTICE)。代码目录中如包含独立来源或许可证文件，以对应文件为准；第三方依赖按其各自许可证使用。
