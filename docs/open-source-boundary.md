# AgentSwarm 开放范围与来源边界

## 1. 项目关系

AgentSwarm 是本次比赛提交的公开发行版，基于
[AgentTeams](https://github.com/agentscope-ai/AgentTeams) 的开源源码和真实运行时契约。

- AgentTeams 的目录名、镜像名、API、环境变量、Matrix 房间模型和安装流程在本仓库中继续保留，因为它们是可运行系统的接口。
- AgentSwarm 负责本次比赛的公开入口、固定 tag、复现指南、依赖说明、治理文件以及本仓库额外整理的公开文档。
- 上游代码、第三方依赖和本仓库新增文档不应被混写为同一来源或同一作者的原创成果。
- 没有公开 URL 证据时，本仓库不声明 AgentTeams 上游合并贡献、第三方采用或共同维护。

## 2. 本仓库公开的核心内容

以下内容属于公开源码交付物，评委可以从固定 tag 的干净 checkout 重新构建或检查：

| 路径 | 公开内容 |
| --- | --- |
| `agentteams-controller/` | Go Controller、CRD、REST API、`agt` CLI 和控制器测试 |
| `manager/` | Manager 镜像、启动脚本、配置模板、Prompt 和 Skills |
| `worker/`、`qwenpaw/`、`copaw/`、`hermes/`、`openhuman/` | Worker runtime、Dockerfile 和入口脚本 |
| `openclaw-base/` | OpenClaw 基础镜像构建输入 |
| `plugins/` | TeamHarness、WorkerFlow、CLI 和其他公开扩展 |
| `helm/`、`install/`、`shared/` | Kubernetes Chart、本地 embedded 安装和共享脚本 |
| `dashboard/` | 使用真实 Controller/Matrix 数据的可选 Dashboard |
| `tests/`、`testweaver/` | 可重新运行的测试、adapter、Schema/接口/Trace 规范 |
| `docs/`、`design/` | 架构、部署、开发、API 和比赛复现文档 |

## 3. 本仓库明确排除的内容

以下内容不属于公开源码或比赛复现输入：

- `testweaver/evidence/`、容器日志、Matrix 历史会话、运行时状态和本地工作区；
- `testweaver/config/runtime.env`、API Key、Token、密码、内部 endpoint 和其他凭证；
- `node_modules/`、`.next/`、Python `__pycache__/`、临时文件、构建产物和本机数据库；
- 含个人账号、凭证、内部地址或不可公开环境信息的截图/录屏；
- 任何预录回复、静态截图或历史 evidence。它们不能代替从源码启动系统并调用真实模型；
- 不必要的私有部署资产、缓存和与评委复现无关的本地运行文件。

`.gitignore` 和发布前的 `git ls-files` 审计共同保护这些边界；如果干净克隆中发现上述路径，应停止发布并先处理原因。

## 4. 许可证与第三方来源

根目录 `LICENSE` 为 Apache License 2.0，`NOTICE` 说明 AgentTeams 上游归属和本仓库发行版关系。单独目录中的来源/许可证文件优先适用于对应内容；评测中包含的独立来源资产保留其原始 attribution 和许可证文件。

第三方 Go module、npm/Python 包、基础镜像、Helm 子 Chart、Tuwunel、Higress、MinIO、Element Web 和模型服务均按各自许可证与服务条款使用。完整的机器可读入口见 [`docs/dependencies.md`](dependencies.md)。

## 5. 上游贡献和第三方采用声明

本仓库当前只核验并公开以下事实：

- 上游项目地址是 `https://github.com/agentscope-ai/AgentTeams`；
- 本仓库公开了 AgentSwarm 比赛发行版和其 Git 历史；
- 评委可以按 [`docs/competition-reproduction.md`](competition-reproduction.md) 重新构建和验证。

本版本不把本仓库自己的 commit、内部评测记录、历史截图或本地运行证据写成 AgentTeams 已合并贡献、第三方采用或共同维护记录。未来只有在存在可直接访问的 PR、Issue、部署反馈或维护者记录 URL 时，才会在发布说明中加入对应事实。

## 6. 发现敏感数据后的处理

如果发现疑似凭证、未脱敏日志、私有地址或其他敏感材料：

1. 不要复制到公开 Issue、PR、聊天或截图中；
2. 立即停止传播，并按照 [`SECURITY.md`](../SECURITY.md) 的私密报告方式联系维护者；
3. 如果材料已经进入 Git 历史，保留必要的 commit/路径信息供私密处理，不要自行改写公共历史；
4. 发布修复后重新执行敏感路径审计和干净克隆检查；
5. 只有重新验证后的源码和文档才能进入新的不可变比赛 tag。
