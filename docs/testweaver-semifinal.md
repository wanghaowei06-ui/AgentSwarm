# TestWeaver 复赛唯一总控

更新时间：2026-09-01（Asia/Shanghai）

状态：`M0_IN_PROGRESS`

唯一当前里程碑：跑通官方 AgentTeams 原生 M0；配置复用是其并行前置，不扩展产品范围。

## 1. 已冻结决策

- 产品仓库：`/root/projects/agentteams`；分支：`testweaver-semifinal`。
- 底座：官方 AgentTeams `2ea027403398dfa06f3fc86445042d59f4684d71`。
- 初赛公开提交 `45070b6`、GitHub `main` `2901065` 和旧仓库 `/root/projects/muti-agent` 只作资产供体与历史证据，不再作为开发主线。
- 选择原因：初赛代码包含可复用领域资产，但也包含自定义 Scheduler、固定 G3 资源、Hermes Leader 和 Python Runner 调度；直接延续会重新形成第二编排器。
- 现有 API Key、AgentLoop、LoongSuite、OTel 和 Nacos 配置必须复用，不要求用户重新填写。只引用 `/etc` 下受保护文件或受控挂载，不读取到输出、不复制或提交密钥值。
- 当前协作在同一工作区完成；按文件范围并行，不再为小任务创建大量 worktree。

## 2. 目标、评分与最低交付

复赛权重：场景价值与复制性 20%、多 Agent 协同 25%、Skill 工程 20%、工程落地与安全审计 30%、开源贡献 5%。

最低交付不是流程图，而是一个真实、可复现、有效果的纵向闭环：

`Human → Manager 动态选 Team/Leader → Leader 原生分解/委派 → Worker 真实模型/工具/Skill → Leader 验收 → Manager 二次决策 → HITL/恢复 → 双 Oracle → 同 Run 证据与评估`

## 3. AgentTeams 与 TestWeaver 的边界

AgentTeams 原生负责最复杂的通用协议：Manager、Team、Leader、Worker、Human、Matrix、身份与房间、Project/Task 生命周期、`roomflow/projectflow/taskflow`、委派/提交/验收、运行时与 MCP/Skill 装配。

TestWeaver 只做产品差异：

- 3–5 个领域 Skill 及 Nacos/SkillOps 治理；
- 最薄的跨 Team Context/Claim/Evidence/Provenance/Handoff；
- 业务 Policy 与真实 HITL 审批事实；
- Outcome/Boundary 双 Oracle；
- DSH、Codex CLI 等异构 Worker 薄适配；
- PostgreSQL 审计关联、AgentLoop 评估、Golden Dataset 与 E0–E3 效果实验；
- 安全边界、离线复跑与开源交付。

禁止恢复第二 Manager/Scheduler、Runner 代替 Leader 创建任务、Observer 控制运行、Project/Session/Room 重建、Hermes 专用桥和巨型前置 Gate。

## 4. 旧资产继承规则

资产审计已完成：commit `27157efd241ed1028f20074530315b88c6f5491a`，共 24 项：9 项直接复用、2 项已迁入验证、8 项仅作参考、5 项拒绝重复。清单位于旧仓库隔离审计分支的 `docs/business/native-asset-inheritance-register.md` 与同名 JSON。

迁移顺序固定为：

1. M0 后立即接真实 LoongSuite/OTel→AgentLoop Trace query 和真实 Skill 调用；
2. 接最薄 Context/Evidence/Handoff；
3. 接 Policy/HITL、恢复和双 Oracle；
4. 接 DSH/PR1139 Codex Worker 异构路径；
5. 做 E0–E3 配对评估、发布与材料。

每项必须先证明原生缺口，再选择直接复用、薄化迁入、仅作参考或拒绝；禁止整提交回灌。

## 5. 当前事实

- 新仓库基线提交：`f2b57d4`，此前工作树干净。
- 原生 M0 线正在核验并复用隔离运行栈 `agentteams-native-m0-20260901-*`：官方 Manager、QwenPaw Leader/Worker 已 Ready；尚未标记 M0 PASS。
- 历史 M0 已真实出现 Manager 首次 provider choice、原生 TeamHarness 委派、Worker submit 与 Leader accept；缺口是 accepted report 曾落入 Leader personal room，Manager admin room 未获得第二次 provider decision。
- 配置线已确认 `/etc/agentteams/agentteams.env`、`providers.env` 和 Worker env 为外部受保护入口；正在建立 names-only preflight 与 AgentLoop 配置引用。
- AgentLoop 旧资产目前只可称合同/replay/历史受限证据；必须等待同一真实 M0/Hero 后完成真实查询回读。

## 6. 实施顺序与完成条件

1. `M0 原生闭环`：同一真实请求完成 Manager→Leader→Worker→Leader→Manager 二次决策；无旧 Runner 参与。
2. `M1 协作与 Skill`：双 Team、至少三个不同职能 Agent、真实 Skill discovery/load/invoke、结构化 Handoff；证据改变至少一次后续路径。
3. `M2 工程与安全`：真实 HITL、一次可恢复异常、迟到结果拒绝、双 Oracle、PG/事件/Trace/AgentLoop 同 Run 关联、密钥和 Gold 隔离。
4. `M3 效果`：冻结同输入、预算和 Oracle，单 Agent、同质多 Agent、异质多 Agent至少三次配对复跑；报告质量、重复率、幻觉阻断、协调开销、Token/成本和净价值。
5. `M4 交付`：clean-room 一键运行/复跑、离线包、产品接入、PPT/PDF、8 分钟内视频、许可证/SBOM/贡献指南。第二场景随后用于证明复制性。

HA、PITR、RAG、高并发、容量和灾备在核心闭环前只保留设计，不阻塞 M0–M3。

## 7. 一票否决

- 不得硬编码 Manager choice、Agent 输出、分支结果、HITL 决定或 Oracle 结论。
- 不得用 fixture、静态事件、旧收据、synthetic Trace 或 UI 文案冒充 LIVE。
- Prompt 不能替代身份、来源、权限、状态、恢复、usage 和审计证据。
- 未观察、未查询或未复跑的能力必须标记 `PARTIAL/NOT_OBSERVED/NOT_AVAILABLE`。

## 8. 维护纪律

本文件是当前方向、状态和后续计划的唯一持久化总纲。只在基线、决策、里程碑状态、真实 Gate 或唯一下一步变化时更新；详细命令、日志、Trace、测试和复核进入机器收据，不再建立逐命令长台账。
