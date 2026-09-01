# TestWeaver 复赛唯一总控

更新时间：2026-09-02（Asia/Shanghai）

状态：`M2-C_PARTIAL / M2-D_HITL_ROUTING_BLOCKED`

唯一当前里程碑：跨房间 assignment 通知修复镜像 `be10aaf` 已部署并由 M2-D 的真实 Worker assignment/submit 验证；M2-D 已到真实 `PAUSE`，当前只解决 Human 决定必须经 Manager 认证并转交 Leader 的原生路由，不扩 Gate、不绕过权限。

## 1. 已冻结决策

- 产品仓库：`/root/projects/agentteams`；分支：`testweaver-semifinal`。
- 底座：官方 AgentTeams `2ea027403398dfa06f3fc86445042d59f4684d71`。
- 初赛公开提交 `45070b6`、GitHub `main` `2901065` 和旧仓库 `/root/projects/muti-agent` 只作资产供体与历史证据，不再作为开发主线。
- 选择原因：初赛代码包含可复用领域资产，但也包含自定义 Scheduler、固定 G3 资源、Hermes Leader 和 Python Runner 调度；直接延续会重新形成第二编排器。
- 现有 API Key、AgentLoop、LoongSuite、OTel 和 Nacos 配置必须复用，不要求用户重新填写。只引用 `/etc` 下受保护文件或受控挂载，不读取到输出、不复制或提交密钥值。
- 当前原生基线继续使用已验证的 `agentteams-gateway/deepseek-v4-flash`，直到 M1 原生稳定性收口；异构资产接入前不得为了提前展示而修改在途 Run 的模型、账号、推理强度或 service tier。
- 异构阶段的 DSH 是 provider-agnostic Harness，不得只用 DeepSeek 形成“异构”结论；必须复用现有受保护配置，让至少一个真实 DSH Worker 调用阿里云百炼模型，并把 provider/model/usage/延迟和结果证据与 DeepSeek 路径分开记录。
- Codex CLI 外部 Worker 必须由 `codex-cc` 启动，不使用裸 `codex`；计划模型固定为 `gpt-5.6-luna`、推理强度 `max`。该配置只在 M1 异构 Worker 薄适配步骤落地，当前不得提前改动运行环境。
- 当前协作在同一工作区完成；按文件范围并行，不再为小任务创建大量 worktree。
- 完整目标态以 [`semifinal-complete-project-proposal.md`](semifinal-complete-project-proposal.md) 为准；该方案已按最新复赛五项评分维度、工程安全七个子项和 AgentTeams 原生边界修订。它不承载实时进度，本文件仍是唯一实施总控。

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

资产按里程碑分步继承，不做一次性回灌：

1. `M0 原生基线`：只复用现有 API Key、provider、AgentLoop/LoongSuite/OTel/Nacos 的受保护配置引用；不迁入旧调度代码，先证明官方 Manager→Leader→Worker 闭环。
2. `M1 协作与 Skill`：在冻结的原生双 Team 基线上，继承领域 Skill、最薄 Context/Claim/Evidence/Provenance/Handoff，以及 DSH/PR1139 Codex Worker 薄适配。DSH 至少覆盖 DeepSeek 与阿里云百炼中的真实异构路径；Codex Worker 由 `codex-cc` 以 `gpt-5.6-luna`、`max` 启动。AgentLoop 只做无侵入接入准备，不能控制或否决运行。
3. `M2 工程与安全`：继承 Policy/HITL、业务恢复与 fencing、双 Oracle、PostgreSQL 质量证据账本、Gold/密钥隔离；把同一真实 Run 的 OTel/LoongSuite Trace 查询回 AgentLoop，形成观测→评估→归因→改进→复评闭环。
4. `M3 效果`：继承 OpenWorker PR #161 Golden Dataset、runner/verifier 和指标合同，执行 E0–E3 配对复跑；历史结果只作先验，不替代新基线运行。
5. `M4 交付`：继承可用的产品展示、离线包、复跑脚本和开源材料；所有 UI、PPT、视频只展示已冻结的真实 receipt，不造历史数据。

每项资产都必须依次完成：证明原生缺口 → 在资产清单中分类 → 只迁入最薄差异层 → focused test → 真实运行验证 → receipt/保留或回退决定。禁止整提交回灌；旧 TaskRun/Scheduler、第二 Manager 协议、Observer 调度权、Room/Session 重建、Hermes 专用桥和外围巨型 Gate 永不继承。

## 5. 当前事实

- 新仓库基线提交：`f2b57d4`，此前工作树干净。
- 原生隔离运行栈 `agentteams-native-m0-20260901-*` 已恢复真实 provider 路由；官方 M0 实际完成 Manager 两次 provider 调用、Leader 原生 TeamHarness 委派、Worker 真实模型/Skill、submit/check/accept 和 Manager 中转收口。功能闭环已通。
- M0 功能闭环已通，但早期 replay 缺少可独立关联的跨 Actor wire payload；补采已冻结 24 条脱敏原始事件，仍诚实分类为 `PARTIAL`。不再打磨旧 Run，下一次 M1+ 直接按完整采集合同生成 canonical evidence。
- 第一次原生双 Team M1 已结束并冻结 `testweaver/evidence/m1/m1-receipt.txt`：两 Team、两 Leader、两真实 QwenPaw Worker、结构化 Handoff、真实 DeepSeek provider run 与 Manager 最终回读均已出现；核心链路成立，整体仍为 `PARTIAL`。阻断升级的运行事实是 Manager 在 OpenClaw compaction 后重复消费同一 Human prompt，以及一次裸 Worker 名称 `m.mentions` 未唤醒第二 Worker。
- Manager compaction 重复 intake 已由 `15b7b14` 最小修复并通过 17 项测试，修复镜像已部署但尚未由新的真实 compaction 场景验证；Controller 历史 `leave` 重复 force-leave 已由 `037a0bb` 最小修复并通过 focused tests，修复镜像未部署。两项都不得在新的真实 Run 前称为 LIVE 行为 PASS。
- Controller 官方 embedded 构建已确认两个独立环境根因：Alpine 官方源超时，以及无 buildx 的 legacy builder 不会自动注入未声明的 `BUILDPLATFORM`。阿里云 Alpine mirror 已验证可用；当前只补全 Dockerfile 全局 `ARG BUILDPLATFORM` 并沿官方 Make target 产出带 commit/digest 的镜像，不改部署。
- M1 第一批差异资产已完成 source-only 薄化：五个领域 Skill `19a929e`、Context/Claim/Evidence/Provenance/Handoff 合同 `ea5366f`、provider-agnostic DSH 与 Codex CLI 适配合同 `79d9a69`。当前测试只是源码合同证据；DeepSeek、阿里云百炼和 `codex-cc`（`gpt-5.6-luna`、`max`）仍须在 M1+ 真实运行分别验证。
- M1 两个功能阻断修复已进入运行镜像：Manager `agentteams/manager:m1plus-15b7b14`（image `798d52808f58…`）和两个 M1 QwenPaw Worker `agentteams/qwenpaw-worker:m1plus-342d1ee`（image `884f8bf1db0e…`）已通过原生 `agt update` 逐个可回滚更新，健康、身份、Team 状态及配置名称均通过；尚未运行修复后的真实模型任务，故仍不能把修复写成 LIVE 行为 PASS。
- Controller/embedded 修复镜像已由官方入口成功产出（`d9480c0`，embedded `7bacad3eb7ec…`），但当前隔离栈没有可证明等价的完整受保护重建入口。membership 修复仅消除重复 force-leave 噪声，不阻止安全真实运行，因此不替换当前 Controller，登记为 `WARN/PARTIAL` 后置。
- 五个领域 Skill 的 AgentTeams frontmatter、目录/名称、manifest hash 与凭据扫描均 PASS；当前缺口不是 Skill 内容，而是尚未通过 QwenPaw 原生 `AgentSpec/package → workspace/skills → refresh → batch-enable` 装入运行态。CMS/OTel 不负责 Skill 安装，静态文件和 receipt 也不能证明 invoke。
- M1+ 真实 Run `m1plus-20260901T193737Z` 已冻结：单次 Human 输入触发 Manager 动态选择两个 Team/Leader，两条新原生 Project/Task、两个真实 Worker provider 调用、两次 submit/check/accept/handoff 和 Manager 最终报告；36 分钟内无第三 Task 或重复 intake。核心原生双 Team 链 PASS，整体仍 PARTIAL。receipt/manifest/hash 为 `82332fc`，独立 review 为 `e09309b`。
- M1+ 独立复核确认五个领域 Skill 的 source/runtime hash 与 enabled 状态，但本 Run exact-name load/invoke 全部 `NOT_OBSERVED`；不得用安装状态冒充调用。`84bd152` 已在原生 AgentSpec `config/AGENTS.md` 增加通用、非案例化纪律：按 `assign_when` 选择零个或多个适用 Skill，经原生路径读取，并在正常 result/handoff 记录 exact name、source commit/version 与 evidence ref；尚未热更新或真实复跑。
- M1+ 仍记录三个非阻断原生缺口：新 Human room 共享 `agent:main:main` session、global task/project 状态投影滞后、global `replyRoute` 指向旧 admin room。它们不推翻已观察的 Team-scoped accepted artifacts，但在后续严格收口前保持 `PARTIAL/WARN`。
- M2-C run `m2c-20260901T211748Z`（commit `503f1d7`）已冻结，状态诚实为 `PARTIAL`：Manager 动态选择 Team、Leader 原生创建 Project/Task 并完成 `delegate_task` 均已成立；但 Task room 中 Worker 虽为 `join`，仍有 0 条 assignment 消息，Leader 未消费跨房间的 `notificationNeeded`，并进入长时间 `sleep` 轮询。因此本 Run 的 Skill invoke、HITL、恢复和双 Oracle 均为 `NOT_OBSERVED`，不能以静态收据补齐。
- 跨房间 assignment 通用根因修复 `be10aaf` 已顺序部署到四个 QwenPaw Agent；健康、身份、Team Ready 和 M2-D 中 Worker 的真实 ack/submit 已证明修复生效。
- M2-D run `m2d-20260901T223736Z` 已真实完成 Manager 选 Team、Leader 委派、Worker 模型/Skill 执行、submit/check/accept 与 `PAUSE`；但 Human 批准被发往 Task room，Leader 正确执行权限拒绝。未出现 `resume_project`、replacement Task 或 `FAULT_READY`，因此未执行容器故障，当前诚实为 `PARTIAL`。唯一下一步是核实并使用 AgentTeams 原生 Human→Manager→Leader 决策链，而不是让 Human 直连 Leader或由脚本改状态。
- 异构 Worker 最薄适配已由 `2e1ef40` source-only 完成：DSH 显式支持 DeepSeek 与阿里云百炼，Codex 使用 `codex-cc`、`gpt-5.6-luna`、`max`；尚未 LIVE，不得替代原生 Leader 分配或回收结果。
- 配置线已建立 names-only preflight，并确认 `/etc/agentteams/agentteams.env`、`providers.env`、LoongSuite、OTel 和 Nacos 只通过外部受保护引用复用；当前 Nacos 探测、OTel Collector 和 LoongSuite 服务状态如实标为延后，不冒充 LIVE。
- AgentLoop 旧资产目前只可称合同/replay/历史受限证据；必须等待同一真实 M0/Hero 后完成真实查询回读。

## 6. 实施顺序与完成条件

1. `M0 原生闭环`：同一真实请求完成 Manager→Leader→Worker→Leader→Manager 二次决策；无旧 Runner 参与。
2. `M1 协作与 Skill`：双 Team、至少三个不同职能 Agent、真实 Skill discovery/load/invoke、结构化 Handoff；证据改变至少一次后续路径。
3. `M2-C`：run `m2c-20260901T211748Z` 保持冻结 `PARTIAL`，不回填未观察的 Skill invoke、HITL、恢复或 Oracle。
4. `M2-D`（唯一下一步，不扩 Gate）：沿 AgentTeams 原生 Human→Manager→Leader 路由完成真实批准与 `resume`；随后执行一次已批准的可恢复故障、原生 cancel+replacement、拒绝旧 Task 迟到提交，再运行双 Oracle。当前 run 若原生状态无法安全续接，则冻结为 `PARTIAL`，只用已验证路径发起一个新 run，不伪改旧状态。
5. `M3 效果`：冻结同输入、预算和 Oracle，单 Agent、同质多 Agent、异质多 Agent至少三次配对复跑；报告质量、重复率、幻觉阻断、协调开销、Token/成本和净价值。
6. `M4 交付`：clean-room 一键运行/复跑、离线包、产品接入、PPT/PDF、8 分钟内视频、许可证/SBOM/贡献指南。第二场景随后用于证明复制性。

HA、PITR、RAG、高并发、容量和灾备在核心闭环前只保留设计，不阻塞 M0–M3。

## 7. 一票否决

- 不得硬编码 Manager choice、Agent 输出、分支结果、HITL 决定或 Oracle 结论。
- 不得用 fixture、静态事件、旧收据、synthetic Trace 或 UI 文案冒充 LIVE。
- Prompt 不能替代身份、来源、权限、状态、恢复、usage 和审计证据。
- 未观察、未查询或未复跑的能力必须标记 `PARTIAL/NOT_OBSERVED/NOT_AVAILABLE`。

## 8. 维护纪律

本文件是当前方向、状态和后续计划的唯一持久化总纲。只在基线、决策、里程碑状态、真实 Gate 或唯一下一步变化时更新；详细命令、日志、Trace、测试和复核进入机器收据，不再建立逐命令长台账。

两名实施 Codex 固定采用“单主线 + 独立加速线”：主线独占当前真实 Run 与本次运行暴露的最小根因；加速线只处理已冻结输入上的证据补采、下一里程碑资产薄化准备或独立模块，不对在途 Run 做提前复核。Reviewer 只在 receipt 冻结后启动。不得并行修改同一文件，不在一次真实 Run 中途频繁改令；只在 run/commit 边界审计和切换唯一任务。发送 tmux 指令后必须回读到明确的 `Working` 或首条回复，输入框中的未提交文字不算已下达。

总控默认每 10 分钟检查两个 Codex 的进度、工作区边界和唯一下一步，不做高频打断。只有出现明确求助、同一错误连续失败、运行无进展、证据/安全红线或需要独立根因定位时，才提前检查并直接提供已验证的最小纠偏。
