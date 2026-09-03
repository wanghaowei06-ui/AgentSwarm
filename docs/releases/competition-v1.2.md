# AgentSwarm competition-v1.2

- 发布类型：比赛发行版 / 可复现源码快照
- 仓库：[wanghaowei06-ui/AgentSwarm](https://github.com/wanghaowei06-ui/AgentSwarm)
- 固定 tag：`competition-v1.2`
- 上游来源：[agentscope-ai/AgentTeams](https://github.com/agentscope-ai/AgentTeams)
- 许可证：[Apache License 2.0](../../LICENSE)

## 发行版定位

AgentSwarm 是基于 AgentTeams 的公开比赛发行版。运行时代码保留 AgentTeams 的真实目录、镜像、API、环境变量和安装契约；本版本新增或整理的是比赛入口、复现说明、依赖/开放边界文档、治理文件和公开示例。

本版本不把 AgentTeams 上游能力重新声明为 AgentSwarm 独立原创，也不把本仓库自己的 commit、内部评测 evidence 或截图写成上游合并贡献、第三方采用或共同维护记录。

## 包含的交付物

- AgentTeams Controller、Manager、Worker runtime、Matrix/网关/存储集成、Helm 和安装脚本；
- Dashboard 源码、公开测试、TestWeaver adapter、Schema/接口/Trace 规范；
- 中文默认 README、英文入口、依赖清单、开放边界、贡献、安全、维护和行为准则文件；
- Docker embedded 和 Kubernetes Helm 两类源码安装交付物；
- [最小真实任务示例](../../examples/README.md)和[完整复现指南](../competition-reproduction.md)。

## 明确不包含

- API Key、Token、管理员密码、GitHub PAT、私有 endpoint 或其他凭证；
- `testweaver/evidence/`、容器日志、Matrix 历史会话、本地数据库和运行时状态；
- `node_modules/`、`.next/`、Python cache、构建产物和个人环境截图；
- mock server、固定回复、离线回放或预录评测结果。

## 复现前置条件

评委需要自行准备：

- Docker Engine 或 Docker Desktop、GNU Make、Bash、Git 和稳定的外网；
- Qwen 或 OpenAI-compatible 在线模型 API 及评委自己的 API Key；
- 至少 2 CPU / 4 GB RAM，建议 4 CPU / 8 GB RAM；首次构建需要额外磁盘空间；
- 如果运行 Dashboard 检查，需要 Node.js 22+ 和 npm；
- 如果运行 Kubernetes 路径，需要 Kubernetes 集群和 Helm；
- 如果运行 GitHub 集成测试，需要权限适当且仅在本地环境使用的 GitHub PAT。

模型 Key 和管理员密码只通过当前终端环境变量或私密配置输入，不能提交到 GitHub。

## 推荐验证流程

固定 tag 后执行：

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
make test-installed TEST_FILTER="01"
~~~

如需验证实时任务，继续执行：

~~~bash
make replay TASK="请在 Matrix 房间中回复一句可识别的中文确认，并说明你是 Manager"
~~~

应保存 `git rev-parse HEAD`、Docker 版本、模型 provider/model、构建参数、容器状态和测试输出。实际模型响应应以本次运行结果为准，不能用静态文件代替。

## 依赖和可复现性限制

`go.sum` 和 `dashboard/package-lock.json` 提供可复核的 Go/npm 解析结果；部分 Python 依赖使用范围约束，外部模型和 registry 的响应也不能由 Git tag 固定。完整说明见
[第三方依赖清单](../dependencies.md)。

## 版本关系

`competition-v1.1` 是此前已发布的不可移动快照。本版本不会修改或覆盖它；未来修复应在 `main` 经过验证后创建新的不可变 tag。

## 上游贡献和采用声明

截至本版本，仓库只公开声明 AgentTeams 上游来源，不声明没有公开 URL 证据的上游合并贡献、第三方部署采用或共同维护。未来若有可核验记录，将在新的发布说明中提供直接链接。
