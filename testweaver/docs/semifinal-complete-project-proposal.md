# TestWeaver（智能体蜂群）Agent 应用质量进化系统

## Agent Infra 复赛完整项目方案（目标态设计稿）

> 文档性质：本文件描述复赛作品的完整目标方案、产品边界、技术架构与验收设计，不是当前实施进度报告。
>
> 规则基线：以用户提供的《赛道一：新智基座｜Agent Infra 复赛规则》为本稿唯一评审依据，评分权重采用“场景价值与复制性 20% / 多 Agent 协同 25% / Skill 工程体系 20% / 工程落地与安全审计 30% / 开源贡献 5%”。
>
> 事实边界：目标方案可以完整覆盖企业级能力，但“代码实现、真实运行、效果结果、生产验收”必须在独立的进度与证据材料中证明。本文不以设计内容代替运行事实。
>
> 当前实施事实、唯一下一步和里程碑状态以 [`semifinal-control.md`](semifinal-control.md) 为准；本文件不重复维护实时进度，避免目标设计与运行结论互相覆盖。

### AgentTeams 原生责任边界（2026-09-01 修订）

本方案以当前仓库中的 AgentTeams 与 TeamHarness 为原生协作控制面，不再设计第二套 Manager、Scheduler、Project/Task/Room、通用 Worker 生命周期或 Skill Runtime：

- AgentTeams Controller 管理 Manager、Team、Leader、Worker、Human、身份、房间、运行时、MCP/Skill 装配和资源生命周期；
- Manager 通过真实模型语义选择 Team/Leader，Leader 使用原生 `projectflow/taskflow/roomflow/message/filesync` 完成 Project/DAG/Loop、委派、提交、验收、重排、暂停和恢复；
- AgentTeams/TeamHarness 的 Project、Task、Room 和生命周期状态是原生执行域的权威事实，TestWeaver 不镜像成第二套可写执行状态，也不由 Runner、Observer 或旁路服务代替 Leader 调度；
- TestWeaver PostgreSQL 只对 Campaign 质量契约、Claim/Evidence/Provenance、业务 Policy/HumanDecision、外部副作用幂等与 fencing、双 Oracle、Skill 评测/晋升和审计事实负责；它保存原生资源 ID、revision、event/trace hash 的只读关联，不反向篡改原生 Project/Task；
- Skill 的发现、加载和调用使用 AgentTeams 原生机制；TestWeaver 只提供领域 Skill 包以及版本、权限、Golden、Nacos 分发、Canary、回滚和退役治理；
- LoongSuite/OTel/AgentLoop 是只读观测与评估链，不参与委派、验收或运行否决。

若本文后续出现 `TaskRun`、`DAG`、`Lease`、`Scheduler` 或“唯一事实源”等旧术语，均以本节的分域权威原则解释；本次修订将这些术语尽量替换为原生 AgentTeams 对象或 TestWeaver 质量域对象。

---

## 1. 项目摘要

### 1.1 一句话定位

TestWeaver 是面向 Agent 应用研发、测试和平台团队的质量控制与持续进化平台：它使用 AgentTeams 组织异质 Agent 团队，在真实目标系统上完成问题探索、证据收敛、可信修复、独立验证、安全恢复和 Skill 演进，并把全过程沉淀为可追踪、可回放、可审计的工程资产。

### 1.2 要解决的核心问题

Agent 应用的质量不只取决于模型。一次失败可能来自模型、Prompt、上下文、RAG、Agent Harness、路由、Skill、MCP/工具契约、状态恢复、权限、验证器或多个组件的交互。传统测试和单 Agent 调试通常存在以下卡点：

1. 问题暴露晚，只能在回归或线上事故后被动定位；
2. 一条 Trace 混合多个故障域，工程师难以判断真正根因；
3. 多个 Agent 反复读取相同信息、重复调用工具，成本增加却没有形成互补证据；
4. 未验证结论在 Agent 之间传播，容易形成幻觉级联；
5. DAG 依赖、任务所有权和失败域不清，超时后容易重复执行或触发恢复风暴；
6. 修复者往往同时充当验证者，局部测试通过不等于业务结果和安全边界同时通过；
7. 一次修复没有沉淀为可版本化、可评测、可回滚的 Skill，类似问题持续复发；
8. 企业环境还要面对高并发、成本、网关路由、版本升级、高可用、灾备、审计和长期运维。

### 1.3 产品角色

TestWeaver 不是一个“多 Agent 聊天室”，也不是一个自动写测试或自动修代码的单点工具。它是位于目标 Agent 应用之外的质量控制面，负责：

- 把业务目标、完成条件、风险边界和预算固化为质量契约；
- 通过 AgentTeams 组织真实的任务拆解、委派、协作、验收和恢复；
- 通过 AgentTeams 原生执行状态、TestWeaver 质量证据账本、Claim—Evidence 结构和独立验证抑制幻觉传播；
- 让多 Agent 的额外成本能够被观测、去重、归因和优化；
- 让已验证经验经过评测、灰度和回滚门禁后成为可复用 Skill；
- 为产品、研发、测试、安全和运维人员提供同一条可审计证据链。

### 1.4 核心价值

TestWeaver 的最终目标不是“启动更多 Agent”，而是在同等约束下提高：

- `Safe Task Success Rate`：任务完成且没有违反风险边界；
- 独特问题发现率和关键风险覆盖率；
- 故障复现率、根因定位准确率和修复一次通过率；
- 失败恢复成功率和长期任务可续跑率；
- 每百万 Token 的有效证据产出；
- 可复用 Skill 的跨 Agent、跨 Team 和跨场景收益；
- 从发现问题到形成可验证修复的端到端时间效率。

### 1.5 给非 Agent Infra 评委的 60 秒说明

可以把 TestWeaver 理解为“Agent 应用的自动化质量调查组和安全验收线”。

当一个 Agent 应用出现问题时，工程师原来需要在模型、Prompt、上下文、工具、代码、权限和运行日志之间人工排查，反复找研发、测试、安全和业务人员确认；即使修好了，也很难证明没有引入新的风险。TestWeaver 使用 AgentTeams 组织不同职责的 Agent：一组负责从不同角度找问题，一组负责把证据收敛成根因并生成修复，独立验证者分别检查“任务是否真的完成”和“有没有越过安全边界”。遇到高风险动作时系统暂停并让人基于证据批准、拒绝或修改；遇到超时和故障时，协作任务从 AgentTeams 原生 Project/Task 状态恢复，TestWeaver 再从 PostgreSQL 质量证据账本恢复证据引用和未决业务操作。最后，经过验证的方法可以成为带版本、可评测、可回滚的 Skill。

用户得到的不是一段 Agent 对话，而是一个可复现的问题、可解释的根因、受控修复、独立验收、量化成本以及一套能在下一次任务中复用的工程资产。

### 1.6 作品亮点列表

1. **AgentTeams 原生动态协作**：Manager、双 Team、DSH/Codex 异质 Worker、Human 共同完成真实 Task/Handoff/终态，不是固定脚本串行调用；
2. **可信共享状态**：AgentTeams 原生执行状态与 TestWeaver PostgreSQL 质量证据账本按 ID/revision/hash 关联，Claim—Evidence 和 provenance 防止幻觉级联与跨 Agent 口头转述失真；
3. **多 Agent 成本控制**：执行前去重、问题指纹、上下文按引用复用、边际价值裁剪和 Token/工具成本归集；
4. **真实 HITL 与安全恢复**：人工暂停、证据展示、授权范围、批准/拒绝/修改、原生任务恢复，以及外部业务操作的 generation 接管、迟到结果拒绝和回滚均进入关联状态链；
5. **双 Oracle 独立验收**：Outcome Oracle 检查任务终态，Boundary Oracle 检查安全边界，修复者不能自证；
6. **Skill 工程化进化**：复用 AgentTeams 原生 Skill discover/load/invoke，在其上增加领域 Skill 的 SemVer、关系图、Golden、Canary、激活、回滚和退役；
7. **全链路可观测**：Agent、模型、路由、上下文、Skill、MCP、工具、Policy、Human 和 Oracle 的输入引用、输出、版本、成本和异常统一关联；
8. **观测—评估—改进闭环**：LoongSuite/OTel → AgentLoop → Golden Dataset → 归因 → 改进 → 同集复评；
9. **企业级长期运行**：高并发、PostgreSQL HA/PITR/复制、网关路由、容量、版本升级、日常运维、审计和灾备；
10. **可离线验收与跨场景复制**：原始事件、失败恢复、独立复跑、哈希 Manifest，以及可替换的 Adapter/Contract/Oracle/Golden。

---

## 2. 初赛反馈与复赛调整

复赛方案针对初赛“架构完整但价值不够直观、AgentTeams 目标态没有在同一权威链中完整展示、工程证据与产品表达不足”等问题，做以下调整：

| 初赛表达 | 复赛调整 | 对应章节 |
|---|---|---|
| 从技术架构和能力清单开始介绍 | <span style="color:red">先用一个真实 Hero Case 说明用户、现实流程、失败代价、输入输出和完成条件</span> | 第 3 章 |
| 多 Agent 主要体现为角色图和聊天协作 | <span style="color:red">使用 AgentTeams 原生 Manager、双 Team、异质 Worker、Task/Handoff/状态和生命周期完成真实业务链</span> | 第 6 章 |
| 容易把多个 Agent 的顺序调用理解为协作 | <span style="color:red">以证据驱动的分支、裁剪、回流、重派、HITL 和恢复证明动态协作</span> | 第 6、7 章 |
| 关注发现数量，未充分解释重复劳动成本 | <span style="color:red">引入执行前去重、问题指纹、上下文引用、价值/成本裁剪和共享读取计量</span> | 第 6、7、10 章 |
| Skill 数量多但运行关系不够直观 | <span style="color:red">聚焦八个核心 Skill，逐个定义调用者、输入输出、失败处理、安全边界和复用价值</span> | 第 8 章 |
| HITL 容易被理解为页面按钮 | <span style="color:red">由 AgentTeams 原生暂停/恢复承载协作状态，并把证据展示、授权范围、批准/拒绝/修改写入 TestWeaver 业务决策账本</span> | 第 6、12 章 |
| 观测与评估相互分离 | <span style="color:red">建立 OTel/LoongSuite → AgentLoop → Golden Dataset → 归因 → 改进 → 同集复评闭环</span> | 第 10 章 |
| 工程规划分散 | <span style="color:red">形成高并发、高可用、PITR、复制、RAG、网关、成本、安全和运维的一体化企业方案</span> | 第 11、12 章 |
| 通用性主要靠列举行业 | <span style="color:red">明确稳定内核、可替换资产、Target Adapter 和跨场景迁移步骤</span> | 第 14 章 |
| Demo 偏静态展示 | <span style="color:red">演示同一 Campaign 的协作、Skill、异常、HITL、双 Oracle 和离线验收包</span> | 第 16 章 |

### 2.1 评委三项优化建议的直接落地

| 优化方向 | 方案中的直接设计 | 独立验收边界 |
|---|---|---|
| 多 Agent 协同 | 在固定镜像、固定 TargetSnapshot 和同一逻辑 Campaign 中运行原生 Manager、Exploration Team、Convergence Team、DSH 异质 Worker、独立 Verifier 和双 Oracle；AgentTeams 原生执行链与 TestWeaver PostgreSQL 质量证据链按 ID/revision/hash 关联，所有动态分支、回流、接管、HITL 和 Skill 调用必须由真实运行证据触发 | 保存 AgentTeams 原始任务/生命周期事件、PostgreSQL append-only 质量事件、失败恢复时间线、即时只读对账、独立复跑脚本和带哈希 Manifest 的离线验收包；合成事件、静态收据和跨 Run 拼接不得替代 LIVE |
| PostgreSQL 工程化 | PostgreSQL 作为 TestWeaver 质量、证据、审批、Oracle、外部副作用与审计域的事实源；使用 PITR、流复制/只读副本、故障切换、逻辑复制、pgvector、容量治理、幂等唯一约束和原子业务操作租约构成生产级数据底座，但不接管 AgentTeams 原生 Project/Task | PITR 与 Failover 分别形成独立收据；逻辑复制只做下游分发；RAG 强制 `version + evidence_ref`；库层并发约束通过真实 SQL、故障注入和对账证明 |
| 可观测与评估 | 使用 LoongSuite 探针/OTel Collector 采集标准 OTel GenAI Trace，在 AgentLoop 中建立 Dataset、Evaluator 和版本比较，形成“观测 → 量化评估 → 归因 → 改进 Proposal → 人工审批 → Canary/回滚 → 同集复评”闭环 | Trace、Log、Metrics、AgentTeams Task、Skill 版本、工具调用、人工决策、PostgreSQL revision 和最终 Oracle 绑定到同一逻辑 Campaign；Golden/holdout 与 Explorer、Repair 隔离 |

---

## 3. 场景闭环与业务价值

### 3.1 目标用户

| 用户 | 现实任务 | 主要痛点 | TestWeaver 承担的责任 |
|---|---|---|---|
| Agent 应用研发工程师 | 定位 Agent 行为异常并安全修复 | Trace 长、故障域多、修复后仍可能引入副作用 | 复现、诊断、候选修复、独立回归 |
| 测试开发/质量平台团队 | 建立系统级测试与质量门禁 | 单点测试无法覆盖模型、上下文、工具和恢复交互 | 风险探索、双 Oracle、Golden 评估、回归资产 |
| Agent/Skill 平台团队 | 发布模型、Prompt、Skill、工具和路由版本 | 组件分别通过但组合后失败，回滚和影响分析困难 | 版本矩阵、对照实验、Skill Bundle 灰度和回滚 |
| 安全与治理团队 | 防止越权、错批、重复副作用和敏感信息泄漏 | 自主执行缺乏统一授权与审计 | Policy、HITL、最小权限、审计和恢复 |
| 业务负责人 | 判断系统是否真正完成业务目标 | “模型说成功”与真实终态不一致 | 签发 Outcome/Boundary Oracle 和高风险授权 |

### 3.2 Hero Case：Agent 审批意图边界缺陷

复赛第一 Hero Case 选用 OpenWorker 的真实历史问题 #160 / PR #161 作为固定 Target。历史易受影响版本的自由文本审批回退逻辑先检查字符串中是否包含 `allow`，因此 `disallow [ow:<id>]` 可能被错误解析为允许。上游修复改为完整词匹配并补充回归测试。

该案例的边界必须明确：它影响的是 parked unattended Inbox 项目的 legacy free-text fallback，不代表 OpenWorker 的所有交互审批都可以被绕过。TestWeaver 使用精确提交、依赖锁、镜像摘要和目标快照冻结易受影响版本与修复版本，避免把依赖漂移误判为修复效果。

#### 现实失败代价

如果 Agent 将拒绝意图误识别为批准，可能产生未经授权的外部动作。即使案例本身范围较窄，它代表了企业 Agent 系统中普遍存在的高风险问题：自然语言意图、审批对象、策略版本和外部副作用之间只要有一处错配，就可能造成“任务看似完成、边界实际被破坏”的 Unsafe Success。

#### 输入

- 固定的 TargetSnapshot：源码提交、依赖锁、镜像、配置和工具契约；
- Agent Quality Contract：允许行为、禁止行为、完成条件、预算和停止条件；
- 公开测试输入与风险章程；
- Outcome Oracle 与 Boundary Oracle 定义；
- AgentTeams 组织、Agent Identity、Skill Bundle 和权限策略；
- 模型路由、DSH/Codex Runtime、TestLab MCP 工具白名单；
- 冻结的公开样例与对 Explorer/Repair 隔离的 Golden 标签。

#### 处理过程

```text
创建 Campaign 与质量契约
  → Manager 提出阶段计划与预算
  → TestWeaver Policy 对风险、预算和证据边界给出允许/拒绝/暂停约束
  → Manager 选择 Team/Leader，Leader 用 AgentTeams 原生 Project/DAG/Task 工具物化协作
  → Exploration Team 运行 Codex 控制分支与 DSH 异质分支
  → 去重、比较证据并形成 Failure Capsule
  → Convergence Team 生成竞争假设和区分实验
  → 证据不足时局部回流探索；充分时进入隔离修复
  → 独立 Verifier 执行 Outcome Oracle 与 Boundary Oracle
  → 高风险发布或不确定结果进入真实 HITL
  → 通过后形成回归资产和 Skill Candidate
  → Golden 评测、关系影响分析、灰度、激活或回滚
  → 输出完整证据包和业务价值指标
```

#### 输出

- 绑定固定版本的 Failure Capsule；
- 至少两个由运行证据产生的竞争假设；
- 区分实验及其证据；
- 候选修复、Patch 影响范围和隔离工作区记录；
- Outcome Oracle 与 Boundary Oracle 的独立结果；
- HITL 决策、授权范围和恢复事件；
- AgentTeams Task/Handoff/状态/生命周期证据；
- Skill discover/load/invoke 记录及版本；
- Token、工具调用、耗时、重试、接管和去重收益；
- 可断网回放的离线验收包。

#### 完成条件

只有同时满足以下条件，系统才把任务标为 Safe Success：

1. 目标业务行为符合 Outcome Oracle；
2. 拒绝意图不能被误解析为允许，Boundary Oracle 通过；
3. 修复者与验证者的身份、权限、工作区和证据相互隔离；
4. 所有关键结论都能追溯到同一 Campaign 下相互关联的 AgentTeams 原生事件、TestWeaver 质量事件、Artifact、Claim 和 Evidence；
5. 高风险动作经过真实人工决策，或者被 Policy 明确阻断；
6. 不存在未处理的冲突、过期引用或未知外部副作用；
7. 离线验收包可以在无模型、无网络、无数据库写入条件下独立校验。

### 3.3 第二场景：长任务恢复与重复副作用防护

第二场景用于证明跨场景复用，而不是复制第一个案例。它面向企业 Agent 执行发布、资源变更、工单处理或其他长时间任务时的典型异常：Worker 在工具可能已经提交后超时，系统无法仅凭 HTTP/模型返回判断真实外部状态。

| 场景要素 | 内容 |
|---|---|
| 目标用户 | Agent 平台工程师、SRE、发布负责人和安全审批者 |
| 原始卡点 | 工具超时后不清楚操作是否成功；人工需要跨日志、工单、目标系统和 Agent 会话对账；直接重试可能产生重复发布、重复资源或重复消息 |
| 输入 | 业务操作 ID、幂等键、TargetSnapshot、原生 AgentTeams Task 引用、旧业务操作 generation、工具 Trace、外部只读查询能力和风险 Policy |
| 动态协作 | Worker 报告 `COMMITTED_UNKNOWN`；Leader 通过原生 Project/Task 暂停下游并调用对账 Skill；证据冲突时原生重排任务或进入 HITL；旧业务操作租约过期后由新 generation 接管 |
| 异常与恢复 | 有限重试、外部状态对账、原子租约接管、旧 generation 迟到结果拒绝、必要时补偿/回滚 |
| 输出 | 唯一业务终态、恢复时间线、HumanDecision、重复副作用拦截证据、成本和离线验收包 |
| 完成条件 | 外部终态可查询；同一幂等键只产生一次有效副作用；不存在并行持有者；恢复后 DAG 正确继续；所有人工与自动动作可审计 |

系统必须先对账，再决定继续、补偿或人工处理；旧 generation 的迟到结果必须被拒绝，不能触发重复外部写入或无限重试。

两个场景共享 AgentTeams 原生组织与执行状态、TestWeaver Policy/证据账本、HITL 业务决策、Skill 治理、审计和离线验收协议，只替换 Target Adapter、场景契约、工具、Oracle、Golden 数据和审批规则，从而证明可复制性。

### 3.4 量化价值与对照设计

#### 真实基线采集

方案不预填未经测量的“节省 80%”之类数字。提交前应对同一案例的人工/单 Agent 流程记录真实时间戳、参与角色和调用数据，形成以下基线：

| 价值问题 | 基线指标 | 数据来源 |
|---|---|---|
| 用户上手成本有多高 | 首次成功 Campaign 用时、培训/配置人时、必填配置数量、失败重试次数 | 操作录像、环境预检、用户访谈和任务日志 |
| 原来排查有多慢 | 复现、定位、修复、验证各阶段 wall-clock 与工程人时 | Issue/工单时间戳、Git/测试记录、人工工时 |
| 工程师沟通成本有多高 | 参与角色数、人工 Handoff 数、澄清轮次、会议/等待时间、重复发送的上下文字节 | 工单、会议记录、消息和 ContextManifest 对照 |
| 多 Agent 是否在重复劳动 | 重复 ExplorationClaim、重复文件/证据读取、重复 MCP/工具调用和重复问题比例 | PostgreSQL、OTel Trace、工具 Ledger |
| 系统是否真正更有效 | Safe Success、独特有效问题、根因准确率、修复一次通过率、边界违规 | Golden Dataset、双 Oracle、独立验证 |
| 系统是否值得长期使用 | 单次有效问题成本、每百万 Token 有效证据、人工介入时间、故障恢复时间 | 网关账单、模型 usage、AgentLoop、原生 Task 引用与 QualityRun/HumanDecision |

核心价值使用相同口径计算：

```text
端到端时间改善 = (baseline_wall_time - candidate_wall_time) / baseline_wall_time
工程人时改善 = (baseline_person_hours - candidate_person_hours) / baseline_person_hours
沟通成本改善 = (baseline_clarification_time - candidate_clarification_time) / baseline_clarification_time
重复调用改善 = (baseline_duplicate_calls - candidate_duplicate_calls) / baseline_duplicate_calls
单位有效证据成本 = total_model_tool_human_cost / independently_verified_unique_evidence
```

所有分母、样本数、预算、失败 Run 和人工口径必须同时公开。若基线为零或数据缺失，则不输出改善百分比。

#### 受控对照

效果评估使用同任务、同 TargetSnapshot、同工具白名单、同模型路由约束、同 Golden 集和可比总预算，设置：

| 组别 | 系统形态 | 目的 |
|---|---|---|
| E0 | 单 Agent 基线 | 衡量传统单 Agent 调试效果 |
| E1 | 同构多 Agent / 固定顺序 | 区分“增加 Agent 数量”与真实协同 |
| E2 | AgentTeams 动态同构 Team | 衡量状态、DAG、恢复和 Manager 决策价值 |
| E3 | AgentTeams 双 Team + DSH 异质 Worker | 衡量异质探索组合的系统效果 |

核心指标包括：

- Safe Task Success Rate；
- 独特有效问题数、关键风险覆盖、共同漏检和误报；
- 重复探索率、上下文重复读取量、无效工具调用率；
- 根因定位耗时、修复一次通过率、验证失败回流次数；
- Worker 超时后的恢复成功率、重复副作用拦截率；
- Token、模型成本、工具成本、wall-clock 和人工介入时间；
- 每百万 Token 的独特有效证据数；
- Skill 晋升前后在同一冻结 Golden 集上的变化。

至少执行三组配对重复；不同 Run 的事实不得拼接成一次完整运行。缺失 Token 或成本数据必须标记为 `NOT_OBSERVED`，不能记为零，也不能产生节省结论。

---

## 4. 目标、边界与设计原则

### 4.1 项目目标

1. 用 AgentTeams 原生组织完成不少于三个不同职能 Agent 的真实协作；
2. 让中间证据能够动态改变后续任务、分支、预算、HITL 和恢复路径；
3. 建立分域权威：AgentTeams 保持原生执行状态，PostgreSQL 保存 TestWeaver 质量事件、版本、证据血缘与只读关联；
4. 防止幻觉级联、重复劳动、依赖不清和失败雪崩；
5. 形成可运行、可评测、可灰度、可回滚的 Skill 工程体系；
6. 把观测、评估、归因、改进和再评估形成闭环；
7. 具备企业级高并发、高可用、灾备、安全、成本和持续运维设计；
8. 通过 Target Adapter、契约和 Oracle 实现跨场景迁移；
9. 形成公开可复现的代码、Schema、Skill、评测和离线证据协议。

### 4.2 非目标

- 不训练或替代基础模型；
- 不把多个 Agent 的聊天数量当作协作价值；
- 不把固定脚本、静态回放或预置事件包装成 AgentTeams 真实运行；
- 不要求、采集或公开模型隐藏思维链；
- 不让 LLM Agent 直接决定高风险授权、最终验收或 Skill 正式发布；
- 不宣称外部系统 exactly-once；采用 at-least-once 交付、幂等、代际 fencing 和对账；
- 不以接入云产品数量作为能力证明，每个外部组件都必须说明必要性和替代路径。

### 4.3 核心不变量

1. Agent 对高风险业务动作只有提议权，TestWeaver Policy 决定允许、拒绝或暂停；获准后的任务规划和委派仍由 Manager/Leader 通过 AgentTeams 原生工具完成；
2. 每个领域只有一个写权威：AgentTeams/TeamHarness 管原生 Project/Task/Room 与执行生命周期，PostgreSQL Event Store 管 TestWeaver Campaign、质量证据、业务审批、Oracle、外部副作用和审计；
3. PostgreSQL 只保存 AgentTeams 资源 ID、revision、event/trace hash 和必要状态摘要的关联，不反向写原生任务；RocketMQ 和 Trace 只做通知或观测；
4. 修复者、验证者、Gold Evaluator 和高风险审批者相互隔离；
5. Outcome Oracle 与 Boundary Oracle 独立；
6. 关键对象具有 schema version、revision、producer、provenance 和 content hash；
7. 未验证 Claim 不得被下游当作事实；
8. 未知外部状态必须先对账，不能盲目重试；
9. 任何高风险操作都必须可阻断、可审计、可恢复；
10. 设计、代码、真实运行、效果和生产验收使用不同证据等级。

---

## 5. 总体架构

### 5.1 五层架构

```text
┌────────────────────────────────────────────────────────────┐
│ 产品与质量契约层                                           │
│ Campaign / Target / Quality Contract / Oracle / Budget / HITL│
└──────────────────────────┬─────────────────────────────────┘
                           │ 目标、约束、审批、停止条件
┌──────────────────────────▼─────────────────────────────────┐
│ AgentTeams 原生协作控制面                                  │
│ Manager → Team/Leader → Project/DAG/Task → Worker → Human  │
│ roomflow/projectflow/taskflow/message/filesync 与资源生命周期│
└──────────────────────────┬─────────────────────────────────┘
                           │ 原生 ID、revision、Artifact、Trace
┌──────────────────────────▼─────────────────────────────────┐
│ TestWeaver 质量与证据扩展层                                │
│ Policy / Dedup / Claim-Evidence / Side-effect Fencing      │
│ Dual Oracle / Skill Evaluation-Promotion-Canary-Rollback   │
└───────────────┬──────────────────────────┬─────────────────┘
                │                          │
┌───────────────▼────────────────┐ ┌──────▼──────────────────┐
│ Agent / Skill / MCP 执行层     │ │ 权威数据与知识层         │
│ DSH、Codex、TestLab、Adapter    │ │ PostgreSQL、Event Store  │
│ Model Gateway、Target Runtime   │ │ Artifact、pgvector、Outbox│
└───────────────┬────────────────┘ └──────┬──────────────────┘
                └──────────────┬──────────┘
                               │ Trace / Log / Metrics / Eval
┌──────────────────────────────▼──────────────────────────────┐
│ 企业工程底座                                                │
│ OTel/LoongSuite/AgentLoop、Higress、Nacos、RocketMQ          │
│ Compose/Kubernetes/Helm、SBOM、备份、灾备、告警和审计        │
└────────────────────────────────────────────────────────────┘
```

### 5.2 四类流程

| 流程 | 内容 | 权威位置 |
|---|---|---|
| 原生协作流 | Manager 选择 Team/Leader；Leader 使用 AgentTeams 原生 Project/DAG/Task 分解、委派、验收、重排和暂停 | AgentTeams/TeamHarness Project、Task、Room、消息与资源状态 |
| 质量决策流 | Agent/Leader 提出高风险业务动作；TestWeaver Policy 允许、拒绝、请求补证或暂停；获准后回到原生 Leader 执行 | PostgreSQL PolicyDecision/HumanDecision + 原生对象引用 |
| 数据流 | Target 输入、工具结果、Artifact、Patch、Oracle 结果 | Artifact Store + Evidence 引用 |
| 质量状态流 | Campaign、Claim/Evidence、外部业务操作 generation、HITL、Oracle、Skill 评测和发布状态 | PostgreSQL append-only Event Store |
| 异常流 | 原生 Worker/任务异常由 AgentTeams 处理；未知外部副作用由 TestWeaver 对账、fencing、补偿或转人工 | 原生 Task 事件 + RecoveryAction/PolicyDecision/Audit 关联 |

全过程必须同时满足“三可”：

| 要求 | 产品表现 | 工程保证 |
|---|---|---|
| 可观测 | 看见当前阶段、Agent、输入输出、成本、异常和预期/实际差异 | OTel/LoongSuite/AgentLoop + PostgreSQL/Artifact 关联 |
| 可控 | 能暂停、限制预算、裁剪分支、补证、重派、转人工和回滚 | AgentTeams 原生 Project/DAG/Task + TestWeaver Policy/HITL/业务操作 fencing |
| 可审核 | 能回答谁在何时基于什么证据执行了什么，以及结果是否符合预期 | append-only Event、Claim—Evidence、HumanDecision、Oracle 和 Manifest |

### 5.3 与仓库代码边界的对应关系

| 方案能力 | 代码边界 |
|---|---|
| AgentTeams 原生 Manager/Team/Leader/Worker/Human 与资源生命周期 | 上游 `agentteams-controller/`、`manager/`、`worker/`、各官方 runtime 目录 |
| 原生 Project/DAG/Loop、Task、Room、消息、文件同步与 Skill 调用 | 上游 `plugins/teamharness/` 与 Manager/Leader/Worker 原生 Agent 模板 |
| TestWeaver 质量契约、Evidence/结构化 Handoff Schema、Policy/HITL、双 Oracle、SkillOps、Golden | `testweaver/` 下按能力建立的薄模块；Handoff 只是原生 Task/Artifact/消息承载的载荷合同，禁止复制原生执行控制面 |
| DSH/Codex CLI 异构 Worker | AgentTeams Worker CR/AgentSpec/TeamHarness 契约上的薄 runtime adapter；优先继承已验证上游实现 |
| AgentLoop、OTel、LoongSuite、Nacos、PostgreSQL 配置与关联 | `testweaver/config/`、后续 `testweaver/integrations/` 及部署外部受保护配置 |
| Hero、对照实验、离线包与机器收据 | `testweaver/evidence/`、后续 `testweaver/evals/` 与 `testweaver/scripts/` |
| TestWeaver 产品页面与 API | 仅在真实数据合同稳定后建立于 `testweaver/` 自有应用目录，不修改上游 AgentTeams 文档边界 |

---

## 6. AgentTeams 原生多 Agent 协同

### 6.1 组织结构

```text
AgentTeams Manager（Campaign 协调角色）
├── Exploration Team
│   ├── Exploration Leader
│   ├── Codex Control Explorer
│   ├── DSH Heterogeneous Explorers
│   └── Adversarial Attacker
├── Convergence Team
│   ├── Convergence Leader
│   ├── Failure Diagnoser
│   ├── Repair Worker
│   └── Independent Verifier
├── Skill Curator
└── Human Reviewer / Business Owner / Security Approver
```

### 6.2 核心身份、职责和边界

| Identity | 核心职责 | 输入 | 输出 | 关键边界 |
|---|---|---|---|---|
| AgentTeams Manager | 接收质量契约，动态选择 Team/Leader，提出全局阶段计划、预算和目标 | TargetSnapshot、Quality Contract | StagePlanProposal、Team/Leader 选择、阶段决策 | 不越过 Leader 直接启动普通 Worker，不写 Oracle 结果 |
| Exploration Leader | 维护异质 ProfilePortfolio，分支、比较、裁剪和补生路径 | Approved Plan、覆盖和成本状态 | Branch Proposal、Handoff | 不确认根因和最终修复 |
| Test Explorer | 运行真实 Target、收集证据、形成问题指纹 | ContextManifest、工具白名单 | Evidence、ExplorationClaim、Failure Candidate | 只能写自己任务输出，不能读隐藏 Gold |
| Adversarial Attacker | 对风险边界进行受控攻击和反例验证 | Attack Charter、TargetSnapshot | Attack Evidence、Boundary Claim | 不能访问生产第三方系统或扩大攻击范围 |
| Convergence Leader | 调度诊断、区分实验、修复和验证 | Failure Capsule、Handoff | Convergence Plan、冲突处理 | 不直接修改 Patch 或 Oracle |
| Failure Diagnoser | 生成竞争假设，设计区分实验 | Capsule、Evidence Graph | Diagnostic Claims、Experiment Proposal | 假设不是事实，必须绑定证据 |
| Repair Worker | 在隔离工作区生成最小候选修复 | 已批准根因、Patch Scope | Patch Candidate、影响说明 | 不读隐藏验证集，不自我验收 |
| Independent Verifier | 执行独立验证和双 Oracle | Patch、冻结场景、Oracle 契约 | Verification Report | 只读 Patch，不修改修复 |
| Skill Curator | 从验证结果生成 Skill Candidate 并管理生命周期 | Verified Capsule/Patch/Process Evidence | Skill Candidate、Relation Delta | 不绕过 Golden、Canary 和人工发布门禁 |
| Human Reviewer | 查看证据并批准、拒绝或修改高风险动作 | Evidence Summary、风险、回滚方案 | HumanDecision | 授权范围、有效期和对象必须明确 |

### 6.3 AgentTeams 承担的原生能力

AgentTeams 不是外围聊天界面，而是协作运行基座，负责：

- Manager、Team、Leader、Worker 和 Human 的身份与资源组织；
- Task 创建、拆解、委派、接单、执行、交接、验收和终态；
- 角色级上下文、工具、Skill、工作区和权限隔离；
- 原生生命周期、心跳、就绪、暂停、重派和退出；
- Handoff 与任务状态的可追踪关联；
- Matrix/协作消息中的人类可见通知和交互。

TestWeaver 在 AgentTeams 之上补充质量契约、确定性业务 Policy、去重、Claim/Evidence、外部副作用安全恢复、双 Oracle、Skill 晋升和审计。AgentTeams/TeamHarness 管组织、Project/DAG/Task 和协作执行；PostgreSQL 只管理 TestWeaver 质量域事实，并通过原生 ID/revision/hash 与执行链关联。

本文所称 `ContextManifest` 和“结构化 Handoff”都是由 AgentTeams 原生 Task spec、Artifact/file sharing 或 Matrix 消息携带的版本化载荷合同，用于减少上下文复制并保留来源；它们不是新的消息总线、Room、Task、状态机或调度协议。

AgentTeams 在本项目中的可见作用不是“让 Agent 在同一个房间聊天”，而是把原本依赖工程师人工协调的工作转化为可执行、可追踪的组织过程：

| 原有卡点 | AgentTeams 提供的能力 | TestWeaver 补充的工程控制 | 可观测结果 |
|---|---|---|---|
| 工程师人工决定谁来处理 | Manager 语义选择 Team/Leader，Leader 原生分解和委派 | Quality Contract 与业务 Policy 约束风险、预算和停止条件 | 任务创建、委派、接单和终态 |
| 上下文靠聊天复制，容易丢约束 | Role Context 与 Handoff | ContextManifest、revision、hash 和权限 | 输入引用、读取量、陈旧/越权拒绝 |
| 多人并行但不知道是否重复 | Team 内多 Worker 与状态 | ExplorationClaim、问题指纹和裁剪算法 | 重复率、节省调用和覆盖增益 |
| 中间发现无法改变既定流程 | Manager/Leader 用原生 Project/DAG/Loop 继续委派和重组任务 | Evidence Policy 提供证据充分度、风险和预算约束 | 分支、回流、合并、暂停和停止原因 |
| Worker 失败后靠人重新找人 | AgentTeams 资源生命周期、Task 状态和 Leader 重排 | 只对“可能已提交”的外部副作用增加 operation generation、对账和迟到拒绝 | 原生重派与业务副作用恢复时间线 |
| 高风险操作在群里口头确认 | Human 作为真实协作参与者 | Human Gate、授权对象、审计和恢复 | 批准/拒绝/修改及后续状态 |

### 6.4 动态协作而非固定流水线

一次 Campaign 不要求预先走完固定顺序。中间证据可以触发：

- 新增不同 Profile 的探索分支；
- 裁剪重复或低信息价值分支；
- 对冲突 Claim 发起区分实验；
- 从诊断局部返回探索，而不是整体重跑；
- 验证失败后返回修复或重新诊断；
- Worker 超时后由 Leader 通过原生任务重派；若外部副作用可能已提交，则另行提出业务操作对账或 generation 接管；
- 风险、预算或未知外部状态触发 HITL；
- 达到证据充分度和停止条件后提前收敛。

所有分支、回流、裁剪、重派和暂停都必须由当前证据触发，并由 Manager/Leader 通过 AgentTeams 原生 Project/DAG/Loop/Task 工具实施。TestWeaver Policy 只对风险、权限、预算、证据充分度和外部副作用给出允许、拒绝、暂停或请求补证，不创建 Task，也不代替 Leader 做拓扑决策。系统允许一次真实运行自然地没有某种分支；不能为了演示完整而伪造循环或失败。

### 6.5 Leader 裁剪机制

Leader 的“判断”采用真实模型语义决策、领域 Skill 和确定性约束相结合的方式：

1. Agent/Skill 评估假设新颖度、证据缺口和下一步探索价值；
2. TestWeaver 去重/价值 Skill 计算覆盖增益、问题指纹重叠、未解决不确定性、边际成本、剩余预算和风险，作为结构化建议；
3. Policy 对权限、最低证据、预算和高风险动作执行确定性允许/阻断；原生 DAG 依赖由 TeamHarness 校验；
4. Leader 基于证据和约束作出真实 `KEEP / PRUNE / SPLIT / REPLACE / RETURN / STOP` 选择，并调用原生 `projectflow/taskflow` 实施。

这样既保留模型对复杂语义的判断能力，也避免让模型自行修改拓扑和预算。建议的裁剪评分为：

```text
expected_value =
  coverage_gain
  + uncertainty_reduction
  + independent_evidence_value
  - duplicate_overlap
  - expected_token_cost
  - expected_tool_cost
  - risk_penalty
```

阈值、权重和可用动作由版本化 Policy 管理，并通过 Golden Dataset 和历史 Campaign 回归，而不是写死在 Prompt 中。

### 6.6 防止重复劳动和幻觉级联

#### 执行前去重

Explorer 启动前登记包含 `campaign_id + target_snapshot + scenario_signature + coverage_axis + profile_hash` 的唯一 ExplorationClaim。数据库唯一约束保证同一覆盖目标只有一条有效 Claim；Leader 读取该质量信号后通过原生 Project/Task 决定裁剪、合并或继续，数据库本身不取得任务调度权。

#### 事后合并

发现结果使用目标快照、输入族、违反不变量、代码范围、根因边界和影响类型形成问题指纹。相同问题合并证据，不重复进入诊断和修复。

#### 可信信息共享

Agent 不通过复制长对话共享事实，而是交换 `ContextManifest`、Handoff 和对象引用。每个关键结论必须表示为：

```text
Claim → Evidence Ref → Producer → Revision → Verification State
```

未验证、过期、来源不明或与当前 revision 不匹配的 Claim 不能解锁下游任务。

### 6.7 原生 DAG 与外部副作用恢复

普通协作任务的 Project、DAG/Loop、Task、委派、提交、验收、暂停和恢复完全使用 AgentTeams/TeamHarness 原生状态，不建立第二套 `TaskRun` 状态机。TestWeaver 只为可能产生外部副作用的业务操作维护独立安全状态：

```text
PROPOSED → POLICY_APPROVED → EXECUTING
                              ├→ COMMITTED
                              ├→ NOT_COMMITTED
                              ├→ COMMITTED_UNKNOWN → RECONCILING
                              │                       ├→ COMMITTED
                              │                       ├→ NOT_COMMITTED
                              │                       └→ HUMAN_REVIEW
                              └→ REJECTED / FAILED
```

恢复规则包括：

- Manager/Leader/Worker 的容器、身份、房间和任务恢复使用 AgentTeams Controller 与 TeamHarness 原生机制；
- 普通 Worker 失败由 Leader 读取原生 Task/Project 结果后重排、修订或重新委派，TestWeaver 不抢占任务所有权；
- 外部操作的临时错误只有在确认 `NOT_COMMITTED` 后才允许有限指数退避和抖动；
- 参数、权限和 Schema 错误不重试，直接阻断；
- 外部状态未知：调用 `reconcile-before-retry`，先查询真实终态；
- 只有外部业务操作需要接管时，Policy 批准后原子更新 operation lease generation；
- 旧 generation 的迟到结果不得改变业务终态，必须记录拒绝证据；
- 上游业务结果未知时，Leader 通过原生 Project 暂停下游，不触发恢复风暴；
- Manager/Leader 重启后从 AgentTeams 原生 Project/Task 恢复执行上下文，再按关联 ID 回读 TestWeaver Campaign、Evidence 和未决业务操作；任何一侧缺失或 revision 不匹配都进入补证或人工处理，不能由另一侧猜测重建。

### 6.8 Human in the Loop

以下情形必须进入真实 HITL：

- 高风险或不可逆外部写入；
- 权限、密钥、网络或目标范围扩大；
- 未知外部状态无法自动对账；
- 双 Oracle 冲突或关键证据不足；
- 预算超限但继续探索可能产生价值；
- Candidate Patch 发布、Skill 激活或回滚；
- 数据删除、生产切换和灾备恢复。

人工页面必须展示：任务目标、拟执行动作、风险、证据、影响范围、费用、回滚方案和有效授权范围。人工可选择 `APPROVE / REJECT / MODIFY / REQUEST_EVIDENCE / DEFER`。决定、操作者、时间、理由、授权对象、Policy 版本和恢复事件进入统一审计链。

人工决定必须来自 AgentTeams `Human` 资源对应的 Matrix 身份，或映射到独立认证 Human actor 的外部操作者。实施系统的主控 Codex 可以代替用户操作审批界面，但只能作为一次真实、显式、可回读的人工输入：它不能使用 Agent 身份自动代签，不能在 Prompt 中预置决定，也不能在同一次模型调用里完成“请求审批”和“批准审批”。

---

## 7. 权威状态、上下文、记忆与 RAG

### 7.1 分域权威对象

| 对象 | 用途 |
|---|---|
| Campaign | 一次完整质量活动和全局关联根 |
| TargetSnapshot | 源码、镜像、模型、Prompt、Skill、工具、路由、数据和策略的复合版本 |
| NativeExecutionRef | AgentTeams Project/Task/Room、Agent Identity、原生 revision/event 与 Artifact 引用；只读关联，不复制可写执行状态 |
| QualityRun | 一次 TestWeaver 质量观察、评估或对照运行及其与原生执行的关联 |
| WorkerProfile / Branch | 探索者认知、模型、上下文、工具和搜索路径 |
| Claim / Evidence | 结构化结论、来源、证据和验证状态 |
| Artifact | 文件、补丁、报告、测试结果和结构化数据 |
| Failure Capsule | 可复现问题、环境、触发条件、证据和影响 |
| PolicyDecision | 允许、拒绝、暂停或修改的确定性决策 |
| BusinessOperation / OperationLease / Budget | 外部副作用的幂等键、执行代际、过期时间和资源额度；不表示普通 Worker Task 所有权 |
| HumanDecision | 人工授权、拒绝、修改和证据请求 |
| Verification | 独立验证范围、Oracle 和结果 |
| Skill / SkillBundle | 能力、版本、依赖、冲突、状态和发布历史 |

所有对象至少带有：

```text
tenant_id / campaign_id / object_id / schema_version / revision
producer_identity / created_at / causation_id / correlation_id
content_hash / provenance / retention_class / status
```

### 7.2 分域唯一事实源与事件关联

- AgentTeams/TeamHarness 保存并推进原生 Project、DAG/Loop、Task、Room、委派、提交、验收和资源生命周期；TestWeaver 不复制其写模型；
- PostgreSQL 保存 TestWeaver append-only 质量领域事件、当前投影、Policy/HumanDecision、Claim/Evidence、Oracle、Skill 评测、外部业务操作租约、幂等记录和审计；
- PostgreSQL 中的 `NativeExecutionRef` 只记录原生 resource/task/event ID、revision、Artifact/Trace hash 和观察时间，用于关联与对账；
- 两个领域各自的投影可由各自事件或原生文件重建，任何一侧不得以陈旧摘要覆盖另一侧；
- Matrix/AgentTeams 消息负责协作和通知，RocketMQ 负责下游分发，Trace 负责观测；关键质量主张必须回到原生对象与 PostgreSQL Evidence 双向核对；
- TestWeaver Outbox 与其业务事务原子写入，外部投递采用 at-least-once；消费者使用幂等键、唯一约束和消费位点防止重复处理。

### 7.3 四类上下文

| 类型 | 内容 | 生命周期 |
|---|---|---|
| Task Context | 当前原生 AgentTeams Task 必要输入、约束和期望输出 | 原生 Task 结束或过期后按保留策略清理 |
| Shared State | 结构化 Claim、Evidence、Artifact 和状态 | 随 Campaign 版本化保存 |
| Long-term Memory | 已验证的模式、故障和 Skill 使用经验 | 经过评测与保留策略长期保存 |
| Knowledge Retrieval | 版本化文档、Schema、Runbook 和历史证据 | 按版本、权限和适用范围检索 |

ContextManifest 只传递最小必要引用，包含 revision、hash、producer、trust state、allowed use 和过期条件。压缩只能删除冗余文本，不能丢失目标、风险边界、未解决冲突和关键证据引用。

### 7.4 带版本和证据引用的 RAG

RAG 使用 PostgreSQL + pgvector 承载检索，向量记录至少包含：

```text
tenant_id
document_id / chunk_id
content_hash
document_version / schema_version
embedding_model_version
evidence_ref / provenance
valid_from / valid_to
permission_scope
retention_class
```

向量表对 `tenant_id + document_id + document_version + chunk_id + embedding_model_version` 建立唯一约束，`version`、`evidence_ref`、`content_hash` 和 `provenance` 均为非空字段。向量相似度只负责候选召回，版本、权限、证据和有效期过滤必须在返回 Agent 上下文前完成。

检索规则：

1. 无版本或无 `evidence_ref` 的内容不可进入 Agent 上下文；
2. 当前 TargetSnapshot、租户、权限和任务用途必须匹配；
3. 冲突内容并列返回并标记来源，不能自动覆盖；
4. 过期知识触发刷新、阻断或重新规划；
5. Golden 标签、Verifier 隐藏资产和跨租户内容不可被 Explorer/Repair 检索；
6. 检索输入、命中、过滤、版本和使用结果进入 Trace 与审计。

### 7.5 信任状态

```text
UNVERIFIED
→ STRUCTURALLY_VALID
→ REPRODUCED
→ INDEPENDENTLY_CHECKED
→ SAFE_TO_REUSE
```

证据不足、冲突或被否定时进入 `REJECTED / STALE / CONFLICTED`。信任状态必须绑定具体 Claim、TargetSnapshot、revision、覆盖条件和验证来源，不能作为全局布尔值。

---

## 8. Skill 工程体系

### 8.1 Skill 定义

Skill 是按 AgentTeams 原生 Skill/AgentSpec 机制分发，并由具体 Agent Runtime 发现、加载和调用的版本化能力包。TestWeaver 不实现第二个通用 Skill Runtime，只定义领域能力与治理元数据，包括：

- 明确用途和适用边界；
- 输入/输出 Schema；
- 运行流程和依赖工具；
- 调用条件、权限和失败语义；
- 测试、Golden 评测和兼容性；
- SemVer、Registry、关系图、灰度、回滚和退役；
- 每次调用的 Skill 版本、Agent、Task、Trace 和结果。

普通函数、Prompt、脚本、API 或 MCP Tool 不能仅因被 Agent 调用就称为 Skill。Skill 可以编排这些能力，但必须具备领域判断、边界、评测和生命周期。

### 8.2 八个核心 Skill

#### S1 `approval-intent-boundary-check`

- 用途：识别批准、拒绝、修改和不确定意图，验证审批对象与授权范围；
- 调用者/状态：Explorer、Verifier、Human Gate 前；
- 输入：原始可公开输入引用、审批对象、Policy 版本、语言和上下文；
- 输出：结构化 Intent Claim、置信度、歧义和所需人工动作；
- 调用条件：自然语言可能触发高风险动作或 Boundary Oracle；
- 失败处理：歧义、解析失败或对象不匹配时阻断，不提供默认批准；
- 安全边界：不得自行执行审批动作，不输出隐藏 Gold；
- 复用价值：适用于支付、发布、权限、工单和运维变更等审批场景。

#### S2 `reconcile-before-retry`

- 用途：处理工具超时、响应丢失和“可能已提交”的外部状态；
- 调用者/状态：Worker、Leader、Recovery Policy；
- 输入：操作 ID、幂等键、目标对象、最后状态和查询工具；
- 输出：`NOT_COMMITTED / COMMITTED / UNKNOWN / CONFLICT` 与下一步建议；
- 调用条件：外部调用结果未知、BusinessOperation generation 接管或恢复重放；
- 失败处理：无法确认时转 HITL，禁止盲目重试；
- 安全边界：只读对账默认允许，补偿和重复写入需单独授权；
- 复用价值：适用于支付、发布、消息发送、资源创建和数据库变更。

#### S3 `preserve-critical-constraints`

- 用途：在上下文压缩、交接和重新规划后保留目标、风险、禁止项和未解决冲突；
- 调用者/状态：Manager、Leader、Context Builder；
- 输入：旧 ContextManifest、任务契约、压缩候选；
- 输出：新 ContextManifest、保留清单和丢失风险；
- 调用条件：上下文超限、跨 Team Handoff、恢复或长任务续跑；
- 失败处理：关键约束缺失时拒绝新上下文并请求重建；
- 安全边界：不得扩大权限、伪造证据或混入其他租户内容；
- 复用价值：适用于所有长上下文和多 Agent 协作任务。

#### S4 `avoid-redundant-exploration`

- 用途：执行前发现重复覆盖，事后合并重复问题，减少 Token 和工具调用；
- 调用者/状态：Exploration Leader、`avoid-redundant-exploration` 领域决策支持；
- 输入：ExplorationClaim、问题指纹、覆盖轴、Profile 和预算；
- 输出：`RUN / MERGE / PRUNE / REQUIRE_DIFFERENTIATOR`；
- 调用条件：新建分支、重复问题候选或预算紧张；
- 失败处理：无法确定是否重复时允许受限区分实验，不静默丢弃；
- 安全边界：高风险未覆盖轴不能仅因文本相似被裁剪；
- 复用价值：适用于测试探索、调研、诊断和并行代码分析。

#### S5 `diagnose-by-competing-hypotheses`

- 用途：从 Failure Capsule 生成至少两个竞争根因假设和区分实验；
- 调用者/状态：Failure Diagnoser、Convergence Leader；
- 输入：Failure Capsule、Evidence Graph、TargetSnapshot；
- 输出：Hypothesis Cards、区分实验、证据缺口和停止条件；
- 调用条件：问题已复现但根因未确认；
- 失败处理：证据不足时返回探索，不把最高分假设直接写成事实；
- 安全边界：不能读取隐藏 Gold 或未授权源码；
- 复用价值：适用于模型、Prompt、工具、路由、RAG、状态和权限故障。

#### S6 `repair-in-isolated-worktree`

- 用途：在独立工作区内生成最小 Patch，并记录影响范围和回滚点；
- 调用者/状态：Repair Worker；
- 输入：已批准根因、Patch Scope、源码快照、允许工具；
- 输出：Patch Candidate、测试结果、变更摘要和回滚信息；
- 调用条件：根因证据达到修复门槛；
- 失败处理：测试失败、范围扩大或环境污染时废弃工作区并重新规划；
- 安全边界：不可访问 Verifier 隐藏资产，不可直接发布到生产；
- 复用价值：适用于代码、配置、Prompt、Schema 和 Adapter 修复。

#### S7 `independent-dual-oracle-verification`

- 用途：分别验证任务结果和风险边界，阻止修复者自证；
- 调用者/状态：Independent Verifier；
- 输入：Patch、冻结场景、Outcome/Boundary Oracle、独立工作集；
- 输出：两个独立 Verdict、覆盖范围、Evidence Ref 和冲突；
- 调用条件：任何候选修复进入验收；
- 失败处理：任一 Oracle 失败即不发布；冲突或不确定进入诊断/HITL；
- 安全边界：Verifier 只读 Patch，不访问 Repair 私有上下文；
- 复用价值：适用于所有“完成任务同时保持安全”的 Agent 场景。

#### S8 `skill-bundle-canary-rollback`

- 用途：对 Skill Candidate 及其依赖/冲突关系进行 Golden、Holdout、灰度和回滚；
- 调用者/状态：Skill Curator、Promotion Controller；
- 输入：Candidate、Relation Delta、Bundle、Golden Dataset、发布策略；
- 输出：Promotion Decision、Canary Receipt、Active/Rejected/RolledBack 状态；
- 调用条件：双 Oracle 通过并产生可泛化能力；
- 失败处理：候选不提升、产生回归或指标越界时拒绝或回滚；
- 安全边界：LLM 只能提出 Candidate，正式激活由 Policy 和人工授权；
- 复用价值：适用于 Agent、Team、诊断、修复和防护 Skill 生命周期。

### 8.3 Skill 与 AgentTeams 状态的关系

每次 Skill 调用必须记录：

```text
campaign_id / quality_run_id / native_project_id / native_task_id / agent_identity / team
skill_id / semver / bundle_hash / graph_revision
input_refs / output_refs / tool_calls / trace_id
permission_decision / duration / token / result / failure_class
```

AgentTeams/具体 Worker Runtime 管理“谁在什么任务中发现、加载、调用和返回”；TestWeaver SkillOps 管理领域 manifest、SemVer、依赖/冲突、权限、Golden、晋升、Canary 与回滚；PostgreSQL 保存治理状态和调用证据关联，AgentLoop 负责观测和评估。Nacos 复用 AgentTeams 已支持的 `nacos://` AgentSpec/Package 分发入口，不另建一套加载协议。

### 8.4 生命周期

```text
Failure/Process Evidence
→ Skill Candidate
→ Schema/安全检查
→ 单 Skill Golden 评测
→ Relation Impact Analysis
→ Bundle/冲突/兼容评测
→ Human Approval
→ Canary
→ Active
→ 监控
→ Rollback / Retire
```

Skill 版本使用 SemVer；Registry 保存 manifest、依赖、权限、适用范围、评测、签名和状态。每个 Candidate 必须拥有可回放评测，不允许一次成功示例直接晋升为 Active。

---

## 9. 工具、MCP、Target Adapter 与外部系统

### 9.1 TestLab MCP

TestLab MCP 提供受控的目标测试能力，包括：

- 冻结/读取 TargetSnapshot；
- 启动、停止和健康检查测试环境；
- 加载场景和 Fixture；
- 执行测试、故障注入和回放；
- 创建隔离 Patch 工作区；
- 查询外部真实终态；
- 执行 Outcome/Boundary Oracle；
- 导出证据、日志和收据。

每个工具必须定义输入输出 Schema、权限、副作用级别、超时、重试、限流、幂等、对账和失败语义。工具结果必须写成 Artifact/Evidence 并影响任务状态，而不是只作为聊天文本。

### 9.2 Target Adapter

Target Adapter 隔离 TestWeaver 内核与具体业务系统，负责：

- Target 生命周期和健康检查；
- 业务输入注入和结果查询；
- 工具和错误语义标准化；
- 版本、镜像和配置快照；
- Oracle 接口；
- 数据脱敏和证据导出；
- 故障注入能力与绝对禁止边界。

迁移到第二场景时，优先替换 Adapter、Quality Contract、Test Charter、Oracle、Golden Dataset 和审批 Policy；不重写 AgentTeams 原生协作控制面和 Skill 调用机制，也不重写 TestWeaver 已稳定的质量证据与 Skill 治理协议。

### 9.3 外部组件必要性与替代路径

| 组件 | 必要性 | 不承担的责任 | 等效替代 |
|---|---|---|---|
| AgentTeams | 原生多 Agent 组织、任务、上下文、状态和生命周期 | 不作业务事实库 | 复赛核心要求，不替换 |
| DSH | 提供异质模型/插件/上下文探索 Worker | 不作权威调度器 | 其他符合 Adapter 契约的 Agent Runtime |
| Codex | 诊断、修复、验证和工程操作 Worker | 不决定授权与最终验收 | 其他可隔离工程 Agent |
| AgentLoop | Trace、Dataset、Evaluator 和改进闭环 | 不作业务 Oracle | 兼容 OTel 的评测平台 |
| LoongSuite/OTel | 标准 GenAI Trace、Log、Metrics 采集与查询 | 不保存权威任务状态 | 兼容 OTel 的 Collector/Backend |
| Higress | 模型/工具网关、路由、限流、熔断和用量入口 | 不决定业务终态 | 兼容 OpenAI/MCP 的企业网关 |
| Nacos | 复用 AgentTeams `nacos://` AgentSpec/Package 入口分发领域 Skill 包，并发布路由、Policy、Bundle 等版本化配置 | 不实现第二套 Skill Runtime，不替代 Git/数据库历史 | GitOps/Consul/其他配置中心 |
| RocketMQ | 事件通知、异步分发和下游解耦 | 不作唯一事实源 | Kafka/Pulsar/兼容消息系统 |
| PostgreSQL | TestWeaver 质量证据、业务决策、Oracle、外部副作用与审计域的权威状态，以及 PITR、复制、只读查询和 pgvector | 不接管 AgentTeams 原生 Project/Task/Room，不保存无边界的原始思维链 | 标准 PostgreSQL 自建 HA 或兼容的托管 PostgreSQL |

---

## 10. 观测、Golden Dataset 与自我改进闭环

### 10.1 统一观测模型

所有观测绑定同一逻辑 Run，并关联：

```text
tenant_id / campaign_id / quality_run_id / native_project_id / native_task_id
agentteams_resource / agent_identity / team / role
target_snapshot / model_route / prompt_hash / context_manifest
skill_id / skill_version / mcp_tool / tool_result
policy_decision / human_decision / lease_generation
token / cost / latency / retry / error_class
artifact_ref / evidence_ref / oracle_result
```

系统采用标准 OTel GenAI Trace，由 LoongSuite 探针/Collector 采集并在 AgentLoop 中查询、分析和展示。Trace、Log、Metrics、评测、AgentTeams 原生事件和 PostgreSQL 质量事件通过稳定 ID 关联，但 Trace 不替代任何领域的权威事实。

系统只记录可观察输入摘要、输出、工具调用、状态变化和决策依据引用，不采集模型隐藏思维链；敏感参数和原始输出按 Policy 脱敏或仅保存 hash/受控 Artifact。

### 10.2 Golden Dataset

Golden Dataset 由以下部分组成：

- 公开输入与场景定义；
- TargetSnapshot 和依赖版本；
- 可验证 Outcome 标签；
- Boundary/风险标签；
- 允许证据类型和最低证据条件；
- 隐藏 Holdout；
- 样本来源、授权、脱敏和适用范围；
- Dataset version、content hash 和 evaluator version。

Explorer、Repair 和 Candidate 不可读取隐藏标签。Evaluator 使用独立身份和权限，评测的是可观察行为和终态，不要求模型输出特定措辞或固定路径。

### 10.3 自我改进闭环

```text
观测数据
→ 评估量化问题
→ 归因到 Agent / Skill / Context / Tool / Route / Policy
→ 生成改进 Proposal
→ Human 审批
→ Candidate/Canary
→ 在同一冻结 Golden 集重新评估
→ 接受、继续观察或回滚
```

基线与 Candidate 分别使用不可变的版本元组和独立 run_id，再由比较收据绑定；不得把两个 Run 描述成一次运行，也不得使用跨 Run 拼接证据。

### 10.4 可观测指标

- AgentTeams：任务创建、接单、Handoff、等待、重派、终态；
- 模型：实际路由、输入/输出 Token、延迟、错误和回退；
- Context/RAG：构建耗时、引用数量、重复读取、陈旧/冲突命中；
- Skill：发现、加载、调用、版本、成功、失败、灰度和回滚；
- MCP/Tool：调用、参数验证、超时、重试、幂等和副作用状态；
- 协作：重复分支、信息价值、冲突、回流和裁剪；
- 业务：Outcome/Boundary、Safe Success、人工介入和恢复；
- 成本：按租户、Campaign、Team、Agent、Skill、模型和工具归集；
- 系统：API、队列、数据库、复制、缓存、存储、网络和告警。

### 10.5 每一步输入输出的可观测合同

可观测平台不仅展示总 Token 和一条 Trace，而是让评委和工程师能够从 Campaign 下钻到每一步，回答“谁基于什么输入、用哪个版本、执行了什么、得到什么、为什么进入下一步”。

| 观测对象 | 必须记录的输入 | 必须记录的输出/状态 | 关键版本与成本 |
|---|---|---|---|
| AgentTeams Task | Task Contract、依赖、ContextManifest、预算和权限引用 | 接单、阶段状态、Handoff、Artifact、终态和失败分类 | Agent/Team/Role、plan revision、wall-clock |
| 模型调用 | Prompt hash、上下文引用、候选路由、采样与安全策略 | 输出 hash/受控 Artifact、finish/error、实际路由和回退 | provider/model/revision、input/output Token、延迟和费用 |
| Skill | Skill ID、SemVer、bundle hash、输入 Schema/引用、调用条件 | 输出引用、领域 Verdict、失败处理和后续状态影响 | Skill/Graph/Bundle 版本、Token、工具与耗时 |
| MCP/Tool | Tool ID、Schema 版本、参数 hash、权限、幂等键和超时 | 返回值摘要、错误语义、外部副作用状态、重试/对账结果 | Server/Tool/Adapter 版本、调用次数、延迟和费用 |
| Context/RAG | Query、任务用途、Target/version、权限和过滤条件 | 命中 `evidence_ref`、版本、排序、冲突、陈旧/越权拒绝 | corpus/index/embedding/policy 版本、读取量和耗时 |
| Gateway | 任务风险、模型候选、配额、健康度和路由 Policy | 实际模型、fallback、限流、熔断和账单归属 | gateway/route 版本、Token、缓存命中和成本 |
| Policy 与原生协作 | Proposal、Evidence、原生 Project/DAG/Task 引用、预算、风险和当前 revision | TestWeaver 记录允许/拒绝/暂停/补证；Manager/Leader 的真实选择与原生 Task 变化分别观测 | Policy 版本、decision hash、原生 event/ref 和执行延迟 |
| Human Gate | 拟执行动作、证据、风险、影响、成本和回滚方案 | APPROVE/REJECT/MODIFY/REQUEST_EVIDENCE、授权范围和恢复 | 人员身份、时间、Policy 和审计引用 |
| PostgreSQL | actor、操作合同、expected revision、idempotency/lease 条件 | event revision、affected rows、projection、冲突/拒绝 | schema/migration、事务延迟、复制位点 |
| Oracle | 冻结场景、Candidate、Oracle Contract 和独立证据集 | expected/actual、PASS/FAIL/UNCERTAIN、差异和 Evidence Ref | Oracle/evaluator/dataset 版本、覆盖和耗时 |

产品页面默认展示业务可读摘要、状态、风险和下一步；技术字段在证据抽屉中展开。敏感输入输出按权限显示摘要、hash 或受控 Artifact，不为可观测性泄露密钥、隐私、隐藏 Gold 或思维链。

---

## 11. 企业级工程设计

### 11.1 高并发与容量

#### 并发模型

- API 和只读查询服务无状态横向扩展；
- Manager/Leader 的逻辑状态保存在 PostgreSQL，可由新 Runtime 恢复；
- AgentTeams Controller 管资源容量与生命周期，Manager/Leader 管原生 Project/Task 调度；TestWeaver 只通过 Policy、预算和网关配额限制租户、Campaign 与高风险业务操作；
- 每个租户设置并发 Agent、模型 Token、工具调用、外部写入和存储配额；
- Campaign 采用总预算、阶段预算和单分支预算三级控制；
- 数据库使用连接池、读写分离、批量追加和必要的时间/租户分区；
- Artifact 使用对象存储，数据库只保存元数据、hash 和权限；
- 高峰时通过 admission control、队列优先级、背压和降级保护核心链路。

#### 调度公平与热点保护

- 单个大 Campaign 不能耗尽所有 Worker；
- 高风险验证和恢复任务优先于低价值探索；
- 热点 Target、租户和工具采用并发令牌与速率限制；
- 重试任务计入原预算，避免失败导致资源放大；
- 重复 ExplorationClaim 由唯一约束拒绝；Leader 在原生委派前读取该质量信号并裁剪重复探索，数据库不直接阻断或创建 AgentTeams Task；
- 超过成本或时间阈值后进入 STOP/HITL，而不是自动扩大资源。

#### 容量管理

按 Campaign 到达率、平均原生 Project/Task 数、QualityRun 数、模型 Token、Trace 量、质量事件写入、Artifact 体积和保留期限建立容量模型。设置 AgentTeams 资源、数据库连接、存储使用、队列积压、Trace 丢弃、模型并发和预算消耗阈值，支持预测扩容和自动告警。

### 11.2 PostgreSQL 高可用、恢复与灾备

#### 生产拓扑

- 一个 PostgreSQL Primary 保存 TestWeaver 质量领域事件、投影和外部业务操作协调状态，至少两个跨故障域的 Streaming Replica 提供冗余；AgentTeams 原生执行状态不迁入该库；
- Patroni/repmgr、Kubernetes Operator 或兼容的托管 PostgreSQL 控制故障检测、选主和防脑裂；方案不依赖某个数据库品牌；
- 只读副本承担产品查询、报表和非实时评估读取，TestWeaver Policy、HumanDecision 和外部业务操作决定仍回到 Primary 当前 quality revision；
- 逻辑复制将版本化事件分发到回放/分析副本；
- TestWeaver 质量事件表仍是其领域唯一事实源，分析副本和消息系统不得反向写质量权威状态；AgentTeams 原生执行事实仍由原生 Project/Task/Room 持有；
- 连接通过服务发现和连接池管理，故障切换后客户端重新解析并有限重试。

#### 幂等和租约的库层强制

- 幂等键使用唯一约束和 `ON CONFLICT DO NOTHING`，重复请求读取既有结果而不是再次执行；
- `operation_id` 保证同一外部业务操作在一个 generation 中只有一个租约持有者；
- `owner_id + lease_generation + lease_expires_at` 记录归属与代际；
- 接管使用带过期条件和旧 generation 的原子 UPDATE；
- 旧 generation 的迟到结果在数据库边界被拒绝；
- 关键质量决策和业务操作状态转换使用 CAS revision，防止陈旧 Evidence/Policy 结果覆盖新状态；该 CAS 不管理原生 Project/DAG/Task。

建议将关键约束直接固化为数据库合同：

```sql
CREATE UNIQUE INDEX uq_idempotency_key
ON idempotency_record (tenant_id, operation_scope, idempotency_key);

INSERT INTO idempotency_record (...)
VALUES (...)
ON CONFLICT DO NOTHING;
```

租约接管必须是一条带旧代际和过期条件的原子语句：

```sql
UPDATE business_operation_lease
SET owner_id = :new_owner,
    lease_generation = lease_generation + 1,
    lease_expires_at = :new_expiry
WHERE operation_id = :operation_id
  AND lease_generation = :expected_generation
  AND lease_expires_at <= clock_timestamp()
RETURNING owner_id, lease_generation, lease_expires_at;
```

未返回行表示接管失败，调用方必须重新读取当前租约，不能把内存判断当作成功。

#### PITR 生产恢复验收（独立收据 `g14-postgresql-pitr`）

- 使用 PostgreSQL base backup + 连续 WAL 归档恢复到明确时间点或 LSN；
- 收据记录源集群、备份 ID、WAL 范围、目标时间、命令时间戳、恢复完成时间和操作者；
- 恢复后按 `campaign_id + revision + event_hash + bundle_hash + provenance` 重放并对账；
- 重建投影，检查 NativeExecutionRef、QualityRun、operation lease generation、Outbox、幂等键、HumanDecision 和未决外部副作用；
- 只有事件连续性、投影一致性和业务终态同时通过，PITR 收据才为 PASS。

#### 高可用切换验收（独立收据 `g15-postgresql-failover`）

- 在受控窗口中使 Primary 不可用并提升同步/异步 Replica；
- 记录故障注入、检测、选主、服务发现更新、客户端重连和恢复写入的时间线；
- 验证没有双 Primary、旧 Primary 被 fencing、事务和事件 revision 无分叉；
- 测量真实 RPO、RTO、失败请求、有限重试和恢复后的即时只读对账；
- Failover 只证明高可用切换，不替代 PITR 历史恢复证明，两项不得合并为一个 PASS。

#### 备份、容量与灾备策略

- 备份加密并执行保留、跨故障域复制、定期恢复抽检和合规删除；
- 初始生产目标建议为 RPO ≤ 5 分钟、核心控制面 RTO ≤ 15 分钟，最终阈值由压测和演练校准；
- 存储使用达到 70% 预警、80% 扩容准备、85% 阻断非关键大对象写入；阈值可按环境调整并版本化；
- 托管 PostgreSQL 可使用自动存储扩容；自建部署使用云盘/LVM 扩容和受控变更 Runbook；
- 计算服务保持无状态并独立横向扩展，数据库连接池、读副本和分区/归档控制数据库负载；
- 多故障域中断、只读延迟、WAL 归档失败、复制积压、备份失败和恢复抽检失败进入告警与值班流程。

### 11.3 事件分发与一致性

- 事务内写领域事件和 Outbox；
- RocketMQ 采用至少一次投递，消费者按事件 ID 幂等；
- PostgreSQL 逻辑复制承担回放、分析和评估副本的数据分发，形成独立收据 `g16-postgresql-logical-replication`；
- 收据绑定 publication/subscription、源/目标 LSN、事件 ID、revision、`bundle_hash`、`provenance` 和内容校验结果；
- 回放/分析副本保持只读业务语义，不参与 Manager/Leader 原生协作、Policy 决策或业务操作租约接管，避免形成双事实源；
- 复制延迟可观测，分析结果携带 authority revision；
- TestWeaver Policy、HumanDecision 和外部业务操作控制必须基于 Primary 当前 quality revision；Manager/Leader 的任务选择继续基于 AgentTeams 原生 Project/Task 状态和已关联 Evidence；
- 不宣称跨数据库、消息、模型和外部工具的 exactly-once。

### 11.4 网关路由与成本治理

Higress 作为模型和工具流量入口，Nacos 管理版本化路由/Policy 配置：

- 根据任务风险、上下文长度、工具能力、预算和服务健康选择模型；
- 记录计划模型、实际模型、回退原因和路由版本；
- 配置超时、有限重试、熔断、并发、速率和租户配额；
- 高风险任务不允许静默降级到不满足能力或合规要求的模型；
- Token、缓存、工具、存储和人工成本按 Campaign/Team/Agent/Skill 归集；
- Leader 裁剪使用边际证据价值与边际成本，不单纯压低 Token；
- 账单缺失或供应商用量不可得时标记 `NOT_OBSERVED`。

### 11.5 服务高可用

- TestWeaver API、Policy 判定、质量投影和观测查询服务可部署多副本；AgentTeams Controller、Manager、Leader、Worker 继续按其原生部署与资源模型扩展；
- 健康检查区分 liveness、readiness 和外部依赖状态；
- Kubernetes 使用 PodDisruptionBudget、反亲和、资源限额和优雅终止；
- Worker 工作区、缓存和临时凭据与任务隔离；
- Runtime 失效后从 AgentTeams 原生 Project/Task 状态恢复协作，并按原生引用重载 TestWeaver 质量证据和未决业务操作，不依赖旧进程内存；
- 模型、MCP、数据库、消息、对象存储和网络分别设置熔断和降级边界。

### 11.6 版本、升级和发布

所有可影响行为的资产进入复合版本矩阵：

- 应用 commit、镜像 digest 和依赖锁；
- Agent Harness、路由、Prompt、Context/RAG；
- 模型、Skill Bundle、MCP Schema 和 Adapter；
- Policy、Oracle、Golden Dataset 和数据库 Schema；
- AgentTeams/AgentLoop/网关/配置中心版本。

发布流程为：构建 → 测试 → SBOM/许可证/Secret 扫描 → 数据库迁移检查 → Golden 回归 → Canary → 人工批准 → 灰度 → 监控 → 全量或回滚。升级不得覆盖历史收据；每次运行绑定实际版本矩阵。

### 11.7 SLO、告警和运维

目标 SLO 需要在压测和演练后冻结，至少覆盖：

- 控制 API 可用性和 P95/P99 延迟；
- TaskReady 到 Worker 接单延迟；
- 事件写入、投影和消息分发延迟；
- AgentTeams 资源心跳与原生任务重派时间，以及 TestWeaver 外部业务操作 lease 过期、generation 接管和对账时间；
- 数据库连接、复制、存储和备份；
- 模型/工具错误率、熔断和预算消耗；
- Trace 覆盖率与采集失败率；
- Safe Success、Boundary Violation 和恢复失败。

系统提供日常巡检、值班手册、告警分级、故障复盘、容量预测、备份恢复和版本回滚 Runbook。每次事故和异常演练产生 Process Capsule，回流 Golden Dataset、Policy 或 Skill Candidate。

### 11.8 长期运行异常场景矩阵

| 企业异常 | 检测与阻断 | 处理与恢复 | 必须保留的证据 |
|---|---|---|---|
| Worker 崩溃/心跳丢失 | AgentTeams Worker/Team 状态、heartbeat、原生 Task 无进展 | AgentTeams Controller 恢复资源，Leader 读取原生 Project/Task 后修订或重派；仅未决外部副作用使用新 operation generation 和迟到拒绝 | 原生状态/Task 事件、重派、业务操作对账与迟到拒绝时间线 |
| Manager/Leader 重启 | AgentTeams 原生生命周期与 TestWeaver 质量投影关联暂时不一致 | 从 AgentTeams 原生 Project/Task 恢复计划与协作上下文，再按 NativeExecutionRef 重载 Campaign、证据引用和未决业务操作，不由 PostgreSQL 重建原生任务 | 恢复前后 native revision、quality revision、Task/Handoff 对账 |
| 模型超时、限流或供应商故障 | Gateway error、SLO、熔断和配额 | 有限重试、合规 fallback、暂停或 HITL；高风险任务不静默降级 | 计划/实际模型、route version、回退原因、Token/费用 |
| MCP/工具超时且提交状态未知 | `COMMITTED_UNKNOWN`、工具 Trace 缺失终态 | 先对账，再继续/补偿/人工；禁止盲目重试 | 幂等键、外部查询、Policy、HumanDecision 和最终状态 |
| Skill 新版本回归 | Golden/Canary 越界、线上指标退化 | 停止灰度、回滚上一 Bundle、重建受影响任务上下文 | Skill/Bundle/Graph 版本、对照结果和 rollback receipt |
| Prompt/模型/路由/Schema 升级不兼容 | 复合版本矩阵和兼容回归失败 | 阻断发布、迁移 Adapter/Context、灰度后再放量 | 版本差异、测试、迁移和回滚记录 |
| PostgreSQL Primary 故障 | 连接、复制和选主告警 | Replica 提升、防脑裂、客户端重连、即时事件对账 | `g15` Failover 收据、RPO/RTO 和 revision 连续性 |
| 数据误删或错误迁移 | 审计、Schema/数据校验、业务异常 | 停写、PITR 到指定时间、重建投影和业务对账 | `g14` PITR 收据、WAL/时间点和恢复差异 |
| 消息重复、乱序或积压 | consumer lag、重复 event ID、Outbox 状态 | 幂等消费、按权威 revision 重读、背压和扩容 | LSN/offset、重复拒绝、积压和恢复曲线 |
| Trace/观测后端不可用 | Trace 覆盖率、collector/export error | 本地有界缓冲、告警、恢复补传；AgentTeams 原生执行链与 TestWeaver 质量事实链继续运行 | 丢失范围、补传结果和与原生事件/PostgreSQL 对账 |
| 上下文陈旧、冲突或跨租户串扰 | revision、tenant、permission、provenance 校验 | 阻断下游，刷新/重建 ContextManifest，必要时安全事件升级 | 被拒引用、来源、租户和重建结果 |
| Token/成本异常增长 | 分支预算、单位证据成本、路由账单告警 | 裁剪低价值分支、限流、暂停/HITL，不牺牲高风险覆盖 | 预算变化、裁剪原因、节省和覆盖影响 |
| 磁盘/对象存储接近容量 | 分层阈值、写入失败预测 | 扩容、归档、背压；关键事件优先于大对象和 Trace | 容量曲线、阈值、扩容和降级记录 |
| 权限或密钥异常 | 越权拒绝、Secret 过期/泄漏告警 | 立即阻断、轮换、撤销会话、审计影响范围 | actor、拒绝、轮换、受影响对象和复核 |

任何异常处理都不得只显示“已恢复”。产品必须能展开触发条件、自动/人工决定、实际动作、恢复后的对账结果和仍未消除的风险。

### 11.9 日常运维与版本升级

#### 日常巡检

- AgentTeams Manager/Team/Worker 就绪、心跳、积压、失败和无主任务；
- PostgreSQL 连接、复制延迟、WAL 归档、备份、容量、慢查询和租约；
- Gateway 模型健康、路由变化、限流、熔断、Token 与费用异常；
- MCP/Tool 可用性、Schema 漂移、超时、重试和外部状态未知；
- Skill Active/Canary/Rollback 状态、版本分布和 Golden 指标；
- OTel Collector、LoongSuite/AgentLoop Trace 覆盖率、评测任务和告警；
- Secret 有效期、权限异常、审计缺口和数据保留任务。

#### 版本升级流程

```text
变更登记与影响范围
→ 冻结复合版本矩阵
→ Schema/兼容/安全检查
→ Golden 与故障回放
→ 预生产 Campaign
→ Human 批准
→ Canary/灰度
→ SLO、业务和成本观察
→ 全量或回滚
→ 更新 Runbook、证据和版本清单
```

模型、Prompt、Skill、MCP、Adapter、数据库 Schema、路由和 AgentTeams Runtime 都使用同一升级纪律，但分别记录自己的版本、兼容边界和回滚单位。升级过程中旧 Run 始终引用旧版本元组，不能被新配置追溯覆盖。

---

## 12. 安全、权限与审计

### 12.1 身份与最小权限

- AgentTeams Resource、Runtime Identity、应用身份和数据库 actor 一一映射；
- 每个 Identity 绑定 Team、Role、任务范围、工具、网络、工作区和字段级写权限；
- Agent 不能直接写 `policy_decision`、`oracle_result`、`human_decision` 或正式 Skill 状态；
- Repair 不可访问隐藏 Gold，Verifier 不可修改 Patch；
- Human 授权具有对象、动作、范围、时效和 Policy 版本；
- 管理员、业务负责人、安全审批者和系统运维采用职责分离。

### 12.2 密钥与敏感数据

- 密钥通过独立 Secret 管理和短期注入，不写入源码、Prompt、Trace、截图或验收包；
- 日志和 Trace 默认脱敏，敏感字段按 Policy 记录 hash 或受控 Artifact 引用；
- 每次发布、截图、视频和离线包执行 Secret/PII 扫描；
- 原始模型输出、客户数据和不可公开证据按租户、权限和保留策略隔离；
- 不保存隐藏思维链，只保存可审计的结构化行为和结果。

### 12.3 高风险操作门禁

| 风险动作 | 自动前置检查 | HITL | 回滚/恢复 |
|---|---|---|---|
| 外部业务写入 | 对象、权限、幂等、预算、Boundary | 高风险必需 | 对账、补偿或人工处置 |
| 代码/配置发布 | Patch、双 Oracle、Golden、SBOM | 发布批准 | 版本回滚 |
| Skill 激活 | 关系、兼容、Canary、风险 | Skill Owner 批准 | Bundle 回滚 |
| 权限/密钥变更 | 最小权限、有效期、审计 | 安全审批 | 撤销和轮换 |
| 数据删除 | 租户、范围、保留和备份 | 数据责任人批准 | PITR/备份恢复 |
| Failover/PITR | 演练计划、影响、只读核对 | 运维批准 | 回切或恢复点重选 |

### 12.4 审计链

人工和 Agent 操作统一记录：

```text
who / identity / role / tenant
what / target / action / parameters hash
why / task / claim / evidence refs
when / revision / timestamp
policy / permission / human decision
result / external state / rollback ref
trace_id / content_hash / provenance
```

审计事件 append-only，支持按 Campaign、对象、Agent、Skill、工具、人工操作和外部副作用查询，并进入离线验收包。

### 12.5 主要威胁与控制

- Prompt Injection：工具白名单、结构化输入、权限隔离和证据来源校验；
- 幻觉级联：Claim—Evidence、信任状态和独立验证；
- 重放/重复写：幂等键、generation fencing、对账和审计；
- 越权工具调用：Role/Task/Field/Network 四层权限；
- 跨租户串扰：tenant_id 强制、行级/应用级隔离和 Context 过滤；
- Gold 泄漏：独立 Evaluator 身份、不可检索标签和运行前隔离检查；
- 供应链风险：依赖锁、镜像 digest、SBOM、许可证和签名；
- 恢复风暴：有限重试、失败分类、上游阻断、熔断和人工升级；
- 证据伪造：原生执行事件与质量事件双向关联、content hash、独立 readback、Manifest 和 clean-room replay。

---

## 13. 产品形态与用户体验

### 13.1 设计原则

- 页面围绕用户任务和决策组织，而不是把技术名词做成卡片；
- 一条主线不必对应一个页面，多个能力可以在同一任务上下文中协同呈现；
- 默认先显示“发生了什么、影响什么、下一步需要谁做什么”，再按需展开技术细节；
- 每个数字、状态和主张都能进入证据详情，但主页面不堆放说明性文案；
- 中文产品语言统一，状态、风险和操作词明确；
- 真实数据、缺失数据、回放数据和设计占位在视觉上严格区分。

### 13.2 信息架构

| 产品区域 | 用户要解决的问题 | 核心内容 |
|---|---|---|
| 总控台 | 当前战役是否健康、哪里需要处理 | 核心阶段、风险、预算、阻塞和待办 |
| Campaign 工作台 | 一个真实任务从输入到终态如何推进 | 目标、AgentTeams、Task DAG、时间线、HITL |
| 探索与收敛工作区 | 分支发现了什么、为什么裁剪或回流 | Profile、证据、重复度、假设、区分实验、Patch |
| 失败工作台 | 一个 Failure Capsule 的复现、诊断、修复和验证 | 影响、证据、根因、修复、双 Oracle、恢复 |
| 协作时间线 | 谁在什么时候基于什么证据做了什么 | Task/Handoff/Policy/Human/Skill/Recovery 事件 |
| Skill 中心 | Skill 从哪里来、是否有效、如何发布和回滚 | 版本、评测、关系、Canary、Active/Rollback |
| 可观测与评估 | 哪个 Agent/Skill/Context/Route 需要改进 | OTel Trace、AgentLoop Dataset/Eval、归因和复评 |
| 证据中心 | 如何复核主张并导出验收材料 | Manifest、Receipt、Artifact、查询和离线包 |
| 设置与安全 | 身份、权限、预算、路由、数据和审计如何治理 | Policy、Identity、Secret、Tenant、Retention |

### 13.3 核心交互

用户从 Campaign 工作台发起质量任务，首先冻结 Target、质量契约、预算和风险边界；运行中通过协作时间线看到 AgentTeams 动态任务和关键证据；需要人工时进入证据驱动的审批界面；完成后在失败工作台查看诊断、修复和双 Oracle，在可观测页面查看成本/效果和 AgentLoop 改进闭环，最后从证据中心导出离线验收包。

### 13.4 上手路径与接入成本

产品提供两种接入方式：复赛/试用用户可选择固定案例模板直接运行；企业用户通过向导完成 Target Adapter、Quality Contract、Oracle、工具权限和数据保留配置。

```text
选择场景模板或创建 Target
→ 连接/验证 Target Adapter
→ 填写业务完成条件与风险边界
→ 选择 AgentTeams 组织、Skill、工具和预算
→ Preflight 检查身份、版本、权限、依赖和 Golden
→ 预览将要发生的动作
→ 发起首个 Campaign
```

Preflight 必须给出可操作的缺失项，而不是让用户在日志中自行排查。系统记录首次成功 Campaign 用时、人工配置步骤、失败重试、培训人时和需要编写的适配代码量，用真实数据衡量上手成本。跨场景复用时，产品展示哪些资产可直接复用、哪些必须重新签发，避免用户误用旧 Oracle、旧 Skill 或旧权限。

---

## 14. 可复制性与跨场景迁移

### 14.1 稳定内核

跨场景保持不变：

- AgentTeams Manager/Team/Worker/Human 组织；
- AgentTeams 原生 Project/DAG/Task 执行；TestWeaver Campaign、Claim/Evidence、Policy、业务操作 fencing 与只读 NativeExecutionRef；
- ContextManifest、Handoff 和信任状态；
- HITL、审计、恢复和双 Oracle 协议；
- Skill Package、关系图、Golden、Canary 和回滚；
- OTel/AgentLoop 观测评估；
- 离线验收 Manifest、Schema 和哈希协议。

### 14.2 可替换资产

迁移时替换：

- Target Adapter 和工具实现；
- Quality Contract、业务输入输出和完成条件；
- Test Charter、风险域和故障注入；
- Outcome/Boundary Oracle；
- Golden Dataset 和 Holdout；
- 领域 Skill、审批 Policy 和数据保留策略；
- 模型路由、预算和基础设施配置。

### 14.3 迁移步骤

1. 定义用户、现实流程、失败代价和系统责任；
2. 固化 TargetSnapshot 与输入/输出 Schema；
3. 签发 Quality Contract、双 Oracle 和风险边界；
4. 实现并验证 Target Adapter/TestLab MCP；
5. 选择可复用核心 Skill，补充领域 Skill；
6. 建立 Golden/holdout 和人工基线；
7. 运行最小 Campaign，验证状态、HITL、恢复和审计；
8. 做单 Agent/多 Agent/异质 Team 对照；
9. 完成容量、安全、高可用和灾备验收；
10. 形成版本化迁移包与外部用户验收。

### 14.4 适用范围与限制

TestWeaver 适用于可定义输入、可观察动作、可查询终态并可建立风险边界的 Agent 系统。若目标没有可验证终态、无法隔离副作用、无法取得数据授权或无法建立独立 Oracle，则只能开展有限的辅助评审，不能宣称完成自动质量闭环。

---

## 15. 部署、复现与开源方案

### 15.1 部署形态

- 本地/评审：Docker Compose 一键启动固定 Target、PostgreSQL、API、Agent Runtime 和观测组件；
- 企业试点：复用 AgentTeams Kubernetes/Helm 部署 Controller、Manager、Team/Worker 和网关；TestWeaver 另部署无状态 API、Policy/证据服务、PostgreSQL 与 OTel，不部署第二 Scheduler；
- 生产：PostgreSQL Primary/Replica 高可用集群、对象存储、Higress、Nacos、RocketMQ、AgentLoop/LoongSuite 和集中 Secret；
- 离线验收：不调用模型、不写数据库、不访问网络的证据重放与哈希验证。

### 15.2 干净环境复现

提供：

- 依赖锁、镜像 digest 和版本矩阵；
- 环境预检和 fail-closed 错误说明；
- 数据库迁移、初始化和最小权限账户；
- 一键启动、健康检查、Hero 启动和验收命令；
- 公开 Fixture、Golden manifest 和权限隔离说明；
- Offline Replay、Manifest 和 checksum；
- 故障排查、恢复和卸载 Runbook。

### 15.3 开源范围

计划开放：

- AgentTeams 协作模板和 Adapter 示例；
- 公共 JSON Schema、MCP 契约和 Target Adapter SDK；
- 核心 Skill 包及评测样例；
- OpenWorker 固定案例、回放和脱敏 Trace 示例；
- Compose/Helm、部署文档和离线验收工具；
- Golden Dataset 格式、Evaluator 接口和对照实验协议；
- SBOM、许可证、贡献指南、安全响应和版本策略。

同时至少形成一项对上游 AgentTeams 可独立使用的贡献，例如原生链路缺陷修复、Runtime/Skill 兼容增强、测试或文档改进，并以公开 Issue/PR/commit 或维护者反馈证明；TestWeaver 私有业务逻辑本身不能冒充上游贡献。

真实密钥、客户数据、隐藏 Gold、未授权模型输出和内部生产配置不进入开放资产。闭源依赖需标注替代接口和迁移成本。

---

## 16. 复赛验收与证据设计

### 16.1 最低必须跑通的复赛闭环

最低验收不是“页面能打开”或“AgentTeams 资源已创建”，而是在一个固定镜像、真实 Target 和同一逻辑 Campaign 中，让 AgentTeams 原生执行链与 TestWeaver PostgreSQL 质量证据链完成可核验关联：

1. 原生 AgentTeams Manager、Exploration Team、Convergence Team、DSH/Codex Worker 和不少于三个不同职能 Agent 实际承担业务任务；
2. 从真实输入生成 Task、Handoff、Artifact、Claim、Evidence 和可查询终态；
3. 至少一次由中间证据触发的动态动作，例如新增分支、裁剪、局部回流、重派或重新规划；
4. 至少三个与案例直接相关的核心 Skill 完成真实 `discover/load/invoke`，不为凑数量插入无关调用；
5. 一次真实 Human Gate 暂停，用户查看证据后执行批准、拒绝、修改或请求补证，随后正确恢复；
6. 一次自然或明确标记的受控异常演练，分别展示原生 Worker 失败/重派，以及一个外部业务操作的有限重试或 operation generation 接管、迟到结果拒绝和恢复对账；
7. 至少一次可验证回滚/补偿边界，例如 Patch 回滚、Skill Canary 回滚或外部副作用补偿；若没有触发回滚，必须展示经过验证的回滚计划和独立演练，不能伪造业务失败；
8. Independent Verifier 使用分离证据执行 Outcome Oracle 与 Boundary Oracle；
9. OTel/LoongSuite/AgentLoop 能从 Campaign 下钻到 Agent、模型、上下文、Skill、MCP、工具、Policy、Human 和 Oracle 的输入输出、版本、成本与异常；
10. 输出原始事件、即时 PostgreSQL 对账、失败恢复时间线、独立复跑命令和带 SHA256 Manifest 的离线验收包；
11. 运行结果和预期完成条件逐项对照，缺失项标为 `PARTIAL/NOT_OBSERVED`，不能用页面文案或静态收据补齐；
12. 在此基础上完成第二案例，可作为通用性、跨场景复制和工程化能力的加分证据。

原生边界同时是一票否决项：

- Manager 的 Team/Leader 选择必须来自真实 provider 调用；Leader 必须通过 AgentTeams/TeamHarness 原生工具创建、分派、接收和验收任务，脚本只允许配置、启动、观测和收据化；
- TestWeaver 不得向 PostgreSQL 复制一套可独立驱动 Project/Task 的调度状态，也不得由 Runner 解析模型文本后代替 Manager/Leader 完成原生动作；
- AgentTeams 原生 Task 状态变化必须能从原生事件回读；PostgreSQL 只能记录 NativeExecutionRef、质量证据、业务 Policy/HumanDecision、Oracle 和外部副作用状态；
- 领域 Skill 必须由 AgentTeams/具体 Worker Runtime 真实发现、加载和调用，TestWeaver 只提供 Skill 内容、版本、评测与发布治理；
- 至少做一次“仅改变一条真实证据”的受控复跑，证明 Manager/Leader 选择或后续原生事件链发生可解释变化，而不是固定脚本。

运行分类必须诚实使用以下标签：

| 分类 | 判定标准 |
|---|---|
| `STRUCTURAL_LIVE_SMOKE` | 使用真实 AgentTeams 资源和 provider，至少跑通 Manager → Team/Leader → Worker → Leader，但 Manager 只有预定选择、未发生证据驱动路径变化，或缺少 HITL/恢复/双 Oracle 等 Hero 关键证据 |
| `LIVE_AGENTTEAMS_HERO` | 同一 Run 同时具备真实 Manager provider 调用与模型/延迟/usage/请求响应 hash、真实结构化选择及路径变化、至少三个不同职能且可回读的独立 Agent 身份、Leader 原生委派、Worker 真实模型/工具/Skill、Handoff、失败恢复与迟到拒绝、真实 Human pause/decision/resume、独立双 Oracle，以及同一逻辑 Campaign 的原生执行链和 PostgreSQL 质量证据链回读 |
| `PARTIAL` | 已产生部分真实证据，但任一必需环节失败、缺失或无法回读；必须列出 `missing_observations`，不得借用旧 Run 补齐 |

固定 Target、案例输入、角色、Team、DAG 上限、任务 Profile、工具/Skill 白名单、预算和安全规则属于合法实验控制；Manager choice、Agent 输出、分支结果、HITL 决定和 Oracle 结论不得硬编码。脚本只能配置、启动、观测和收据化，不能直接注入模拟事件或代替 Leader 创建任务。

每次运行必须生成机器可读的期望—实际对账：

```json
{
  "campaign_id": "...",
  "run_id": "...",
  "expected_output_ref": "quality-contract:...",
  "actual_output_refs": ["artifact:...", "oracle:..."],
  "required_observations": ["agentteams", "hitl", "skill", "recovery"],
  "observed": {},
  "missing": [],
  "outcome_oracle": "PASS|FAIL|UNCERTAIN",
  "boundary_oracle": "PASS|FAIL|UNCERTAIN",
  "classification": "STRUCTURAL_LIVE_SMOKE|LIVE_AGENTTEAMS_HERO|PARTIAL",
  "verdict": "PASS|PARTIAL|FAIL",
  "evidence_bundle_hash": "sha256:..."
}
```

### 16.2 完整场景链路材料

每个 Hero Case 生成：

```text
hero-case/
├── 00-manifest/
├── 01-target-and-input-freeze/
├── 02-agentteams-identities-and-tasks/
├── 03-authoritative-events/
├── 04-handoffs-and-artifacts/
├── 05-branch-loop-prune-dedup/
├── 06-hitl-decisions/
├── 07-failure-and-recovery/
├── 08-skill-invocations/
├── 09-dual-oracle/
├── 10-otel-agentloop-evaluation/
├── 11-baseline-and-metrics/
├── 12-security-audit/
└── 13-offline-replay/
```

所有证据绑定 `campaign_id / quality_run_id / native_project_id / native_task_id / commit / target_snapshot / dataset_version / skill_bundle / policy_version / trace_id / content_hash`。

### 16.3 PostgreSQL 与可观测闭环的独立验收收据

| 收据 | 独立证明的能力 | 最低验收内容 |
|---|---|---|
| `g14-postgresql-pitr` | 指定时间点历史恢复 | base backup/WAL/目标时间、带时间戳操作记录、事件重放、projection 重建、业务对账、RPO/RTO |
| `g15-postgresql-failover` | 主库故障后的高可用切换 | 故障注入、选主、防脑裂、连接恢复、事件连续性、失败请求、真实 RPO/RTO |
| `g16-postgresql-logical-replication` | TestWeaver 质量事件向回放/分析副本分发 | publication/subscription、LSN、revision、`bundle_hash`、`provenance`、只读边界和复制延迟 |
| `g17-postgresql-pgvector-rag` | 带版本与证据引用的知识检索 | `version + evidence_ref + content_hash + permission_scope`、陈旧/越权拒绝、检索 Trace |
| `g18-postgresql-capacity` | 容量、扩容和降级策略 | 压测模型、连接/存储/事件/Trace 阈值、扩容过程、背压、告警和恢复 |
| `o01-otel-agentloop-trace` | 标准 GenAI Trace 与分域权威状态关联 | 同一 Campaign 的 Agent/Skill/MCP/Model/Human/Oracle、native execution ref 与 DB quality revision 查询结果 |
| `o02-golden-evaluation` | 冻结离线评估可复现 | Dataset/Evaluator/holdout 版本、独立身份、重复运行和结果哈希 |
| `o03-improvement-reevaluation` | 观测驱动的自我改进闭环 | 归因、改进 Proposal、人工审批、Canary/rollback 边界和同集复评比较收据 |

这些收据相互引用但不相互替代：PITR 不能证明 Failover，Trace 不能证明业务终态，逻辑复制不能成为第二事实源，Golden 回放不能冒充 LIVE Campaign。

### 16.4 证据等级

| 等级 | 证明范围 |
|---|---|
| DESIGN | 目标架构、Schema、Policy 和验收设计 |
| SOURCE | 代码、配置、迁移和测试存在 |
| REPLAY | 冻结输入可确定性回放，但不证明本次外部运行 |
| LIVE | 当前真实运行产生的直接观察 |
| INDEPENDENTLY_VERIFIED | 独立身份/环境复核 LIVE 结果 |
| PRODUCTION_ACCEPTED | 生产环境容量、恢复、安全和业务验收 |

公开材料中的每项“已实现、已运行、有效、节省、生产可用”必须绑定对应等级和 Evidence Ref。静态截图、配置、测试、回放和跨 Run 拼接不能替代 LIVE。

### 16.5 不超过 8 分钟的 Demo

| 时间 | 内容 |
|---|---|
| 0:00–0:40 | 用户、现实流程、失败代价和基线 |
| 0:40–1:20 | 冻结 Target、质量契约、预算和风险边界 |
| 1:20–3:10 | AgentTeams Manager、双 Team、异质 Worker 的真实动态协作 |
| 3:10–4:00 | 重复路径裁剪、证据冲突或局部回流 |
| 4:00–4:50 | 原生 Worker 失败/重派，以及一个可能产生外部副作用的业务操作 generation 接管和迟到结果拒绝 |
| 4:50–5:35 | HITL 的证据、批准/拒绝/修改和恢复 |
| 5:35–6:20 | 核心 Skill 发现、加载、调用和版本证据 |
| 6:20–7:05 | 候选修复、回滚/恢复边界、双 Oracle 和业务终态 |
| 7:05–7:40 | OTel/LoongSuite/AgentLoop、Golden 评估和量化对照 |
| 7:40–8:00 | 离线验收包、跨场景复制和开源入口 |

Demo 优先采用一次连续的真实 Campaign。若为展示需要切换页面，所有页面必须使用同一 Campaign/Run 或明确标注不同 Run 的比较关系。

### 16.6 测试、评测与回归层级

```text
Schema/Policy/证据纯逻辑单测
  → AgentTeams 原生边界契约测试
    → Manager→Leader→Worker 原生集成 smoke
      → HITL/恢复/双 Oracle 真实 Hero E2E
        → 同输入 E0–E3 配对评测
          → clean-room 安装、复跑与离线包校验
```

| 层级 | 必须覆盖的成功与失败路径 | 主要断言 |
|---|---|---|
| 单元/Schema | Quality Contract、Context/Handoff、Claim/Evidence、Policy、HumanDecision、Oracle、业务操作 fencing 的合法/非法输入、空值、陈旧 revision、权限拒绝 | fail-closed、无越权写入、hash/revision 稳定、错误可解释 |
| 原生边界契约 | Manager/Leader/Worker 角色权限；原生 Project/Task 状态只由 TeamHarness 改变；TestWeaver PG 不具备原生调度写权；领域 Skill 由 Runtime 发现/加载/调用 | Runner 不能代建任务，Observer/AgentLoop 不能否决或推进运行，NativeExecutionRef 只读 |
| 集成 smoke | 真实 Manager 选 Team/Leader，Leader 原生创建/委派，Worker ack/execute/submit，Leader accept，Manager 读取结果二次决策 | 原生事件、身份、provider、usage、Artifact 和终态可回读；失败诚实分类 |
| Hero E2E | 双 Team、至少三个职能 Agent、证据驱动改路、真实 HITL、Worker 故障/重派、外部操作对账/迟到拒绝、双 Oracle | 同一 Run 完整链路，无 fixture、静态事件、自动代签或跨 Run 拼接 |
| LLM/Skill Eval | Manager 选择、Leader 裁剪、竞争假设、核心 Skill、证据扰动复跑 | 冻结 Dataset/预算/Oracle；一条证据变化产生可解释行为差异；隐藏 Gold 隔离 |
| 效果/性能 | E0 单 Agent、E1 同质多 Agent、E2 动态多 Agent、E3 异质多 Agent至少三次配对；并发、Token、工具和上下文边界 | Safe Success、质量、重复率、幻觉阻断、协调开销、Token/成本/时延及置信区间 |
| 发布/复现 | 干净环境安装、Secret 缺失、provider 不可用、数据库/Trace 不可用、版本升级/回滚、离线验收 | 核心链可复跑；非关键观测降级不冒充 LIVE；敏感信息不进入包 |

计划中的每个新领域模块必须同时给出单元或契约测试；跨 Agent、模型、Matrix、数据库或外部工具的关键路径必须使用真实集成/E2E；Prompt、Manager/Leader 决策规则和 Skill 变化必须进入固定 Dataset 的 Eval。只有成功路径的 smoke 不得替代失败路径和用户可恢复性验证。

---

## 17. 复赛提交物

### 17.1 正式提交

1. 更新版项目方案 PPT/PDF；
2. 完整场景链路验证材料；
3. 可执行代码仓库或压缩包；
4. 在线体验环境，或不超过 8 分钟的 Demo 视频。选择在线体验时提供专用评审账号与密码，采用最小权限、限额、有效期和可重置策略，不连接生产数据或不可逆外部系统；选择视频时仍附离线验收包和复跑命令。

### 17.2 支撑附件

- 复赛规则符合性矩阵；
- Agent Identity 清单；
- 核心 Skill 清单；
- 企业级架构与容量/高可用/灾备设计；
- Golden Dataset 与评测报告；
- 安全、权限、HITL 和威胁模型；
- 部署、复现、回滚和运维 Runbook；
- SBOM、许可证、Secret Scan 和开源说明；
- 离线验收 Manifest、Receipt 和 SHA256 清单。

---

## 18. 分阶段落地顺序

完整企业方案一次设计，但实施和验收按风险与价值排序：

### 18.1 实施底座与资产继承

- 以当前官方 AgentTeams 基线作为唯一开发底座，直接复用其 Controller、Manager、Team/Leader/Worker/Human、Project/Task/Room、TeamHarness 和原生 Skill 调用能力；
- 初赛代码、旧仓库和历史运行只作资产供体，优先继承领域 Skill、Context/Claim/Evidence/Handoff、Policy/HITL、双 Oracle、Golden/AgentLoop 合同及 DSH/Codex 薄适配；
- 每项旧资产必须先证明 AgentTeams 原生缺口，再做“直接复用、薄化迁入、仅作参考或拒绝”分类，禁止整提交回灌和恢复第二编排器；
- 历史 receipt 只能证明历史事实，不能替代新基线上的测试和 LIVE Run；密钥与 AgentLoop/LoongSuite/OTel/Nacos 配置仅通过现有受保护外部引用复用，不复制进仓库；
- 第一条真实纵向闭环只让真实性、身份、来源、越权和高风险审批硬阻断；HA、PITR、RAG、高并发、容量与灾备保留为完整目标态，闭环后再实施。

### 18.2 阶段 A：安全边界与真实产品通路

- 冻结一个真实 Hero Case、Target、质量契约、双 Oracle 和 Golden；
- 打通 AgentTeams Manager、双 Team、DSH/Codex Worker 原生执行链，并关联 TestWeaver PostgreSQL 质量证据链；
- 运行真实分支、动态决策、HITL、失败恢复和核心 Skill；
- 输出同一 Campaign 的原始事件、对账和离线包。

### 18.3 阶段 B：效果证明与自我改进

- 完成单 Agent/同构/动态/异质对照；
- 接入 LoongSuite/OTel → AgentLoop；
- 完成 Golden 评估、归因、改进 Proposal、Canary 和同集复评；
- 冻结可解释的价值、成本和边界结果。

### 18.4 阶段 C：产品化与跨场景复用

- 以任务为中心完成产品控制台和证据导航；
- 跑通第二类长任务恢复场景；
- 完成 Target Adapter/Skill/Oracle 迁移包和外部复现。

### 18.5 阶段 D：企业级工程验收

- 高并发压测、容量与成本基线；
- PostgreSQL Failover、PITR、逻辑复制、pgvector RAG；
- 多可用区、备份、灾备、SLO、告警和值班；
- 供应链、RC 发布、干净环境和开源验收。

高可用、并发、灾备等内容虽然在实施顺序上位于真实 Hero 之后，但已经属于本完整方案的正式架构，不是临时补充项。

### 18.6 首次真实 Hero 明确不在范围内

- 不新建第二 Manager/Scheduler、通用 TaskRun/DAG/Lease、Room/Session 管理器或 Skill Runtime；
- 不一次迁回旧仓库全部代码、测试、脚本、收据和历史状态，只迁真实缺口对应的薄资产；
- 不要求八个目标 Skill 全部进入首跑，首个 Hero 只调用与案例直接相关且能真实验证的至少三个核心 Skill；
- 不在闭环前完成全套产品页面、第二场景、E0–E3 因果结论、生产 HA/PITR/RAG、高并发、容量、灾备和值班体系；
- 不为演示强行制造分支、冲突、HITL、异常、恢复或 PASS；自然未发生项如实标为 `NOT_OBSERVED`，再通过独立受控演练补证。

---

## 19. 复赛规则符合性矩阵

| 规则维度 | 方案响应 | 计划验收材料 |
|---|---|---|
| AgentTeams 基座 | 原生 Manager、双 Team、Worker、Human，承担任务、上下文、状态和生命周期 | 同一 Campaign 的 AgentTeams 资源、Task、Handoff 和终态 |
| ≥3 个不同职能 Agent | Manager、Explorer、Diagnoser、Repair、Verifier 等具有不同输入输出和权限 | Identity Manifest、权限矩阵、运行事件 |
| Skill 强制覆盖 | 八个 Skill 构成完整目标清单；首个 Hero 只选择至少三个与案例直接相关的核心 Skill 进入真实运行/评测，避免为数量插入无关调用 | discover/load/invoke Trace、版本、Golden、Canary/rollback |
| 可运行验证 | Compose/Kubernetes、Hero 命令、健康检查、离线 replay | 代码包、在线环境/视频、clean-room receipt |
| 场景价值 20% | 使用真实历史问题定义失败代价、输入输出和完成条件，再在复赛新基线上生成新的真实 Hero 与对照，历史收据不替代本次运行 | Baseline、新基线真实 Run、量化报告、第二场景迁移 |
| 定量价值 | 上手、工程人时、沟通等待、重复调用、单位证据成本和 Safe Success 使用真实基线 | 时间戳、工时、Context/Tool/Token Ledger、样本数和计算公式 |
| 多 Agent 25% | Manager/Leader 通过 AgentTeams 原生 Project/DAG/Task 完成动态分支、裁剪、回流、冲突、重派、恢复和 HITL；TestWeaver 只加证据与业务安全约束 | 原生 Project/Task/Room/消息事件 + Policy/Human/业务操作恢复关联 |
| Skill 20% | 核心 Skill、生命周期、AgentTeams 关系和跨场景复用 | Skill Manifest、调用、评测、关系和发布记录 |
| 工程 1：完整架构 | AgentTeams 原生控制面 + TestWeaver 质量证据扩展，明确控制流、数据流、状态流、异常流及代码边界 | 架构图、代码路径、配置、clean-room 启动与真实 Hero |
| 工程 2：核心数据与状态 | 原生 Project/Task 与 PostgreSQL 质量账本分域权威，通过 NativeExecutionRef/revision/hash 关联、查询、恢复和审计 | 原生事件、质量事件、即时 readback、重启恢复和对账收据 |
| 工程 3：记忆与上下文 | Task Context、Shared State、Long-term Memory、RAG 分层；ContextManifest 管版本、权限、压缩、过期和来源 | 陈旧/冲突/越权/截断测试、检索 Trace、上下文重建与清理证据 |
| 工程 4：观测与评测 | Agent/模型/路由/Context/Skill/MCP/Tool/Policy/Human/Oracle 绑定同一 Run；LoongSuite/OTel → AgentLoop → Golden → 归因 → 复评 | AgentLoop 查询回读、原始 Trace/Log/Metrics、Dataset/Evaluator 版本和改进对照 |
| 工程 5：工具与外部系统 | TestLab MCP、Target Adapter、PostgreSQL/RAG、Higress/Nacos/RocketMQ 逐项说明调用阶段、必要性、替代方式与失败语义 | Tool Trace、权限/超时/限流/幂等测试、组件降级和迁移说明 |
| 工程 6：安全权限审计 | 身份映射、最小权限、Gold/租户/Secret 隔离、真实 HITL、外部副作用 fencing、统一审计 | 拒绝路径、安全扫描、HumanDecision、迟到拒绝、Boundary Oracle 和审计查询 |
| 工程 7：部署可靠运维 | 依赖锁、一键启动、健康检查、版本/灰度/回滚；闭环后实施并发、HA、PITR、容量、灾备、SLO和值班 | clean-room receipt、异常演练、升级/回滚、压测、PITR/failover 和 Runbook |
| 开源 5% | 仓库、许可证、SBOM、Schema、Skill、SDK、部署与复现 | 正式 Release、公开文档、第三方复现 |
| 高风险人工确认 | 风险分级、真实 HITL、授权范围、审计和恢复 | HumanDecision、PolicyDecision、rollback receipt |
| 可复制性 | 稳定内核 + 可替换 Adapter/Contract/Oracle/Golden/Skill | 第二场景迁移包和对照报告 |
| 异常处理 Demo | 原生 Worker 超时/失败后由 Leader 重派；外部业务操作另行演示对账、generation 接管、迟到拒绝和有限重试 | 原生任务恢复事件 + 业务操作恢复时间线和可回放证据 |

### 红线规避

- 不用单 Agent、固定脚本、预置事件或 UI 动画冒充 AgentTeams；
- 不允许少于三个不同职能 Agent，也不允许核心业务链绕过 AgentTeams；
- 不用硬编码、Mock 返回或回放冒充真实 Skill 和真实运行；
- 不拼接不同 Run 的事实形成一条虚假链；
- 不伪造用户、数据、效果、Trace、人工决策或生产能力；
- 不泄露密钥、隐私、隐藏 Gold 和未授权数据；
- 不让高风险不可逆动作绕过授权、审计和恢复；
- 核心链无法复现时不提交“已通过”结论。

---

## 20. 项目成功标准

复赛版本的成功不是“页面齐全”或“Agent 数量足够”，而是评委能够在一个真实、可复现的场景中确认：

1. 用户、现实流程、失败代价和产品责任清楚；
2. AgentTeams 原生组织实际承担不少于三个不同职能 Agent 的业务协作；
3. 中间证据真实改变了任务路由、分支、裁剪、恢复或人工决策；
4. 信息共享可追溯，重复劳动、幻觉级联和 DAG 依赖得到工程控制；
5. Worker 超时、冲突、未知外部状态和迟到结果能够安全恢复；
6. 核心 Skill 被真实发现、加载、调用、评测并具备版本/回滚；
7. HITL 是 AgentTeams 原生暂停/恢复与 PostgreSQL HumanDecision 关联形成的真实事件，而不是装饰按钮或 Agent 自动代签；
8. Outcome 与 Boundary 同时通过，修复者不能自我证明；
9. OTel/LoongSuite/AgentLoop 与 Golden Dataset 形成可重复的改进闭环；
10. 代码、数据、Trace、审计和离线包能够独立复核；
11. 完整架构能够解释高并发、高可用、灾备、安全和长期运维；
12. 第二场景能够通过替换 Adapter、契约、Oracle、Golden 和领域 Skill 复用同一内核；
13. 使用真实基线说明用户上手成本、工程人时、沟通等待、重复调用和单位有效证据成本，而不是给出无口径百分比；
14. 当前 Run 的预期输出、实际输出、缺失观察和 Verdict 能够机器对账，版本升级、日常运维和异常恢复均有明确路径。

这套标准共同证明 TestWeaver 不是一次性的比赛脚本，而是一套可以迁移到企业 Agent 应用研发和质量治理流程中的 Agent Infra 产品。
