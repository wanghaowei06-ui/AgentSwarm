# TestWeaver 复赛总控

更新时间：2026-09-01（Asia/Shanghai）

## 当前基线

- 产品仓库：`/root/projects/agentteams`
- 开发分支：`testweaver-semifinal`
- 官方 AgentTeams 基线：`2ea027403398dfa06f3fc86445042d59f4684d71`
- 旧仓库 `/root/projects/muti-agent` 自此只作只读资产与历史证据库，不再作为开发主线。

## 目标与评分

在官方 AgentTeams 原生控制面上完成可复现的真实多 Agent 工程闭环，并按复赛权重收口：

- 场景价值与复制性：20%
- 多 Agent 协同：25%
- Skill 工程：20%
- 工程落地与安全审计：30%
- 开源贡献：5%

## 责任边界

- AgentTeams 原生负责 Manager、Team、Leader、Worker、Human、Task、Room、委派与运行时 Skill 调用。
- TestWeaver 只扩展领域 Skill、结构化跨 Team Handoff、Evidence/Claim、HITL 业务审批、双 Oracle、异构 Worker、评估与审计。
- 禁止恢复第二编排器、Runner 代替 Manager/Leader 调度、Observer 控制运行、Hermes 专用桥和巨型前置 Gate。

## 资产继承

旧资产必须逐项验证后迁入，禁止整提交回灌。优先候选：

1. 3–5 个核心领域 Skill 与 SkillOps/Nacos 版本治理；
2. Evidence/Claim/Provenance 与最薄结构化 Handoff；
3. HITL Policy、Outcome/Boundary 双 Oracle；
4. DSH 与 Codex CLI 异构 Worker 薄适配；
5. OTel/LoongSuite→AgentLoop、Golden Dataset 与 E0–E3 评估；
6. 安全审计、SBOM、离线复跑与发布资产。

每项只允许标记为：直接复用、薄化迁入、仅作参考或拒绝重复。

## 实施顺序

1. `M0`：用官方 AgentTeams 跑通 Manager→Team/Leader→Worker→Leader→Manager 二次决策。
2. `M1`：扩展到双 Team、至少三个不同职能 Agent，并产生真实 Skill 调用和结构化 Handoff。
3. `M2`：加入真实 HITL、可恢复故障、双 Oracle、同 Run PostgreSQL/事件/Trace 证据和 AgentLoop 回读。
4. `M3`：冻结同输入、预算和 Oracle，完成单 Agent、同质多 Agent、异质多 Agent至少三次配对复跑。
5. `M4`：完成 clean-room 一键复跑、离线包、材料、视频、开源发布；再考虑第二场景与后置工程。

## 一票否决

- 不得硬编码 Manager choice、Agent 输出、HITL 决定或 Oracle 结论。
- 不得用 fixture、静态事件、旧收据或 UI 文案冒充真实运行。
- Prompt 不能替代身份、来源、权限、状态、恢复和审计证据。
- HA、PITR、RAG、高并发和灾备不阻塞首个真实闭环；未实现时如实标记。

## 维护纪律

本文件是当前方向和里程碑的唯一持久化总纲，只在目标、Gate、事实状态或唯一下一步变化时更新。详细命令、日志、Trace 和复核结果进入机器收据，不再维护逐命令长台账。

当前唯一下一步：先验证官方 quickstart 和原生 TeamHarness M0，不迁入任何旧业务代码。
