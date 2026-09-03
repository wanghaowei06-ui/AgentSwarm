# AgentSwarm 开源边界与比赛发行版设计

**日期：** 2026-09-03
**状态：** 待用户评审
**适用版本：** 下一次公开发行版（`competition-v1.2`）

## 目标

将公开仓库从“AgentTeams 源码快照 + AgentSwarm 比赛材料”的混合呈现，整理为一个来源诚实、边界清晰、可安装、可复现、可持续维护的 AgentSwarm 比赛发行版，同时保留 AgentTeams 运行时所需的真实目录名、镜像名、API 和安装契约。

## 背景与现状

当前公开仓库已经具备 Apache-2.0 许可证、Docker/Helm 安装流程、真实源码、测试和比赛复现指南，但入口文档仍大量沿用 AgentTeams 上游项目的产品介绍、动态、社区入口和 Issue 指引。评委容易无法区分：

1. AgentTeams 上游已有的能力和版权归属；
2. AgentSwarm 比赛发行版新增或整理的内容；
3. 为了复现而排除的本地证据、日志、密钥和缓存；
4. 当前仓库实际承诺的支持与维护范围。

主开发工作区当前还有未提交的 Dashboard 功能实现（`dashboard/lib/inbox/`、相关测试和 `dashboard/tests/store.test.ts`），这些内容属于正在进行的开发，不纳入本次公开发行版。

## 设计决策

### 1. 保留一个公开仓库，分离文档身份

不复制出第二份运行时代码，也不对所有 `AgentTeams` 目录、镜像和 API 做强制改名。公开仓库根目录定位为：

> **AgentSwarm：基于 AgentTeams 的比赛发行版与可复现源码快照。**

根目录 `README.md` 只负责解释 AgentSwarm 的比赛交付物、来源、复现路径、开放范围和治理入口；运行时代码中的 `AgentTeams` 名称继续保持不变，因为这些名称是源码、Dockerfile、Helm Chart、环境变量和安装脚本之间的真实接口。

README 必须明确说明：

- `AgentTeams` 是上游开源项目，链接到 <https://github.com/agentscope-ai/AgentTeams>；
- AgentSwarm 使用上游 Apache-2.0 代码并在公开仓库中保留源代码和必要归属；
- 本仓库的比赛文档、复现边界、Dashboard/TestWeaver 适配内容和后续改动单独列出；
- 没有真实上游 PR、Issue 或已合并 commit 链接时，不声称已经对 AgentTeams 产生上游贡献；
- 评委应以固定比赛 tag，而不是持续变化的 `main`，作为复现输入。

### 2. 公开范围与排除范围

公开范围保持真实系统的核心内容：

| 范围 | 公开内容 |
| --- | --- |
| 控制面 | `agentteams-controller/` 的 Go Controller、CRD、REST API、`agt` CLI 和单元/集成测试 |
| Agent 运行时 | `manager/`、`worker/`、`copaw/`、`qwenpaw/`、`hermes/`、`openhuman/`、`openclaw-base/` |
| 编排与安装 | `helm/`、`install/`、`shared/`、根 `Makefile` 和 Dockerfile |
| 扩展与界面 | `plugins/`、`dashboard/` |
| 协作规范 | `manager/agent/` 下的 Skill、Prompt、Schema、接口和运行时文档 |
| 验证材料 | 可重新执行的 `tests/`、`testweaver/adapters/`、评测/Trace 规范和复现脚本 |

明确排除不可公开或不可作为源码能力声明的内容：

- `testweaver/evidence/`、运行日志、容器状态、历史会话和本地工作区；
- `testweaver/config/runtime.env`、API Key、Token、密码、内部 endpoint 和其他凭证；
- `node_modules/`、`.next/`、Python 缓存、构建产物和临时目录；
- 含凭证、个人环境或内部地址的截图和录屏；
- 任何预录结果都不能替代评委从源码重新构建、启动和调用真实模型。

排除项必须在 README 和 `docs/open-source-boundary.md` 中重复说明，并通过干净克隆的路径审计验证。

### 3. 许可证、归属和第三方依赖

- 保留根目录 Apache License 2.0，不把上游代码改称为 AgentSwarm 独立原创代码。
- 新增 `NOTICE`，说明 AgentSwarm 是基于 AgentTeams 的发行版，并区分上游代码、比赛整理文档和本仓库新增内容。
- 新增 `docs/dependencies.md`，按组件列出依赖清单入口、版本/锁定文件、构建来源、外部服务和许可证边界。
- `go.mod`/`go.sum`、`package.json`/`package-lock.json`、各 Python `pyproject.toml`、Dockerfile 和 Helm Chart 继续作为机器可读的依赖事实来源；文档不复制一份容易过期的完整传递依赖列表。
- 对带有独立来源或独立许可证的评测资产，继续保留其目录内的来源许可证文件，并在第三方依赖文档中建立链接。
- 文档明确说明模型 API、Docker Engine、Kubernetes、Higress、Tuwunel、MinIO、Element Web 和 npm/PyPI/Go registry 是外部依赖，不由本仓库重新许可或保证长期可用。

### 4. 版本、安装包和可运行示例

- 保留已经发布的 `competition-v1.1`，不移动或覆盖该 tag。
- 本次治理整理完成后创建新的不可变 `competition-v1.2` tag，并增加对应发布说明；公开仓库的 `main` 指向最新已验证提交。
- 将 `install/` 的 Docker/embedded 安装脚本和 `helm/agentteams/` Chart 明确列为本发行版的安装交付物；不虚构不存在的 PyPI/npm 安装包或预构建镜像。
- 新增一个 `examples/` 入口，提供从启动后向 Manager 发送第一条真实任务、查看 Matrix 房间和运行验证测试的可复制示例；示例不内置 mock、默认账号、API Key 或虚假结果。
- 发布说明记录源码 commit、版本 tag、复现命令、验证命令、已知外部前置条件和不包含的本地证据。

### 5. 贡献、安全和维护机制

新增以下仓库治理入口：

| 文件 | 责任 |
| --- | --- |
| `CONTRIBUTING.md` | 分支、提交、测试、文档、许可证和 Pull Request 要求 |
| `SECURITY.md` | 凭证泄露、远程执行、权限绕过等安全问题的私密报告路径和不应公开的内容 |
| `CODE_OF_CONDUCT.md` | 社区行为底线和处理方式 |
| `MAINTAINERS.md` | 当前仓库维护者、职责范围和维护状态 |
| `.github/PULL_REQUEST_TEMPLATE.md` | 变更范围、测试、兼容性和敏感数据检查清单 |
| `.github/ISSUE_TEMPLATE/feature_request.yml` | 功能建议入口；现有 Bug 模板继续保留并修正仓库指向 |

治理文档只承诺当前可以执行的机制：GitHub Issue 用于公开问题和需求，Pull Request 用于代码/文档改动，Security 页面或维护者私密渠道用于敏感问题。没有真实第三方采用、共同维护或上游合并记录时，文档明确写“当前未声明”，而不是用项目自身的提交制造第三方背书。

## 预期文件变更

### 新增

- `NOTICE`
- `VERSION`
- `CHANGELOG.md`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `CODE_OF_CONDUCT.md`
- `MAINTAINERS.md`
- `docs/dependencies.md`
- `docs/open-source-boundary.md`
- `docs/releases/competition-v1.2.md`
- `examples/README.md`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/ISSUE_TEMPLATE/feature_request.yml`

### 修改

- `README.md`：改为 AgentSwarm 默认中文入口，保留真实 AgentTeams 运行契约说明。
- `README.en.md`：与中文入口保持同一身份、许可证和复现边界。
- `README.zh-CN.md`：继续作为旧链接兼容入口，指向根目录中文 README。
- `dashboard/README.md`：补充其在发行版中的位置、真实数据边界和本地检查方式。
- `docs/competition-reproduction.md`：加入来源、许可证、依赖、评委输出保存和固定版本说明的链接。
- `.github/ISSUE_TEMPLATE/bug_report.yml`：将模板从上游 AgentTeams 专用指引调整为本仓库/上游问题分流指引。

不修改：

- `agentteams-controller/`、`manager/`、`worker/`、各运行时、Helm、安装脚本和未提交的主工作区 Dashboard 实现；
- `LICENSE` 的 Apache-2.0 正文；
- 已发布的 `competition-v1.1` tag。

## 验证标准

实施完成后，以下条件必须全部满足：

1. 根 README 第一屏能看出仓库是 AgentSwarm 比赛发行版，并明确上游 AgentTeams 来源。
2. README、依赖、许可证、开放边界、复现、贡献和安全入口之间的链接都存在且指向正确文件。
3. `LICENSE`、`NOTICE` 和第三方依赖说明不互相矛盾，不把第三方依赖重新声明为本仓库原创或单一许可证。
4. 新版本 tag 与发布说明指向同一个已验证 commit，旧 `competition-v1.1` 仍可独立复现。
5. 干净克隆的 `git ls-files` 不包含运行时密钥、证据包、依赖缓存或敏感截图。
6. 现有适配器、Dashboard 和脚本检查继续通过；文档-only 变更不影响运行时代码构建路径。
7. 主开发工作区的未提交 Dashboard 改动不被 staging、commit 或推送。
8. 对 AgentTeams 上游贡献、第三方采用和共同维护只写入可由公开 URL 核验的事实。

## 未采用的方案

### 方案 A：复制一份完全改名的 AgentSwarm 代码

不采用。它会产生两份运行时代码，容易让安装命令、镜像、API、Helm 和文档互相漂移，也会掩盖上游来源。

### 方案 B：继续作为 AgentTeams 原样镜像，仅在末尾添加比赛说明

不采用。当前混淆正是由入口标题、上游动态、社区链接和比赛材料并置造成的，末尾追加说明不能解决身份问题。

### 方案 C：保留真实 AgentTeams 代码契约，使用 AgentSwarm 专属入口和治理文档

采用。它以最小代码改动解决评委的归属、依赖、复现、维护和安全判断，同时让后续主仓库开发能够按版本 tag 增量同步。

## 后续步骤

用户确认本设计文档后，使用独立实施计划逐项新增/修改文档与治理文件，运行链接、敏感路径、Markdown、现有测试和干净克隆检查，提交后再推送 `main` 与 `competition-v1.2`。
