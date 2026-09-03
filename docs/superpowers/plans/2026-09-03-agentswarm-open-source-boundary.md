# AgentSwarm 开源边界与治理整理实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`[ ]`) syntax.

**Goal:** 将公开仓库整理为来源清晰、许可证和依赖可核验、可安装复现、具备基本贡献/安全/维护机制的 AgentSwarm 比赛发行版。

**Architecture:** 保留 AgentTeams 的真实运行时代码、镜像名、环境变量、API 和安装契约；在根 README、归属/依赖文档、发布说明和 GitHub 治理文件中建立 AgentSwarm 的公开交付边界。所有改动只发生在公开仓库工作区，主开发工作区的未提交 Dashboard 实现不进入本次提交。

**Tech Stack:** Markdown、GitHub Issue/PR 模板、Docker/Helm/Make 复现入口；验证使用 Git 路径审计、Markdown 链接检查、现有 Python/Node/Shell 测试。

**Spec:** `docs/superpowers/specs/2026-09-03-agentswarm-open-source-boundary-design.md`

## Global Constraints

- 工作目录固定为 `/root/projects/agentteams-competition-worktree`，分支为 `agent-swarm-public`。
- 不修改 `agentteams-controller/`、`manager/`、`worker/`、`copaw/`、`qwenpaw/`、`hermes/`、`openhuman/`、`openclaw-base/`、`shared/`、`helm/`、`install/` 和 Dashboard 运行时代码。
- 不 stage、commit 或推送 `/root/projects/agentteams` 中当前未提交的 Dashboard 变更。
- 保留 `LICENSE` 的 Apache License 2.0 正文；新增内容默认遵循 Apache-2.0，但不替第三方依赖重新许可。
- 不声明没有公开 URL 证据的 AgentTeams 上游合并贡献、第三方采用、共同维护或评测结果。
- 保留已发布的 `competition-v1.1`，完成验证后创建新的不可变 `competition-v1.2`；不移动历史 tag。
- 根目录 `README.md` 是默认中文入口，`README.en.md` 保持身份、边界和命令的英文对应版本。
- 不添加 API Key、Token、密码、内部 URL、运行日志、证据包、依赖缓存、个人环境截图或预录结果。
- 文档只描述当前仓库真实存在的安装脚本、Helm Chart、测试和示例；不虚构 PyPI/npm 包或预构建镜像。

---

### Task 1: 建立 AgentSwarm 专属入口文档

**Files:**
- Modify: `README.md`
- Modify: `README.en.md`
- Modify: `README.zh-CN.md`
- Modify: `dashboard/README.md`
- Modify: `docs/competition-reproduction.md`

**Interfaces:**
- Consumes: 现有 AgentTeams 源码目录、`LICENSE`、`competition-v1.1` 复现流程和上游链接。
- Produces: 以 AgentSwarm 为第一身份的中文 README、英文对应入口、兼容入口和比赛复现交叉链接。

- [ ] **Step 1: 记录现有公开入口和主工作区边界**

运行：

~~~bash
git -C /root/projects/agentteams-competition-worktree status --short
rg -n 'AgentTeams|AgentSwarm|agentscope-ai|competition-v1.1' \
  /root/projects/agentteams-competition-worktree/README*.md \
  /root/projects/agentteams-competition-worktree/docs/competition-reproduction.md
git -C /root/projects/agentteams status --short
~~~

确认只记录状态，不修改主工作区；公开工作区必须保持干净后再开始本任务。

- [ ] **Step 2: 重写中文 README 的第一屏和目录结构**

将根标题、摘要和第一屏固定为以下事实关系：

~~~markdown
# AgentSwarm

AgentSwarm 是本次比赛提交的公开发行版，基于上游开源项目
[AgentTeams](https://github.com/agentscope-ai/AgentTeams)。
运行时代码继续使用 AgentTeams 的真实目录、镜像、API 和环境变量名称；这不是把上游代码重新声明为 AgentSwarm 独立原创项目。
~~~

第一屏直接链接“比赛复现”“开源边界”“依赖清单”“贡献指南”“安全响应”和“版本记录”。保留真实系统能力说明，但将上游项目历史动态、上游社区链接和上游 Bug 流程移到“上游项目”小节或直接链接上游。

- [ ] **Step 3: 在中文 README 中说明开放范围和来源边界**

增加表格，至少覆盖 `agentteams-controller/`、`manager/`、各 Worker runtime、`plugins/`、`helm/`、`install/`、`dashboard/`、`tests/` 和 `testweaver/`；同时列出不提交 `testweaver/evidence/`、运行时配置、密钥、日志、缓存和敏感截图的原因。明确写出“当前未声明未提供公开 URL 证据的上游合并贡献、第三方采用和共同维护记录”。

- [ ] **Step 4: 同步英文 README 和中文兼容入口**

`README.en.md` 使用同一信息结构和同一版本/命令；`README.zh-CN.md` 保留为旧链接兼容页，只指向根目录 `README.md`，不再复制第二份长期内容。

- [ ] **Step 5: 修正 Dashboard 与比赛指南中的身份措辞**

在 `dashboard/README.md` 中说明它是 AgentSwarm 快照中的可选界面，数据来自真实 Matrix/Controller，不是演示页面；在 `docs/competition-reproduction.md` 中链接开源边界、依赖清单和发布说明，并继续要求评委从固定 tag 构建和使用自己的在线模型 API。

- [ ] **Step 6: 检查文档身份和链接**

运行：

~~~bash
rg -n 'AgentSwarm|AgentTeams|competition-v1.1|open-source-boundary|dependencies|CONTRIBUTING|SECURITY' \
  /root/projects/agentteams-competition-worktree/README*.md \
  /root/projects/agentteams-competition-worktree/dashboard/README.md \
  /root/projects/agentteams-competition-worktree/docs/competition-reproduction.md
git -C /root/projects/agentteams-competition-worktree diff --check
~~~

确认根 README 首屏先表达 AgentSwarm，再解释 AgentTeams 上游；不得出现把上游提交、上游社区或上游发布版本写成 AgentSwarm 自己发行记录的句子。

- [ ] **Step 7: 提交入口文档**

~~~bash
git -C /root/projects/agentteams-competition-worktree add README.md README.en.md README.zh-CN.md dashboard/README.md docs/competition-reproduction.md
git -C /root/projects/agentteams-competition-worktree commit -m "docs: clarify AgentSwarm competition distribution identity"
~~~

### Task 2: 补齐许可证、来源、依赖和开放边界说明

**Files:**
- Create: `NOTICE`
- Create: `VERSION`
- Create: `CHANGELOG.md`
- Create: `docs/dependencies.md`
- Create: `docs/open-source-boundary.md`

**Interfaces:**
- Consumes: `LICENSE`、各组件 manifest、Dockerfile、Helm Chart、公开快照排除规则和上游 AgentTeams URL。
- Produces: 评委和外部贡献者可单独阅读的法律归属、依赖事实来源、版本状态和开放边界说明。

- [ ] **Step 1: 新增 NOTICE 并保留 Apache-2.0 正文**

`NOTICE` 说明：本仓库名为 AgentSwarm；运行时代码主要源自 AgentTeams；上游地址为 `https://github.com/agentscope-ai/AgentTeams`；Apache-2.0 正文位于根目录 `LICENSE`；第三方依赖仍受各自许可证约束。不要替换 `LICENSE` 正文，也不要声称全部代码由单一作者原创。

- [ ] **Step 2: 新增版本文件和变更记录入口**

将 `VERSION` 内容设为：

~~~text
competition-v1.2
~~~

`CHANGELOG.md` 只记录 AgentSwarm 发行版；首个条目链接 `docs/releases/competition-v1.2.md`，并说明 `competition-v1.1` 是此前不可变快照。

- [ ] **Step 3: 编写开放边界文档**

`docs/open-source-boundary.md` 固定包含：

~~~markdown
# AgentSwarm 开放范围与来源边界
## 1. 项目关系
## 2. 本仓库公开的核心内容
## 3. 本仓库明确排除的内容
## 4. 许可证与第三方来源
## 5. 上游贡献和第三方采用声明
## 6. 发现敏感数据后的处理
~~~

内容逐目录列出开放核心、评测/Trace 规范和排除项；明确历史证据不能替代实时复现；明确没有公开链接的上游贡献和第三方采用记录当前不作声明。

- [ ] **Step 4: 编写依赖清单**

`docs/dependencies.md` 至少使用以下组件维度：

| 组件 | 依赖事实来源 | 版本/解析方式 | 外部前置 | 许可证说明 |
| --- | --- | --- | --- | --- |
| Controller | `agentteams-controller/go.mod`, `go.sum` | Go module 版本与校验和 | Go、Docker | 依赖按各自上游许可证 |
| Dashboard | `dashboard/package.json`, `package-lock.json` | `npm ci` 使用 lockfile | Node.js、npm | npm 包按各自元数据 |
| Python runtimes/plugins | 各目录 `pyproject.toml`、Dockerfile | PyPI/Git 来源及 Dockerfile 版本约束 | Python、pip、网络 | Python 包按各自许可证 |
| Agent images | `openclaw-base/`、`manager/`、`worker/` 等 Dockerfile | 基础镜像和构建参数 | Docker Engine | 基础镜像按发布方条款 |
| Kubernetes | `helm/agentteams/Chart.yaml`、`values.yaml` | Helm chart 和子 chart 版本 | Kubernetes、Helm | chart/镜像/服务按各自许可证 |
| Services | `docs/architecture.md`、`helm/`、`install/` | Higress、Tuwunel、MinIO、Element Web | 外网和容器 registry | 不由本仓库重新许可 |
| Model provider | `docs/competition-reproduction.md` | 评委自己的 Qwen 或 OpenAI-compatible API | 在线 API Key | Key 不进入仓库 |

同时说明 `go.sum` 和 `package-lock.json` 是可复核材料，而 Python/Docker 的范围依赖仍需按 Dockerfile 和发布 tag 复核，不能声称所有传递依赖已经完全离线锁定。

- [ ] **Step 5: 检查许可证与依赖文档一致性**

~~~bash
test -f /root/projects/agentteams-competition-worktree/LICENSE
test -f /root/projects/agentteams-competition-worktree/NOTICE
test "$(tr -d '\r\n' < /root/projects/agentteams-competition-worktree/VERSION)" = competition-v1.2
rg -n 'Apache|AgentTeams|AgentSwarm|go.mod|package-lock|pyproject|Dockerfile|Helm|不作声明|不重新许可' \
  /root/projects/agentteams-competition-worktree/NOTICE \
  /root/projects/agentteams-competition-worktree/docs/dependencies.md \
  /root/projects/agentteams-competition-worktree/docs/open-source-boundary.md
git -C /root/projects/agentteams-competition-worktree diff --check
~~~

- [ ] **Step 6: 提交法律和依赖文档**

~~~bash
git -C /root/projects/agentteams-competition-worktree add NOTICE VERSION CHANGELOG.md docs/dependencies.md docs/open-source-boundary.md
git -C /root/projects/agentteams-competition-worktree commit -m "docs: document AgentSwarm provenance and dependencies"
~~~

### Task 3: 建立贡献、安全、行为和维护入口

**Files:**
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`
- Create: `CODE_OF_CONDUCT.md`
- Create: `MAINTAINERS.md`
- Create: `.github/PULL_REQUEST_TEMPLATE.md`
- Create: `.github/ISSUE_TEMPLATE/feature_request.yml`
- Modify: `.github/ISSUE_TEMPLATE/bug_report.yml`

**Interfaces:**
- Consumes: 现有 Bug Issue 模板、AgentTeams 代码构建/测试命令和公开仓库维护者账号。
- Produces: 外部人员能够报告问题、提交改动、报告安全问题并识别当前维护范围的最小治理机制。

- [ ] **Step 1: 编写 CONTRIBUTING.md**

包括 Fork/分支/PR 流程；修改 runtime 或 Controller 时运行的测试；文档-only 变更的 Markdown/link 检查；不得提交凭证、证据包、日志和依赖缓存；新文件默认 Apache-2.0；PR 必须说明是否改动真实运行时契约；本仓库提交不得自动标记为 AgentTeams 上游贡献。

- [ ] **Step 2: 编写 SECURITY.md**

要求不要在公开 Issue 发布 API Key、Token、密码、私有 URL、未脱敏 Matrix 事件或容器日志；优先通过 GitHub Security 页私密漏洞报告入口联系维护者，入口不可用时通过维护者 GitHub 账号私密联系；公开问题只用于不包含敏感细节的修复跟踪。支持范围写为当前 `competition-v1.2` 和仍可复现的 `competition-v1.1`，不承诺外部依赖服务的安全响应 SLA。

- [ ] **Step 3: 编写 CODE_OF_CONDUCT.md 和 MAINTAINERS.md**

行为准则提供尊重、反骚扰、问题报告和处理规则。维护者文件明确当前仓库维护者为 GitHub 账号 `@wanghaowei06-ui`，负责公开 Issue、PR、比赛发行版文档和安全分流；不代表 AgentTeams 上游维护团队，也不声明第三方共同维护。

- [ ] **Step 4: 新增 PR 模板和功能 Issue 模板**

PR 模板包含：变更范围、测试命令、许可证/来源、敏感数据扫描、是否影响安装或 API、是否需要更新文档和 CHANGELOG。Feature Request 使用合法 GitHub issue-form YAML，字段至少包括问题背景、期望行为、复现/使用场景、影响组件和是否愿意贡献实现。

- [ ] **Step 5: 修正 Bug 模板的仓库归属**

将模板标题、描述和链接改成 AgentSwarm；增加“问题属于 AgentSwarm 整理层还是 AgentTeams 上游运行时”的分流字段；保留版本/commit、复现步骤、组件和脱敏日志字段；不要要求用户在公开 Issue 粘贴凭证或未脱敏事件。

- [ ] **Step 6: 验证治理文件**

运行：

~~~bash
git -C /root/projects/agentteams-competition-worktree diff --check
rg -n 'CONTRIBUTING|SECURITY|AgentSwarm|AgentTeams|凭证|Token|API Key|@wanghaowei06-ui|competition-v1.2' \
  /root/projects/agentteams-competition-worktree/CONTRIBUTING.md \
  /root/projects/agentteams-competition-worktree/SECURITY.md \
  /root/projects/agentteams-competition-worktree/CODE_OF_CONDUCT.md \
  /root/projects/agentteams-competition-worktree/MAINTAINERS.md \
  /root/projects/agentteams-competition-worktree/.github/PULL_REQUEST_TEMPLATE.md \
  /root/projects/agentteams-competition-worktree/.github/ISSUE_TEMPLATE/*.yml
~~~

使用 YAML 解析器检查 Issue forms；若环境没有 YAML 解析器，则对照 GitHub Issue Form schema 检查顶层 `name`、`description`、`body`、字段 `id` 和 `type`。

- [ ] **Step 7: 提交治理文件**

~~~bash
git -C /root/projects/agentteams-competition-worktree add CONTRIBUTING.md SECURITY.md CODE_OF_CONDUCT.md MAINTAINERS.md .github/PULL_REQUEST_TEMPLATE.md .github/ISSUE_TEMPLATE/feature_request.yml .github/ISSUE_TEMPLATE/bug_report.yml
git -C /root/projects/agentteams-competition-worktree commit -m "docs: add AgentSwarm contribution and security governance"
~~~

### Task 4: 增加可运行示例和正式发行说明

**Files:**
- Create: `examples/README.md`
- Create: `docs/releases/competition-v1.2.md`
- Modify: `README.md`
- Modify: `README.en.md`
- Modify: `docs/competition-reproduction.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: 已验证的 embedded 安装、`make verify`、`make test-installed`、`make replay` 命令和 `competition-v1.2` 版本信息。
- Produces: 外部评委可复制的第一条真实任务示例和正式版本说明。

- [ ] **Step 1: 编写 examples/README.md**

示例顺序为：切换 `competition-v1.2`；配置评委自己的 `AGENTTEAMS_LLM_API_KEY` 和管理员密码；运行 `make build-openclaw-base`、`make install-embedded`、`make wait-ready-embedded`；运行 `make verify`；执行 `make replay TASK="请在 Matrix 房间中回复一句可识别的中文确认，并说明你是 Manager"`；用 `docker ps`、Element Web 或 `make test-installed TEST_FILTER="01"` 检查真实结果；最后用 `make uninstall-embedded` 清理。示例只能描述期望观察点，不能写固定的伪造回复或预录日志。

- [ ] **Step 2: 编写 competition-v1.2 发布说明**

发布说明包含：版本/tag；AgentTeams 上游链接；本发行版定位；公开内容；排除内容；安装交付物；外部模型和 Docker/Kubernetes 前置条件；复现命令；验证命令；已知限制（外部依赖和 Python/Docker 范围依赖）；旧 `competition-v1.1` 保留策略；当前没有上游合并贡献、第三方采用或共同维护声明的事实。

- [ ] **Step 3: 补充 README 和比赛指南的发布入口**

将 `competition-v1.2`、发布说明、示例和版本记录加入中文/英文 README 与比赛指南；所有复制命令在同一版本中使用一致的 `VERSION`、镜像 tag 和固定 checkout。

- [ ] **Step 4: 更新 CHANGELOG.md**

将本次整理列为 `competition-v1.2` 的文档/治理变更，链接发布说明和本仓库提交历史；不要把 AgentTeams 上游历史 release notes 复制为 AgentSwarm 的发行内容。

- [ ] **Step 5: 检查示例不含敏感值**

运行：

~~~bash
if rg -n -i '(sk-[A-Za-z0-9]|ghp_[A-Za-z0-9]|AGENTTEAMS_.*(TOKEN|PASSWORD)=.{8,}|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|runtime\\.env)' \
  /root/projects/agentteams-competition-worktree/examples \
  /root/projects/agentteams-competition-worktree/docs/releases/competition-v1.2.md; then
  exit 1
fi
git -C /root/projects/agentteams-competition-worktree diff --check
~~~

- [ ] **Step 6: 提交示例和发行说明**

~~~bash
git -C /root/projects/agentteams-competition-worktree add examples README.md README.en.md docs/competition-reproduction.md docs/releases/competition-v1.2.md CHANGELOG.md
git -C /root/projects/agentteams-competition-worktree commit -m "docs: publish AgentSwarm competition v1.2 guide"
~~~

### Task 5: 完整验证、创建 tag 并推送

**Files:**
- Verify: Tasks 1-4 的全部文件
- Verify unchanged: `/root/projects/agentteams` 主开发工作区

**Interfaces:**
- Consumes: 任务 1-4 的已提交文档和现有运行时代码。
- Produces: 一个可干净克隆、可检查、可复现的 `competition-v1.2` 公开 tag。

- [ ] **Step 1: 验证公开工作区和主工作区边界**

运行：

~~~bash
git -C /root/projects/agentteams-competition-worktree status --short
git -C /root/projects/agentteams status --short
git -C /root/projects/agentteams-competition-worktree diff competition-v1.1..HEAD --name-only
~~~

公开工作区必须无未提交文件；主工作区原有 Dashboard 未提交路径必须仍在，且不得出现在公开提交文件列表中。

- [ ] **Step 2: 做敏感路径和关键文件审计**

运行：

~~~bash
PUBLIC=/root/projects/agentteams-competition-worktree
if git -C "$PUBLIC" ls-files | rg '(^|/)(testweaver/evidence|evidence|node_modules|\\.next|__pycache__)(/|$)|(^|/)runtime\\.env$'; then
  exit 1
fi
test -f "$PUBLIC/LICENSE"
test -f "$PUBLIC/NOTICE"
test -f "$PUBLIC/CONTRIBUTING.md"
test -f "$PUBLIC/SECURITY.md"
test -f "$PUBLIC/docs/dependencies.md"
test -f "$PUBLIC/docs/open-source-boundary.md"
test -f "$PUBLIC/examples/README.md"
~~~

- [ ] **Step 3: 验证 Markdown 链接目标**

对根 README、治理文件、比赛指南、依赖/边界文档和发布说明中的相对链接逐一确认目标文件存在；外部链接只检查 URL 文本与目标仓库/上游地址，不把网络可达性误当成本地复现成功。

- [ ] **Step 4: 运行现有测试和静态检查**

运行：

~~~bash
cd /root/projects/agentteams-competition-worktree
python3 -m unittest discover -s testweaver/adapters/tests -p 'test_*.py'
cd dashboard && npm test && npm run lint && npm run typecheck
cd ..
bash -n scripts/testweaver-config-preflight.sh install/agentteams-install.sh install/agentteams-verify.sh
git diff --check
~~~

文档整理不改变运行时代码；如果测试发现主工作区并发变更影响当前工作区，应记录实际失败原因，不擅自修改运行时代码来“修绿”。

- [ ] **Step 5: 干净克隆检查**

创建临时目录并从公开工作区克隆 `agent-swarm-public`，检查 README、许可证、治理文件、版本文件和排除路径；在干净克隆中再次运行适配器测试和脚本语法检查。不要把临时目录或构建缓存加入公开工作区。

- [ ] **Step 6: 创建并验证不可变版本 tag**

确认 `competition-v1.2` 不存在后，在最终已验证 commit 上创建 annotated tag：

~~~bash
git -C /root/projects/agentteams-competition-worktree tag -a competition-v1.2 -m "AgentSwarm competition reproduction snapshot v1.2" HEAD
git -C /root/projects/agentteams-competition-worktree show --no-patch --decorate competition-v1.2
~~~

不得覆盖已存在的 tag；确认 `competition-v1.1` 的对象仍保持不变。

- [ ] **Step 7: 推送并回读远程状态**

~~~bash
git -C /root/projects/agentteams-competition-worktree push --atomic competition agent-swarm-public:main refs/tags/competition-v1.2
git -C /root/projects/agentteams-competition-worktree ls-remote competition refs/heads/main refs/tags/competition-v1.2 'refs/tags/competition-v1.2^{}'
git -C /root/projects/agentteams-competition-worktree status --short
~~~

远程 `main` 与 `competition-v1.2` 的 peeled commit 必须相同；最后回读 GitHub raw `README.md` 和发布说明，确认默认中文入口已生效。

- [ ] **Step 8: 交付结果**

最终回复提供：仓库 URL、`competition-v1.2` tag URL、最终 commit、默认中文 README、治理/依赖/复现文档入口、验证命令结果，以及主工作区未提交内容仍被保留的说明。

