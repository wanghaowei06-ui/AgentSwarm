# TestWeaver 复赛唯一总控

更新时间：2026-09-03（Asia/Shanghai）

状态：`M2-G_CURRENT_HERO_PARTIAL_SEALED / GOLDEN_HERO_MINIMAL_FIX_BATCH / M0-M1_NATIVE_CHAIN_PASS`

唯一当前里程碑：首轮完整 Hero 已封存为诚实 `PARTIAL`，证明了真实 Manager 两次动态决策、原生双 Team/Leader/Worker、证据根和两个独立 Oracle，但未闭合 DSH→百炼、有效 Human 决定、私有 Gold、恢复、Skill、PG 与 AgentLoop。当前只完成本轮暴露的最小通用修复批次（Taskflow 结构化终态、Matrix event_id 幂等、唯一 Human ACL、Outcome 私有 Gold 角色边界和 fresh-room 上下文约束），构建/部署一次后立即运行新的 Golden Hero；不新增 Gate、协调器或案例特例。

## 0. 今晚批量收口策略（最高优先级，覆盖后文的逐小步运行措辞）

- 不再扩展架构或外围 Gate。当前只收口真实 DSH 启动阻断；每个失败仅修该次原始证据揭示的最小通用根因，随后立即启动新 Hero。
- 一个集成批次只补 AgentTeams 原生没有的四层：DSH/Codex 异构薄适配与统一结果；Outcome/Boundary 双 Oracle；OTel/LoongSuite→AgentLoop 同 Run 查询评估；五个领域 Skill 加 Context/Claim/Evidence/Provenance/Handoff 的版本化改进边界。
- 先对当前仓库、24 项资产清单、旧供体和运行配置做一次完整差距审计；能直接复用的只接线，不重写。把所有可由代码、Schema、配置和离线测试发现的问题合并为一个 allowlist，一次实现和一次独立复核。
- 仅在批量预检全部通过后构建一次最终候选镜像并运行完整 Hero。Hero 自然暴露的问题集中冻结后再做至多一个通用修复批次；只有 provider/异步时序等无法静态证明的问题允许通过真实运行发现。
- 完整 Hero 必须自然包含 Manager 动态选 Team/Leader、双 Team/结构化 handoff、真实 DSH Worker、真实 Skill、Context/Evidence/Claim、真实 HITL、两个独立 Oracle、Leader 收敛和 Manager 二次决策；脚本只配置、采集和收据化。
- 下一次完整 Hero 前只要求 AgentLoop/LoongSuite 可信传输、同 Run 投影入口与 Skill 进化状态机 fail-closed；两者的真实 Trace、评估、提案、Human 决定、canary 和复评必须消费该 Hero 的原始事实并在 Hero 后收口，不能用静态合同代替。百炼统一网关、Codex 第二外部 Worker、HA/PITR/RAG/高并发、第二场景和完整 E0–E3 不阻塞首个完整 Hero。
- “一次性完成”仅指一次接齐上述核心薄层、统一静态验证、一次构建后再联调；不包含企业级数据库硬化，也不得新建第二编排器。下一次 Hero 启动前不消耗新的正式 Run 编号。
- Skill 进化的最低闭环固定为：真实 Trace/结果进入冻结数据集 → 同一评估合同量化并归因 → 产生带版本、证据引用和回滚点的 Skill 变更提案 → Human 批准 → canary → 同集复评；首轮只需证明一项真实 Skill 的完整循环，其余 Skill 共享同一机制。
- AgentLoop 的最低真实门槛固定为：真实 Hero 的 OTel GenAI Trace 经 LoongSuite/Collector 进入同一 AgentSpace 数据面，并能按同一 run/campaign/trace 标识从 AgentLoop 或其权威 SLS 数据面回读；仅有 Collector READY、CMS 可达或本地 synthetic span 不算接入完成。

## 1. 已冻结决策

- 产品仓库：`/root/projects/agentteams`；分支：`testweaver-semifinal`。
- 底座：官方 AgentTeams `2ea027403398dfa06f3fc86445042d59f4684d71`。
- 初赛公开提交 `45070b6`、GitHub `main` `2901065` 和旧仓库 `/root/projects/muti-agent` 只作资产供体与历史证据，不再作为开发主线。
- 选择原因：初赛代码包含可复用领域资产，但也包含自定义 Scheduler、固定 G3 资源、Hermes Leader 和 Python Runner 调度；直接延续会重新形成第二编排器。
- 现有 API Key、AgentLoop、LoongSuite、OTel 和 Nacos 配置必须复用，不要求用户重新填写。只引用 `/etc` 下受保护文件或受控挂载，不读取到输出、不复制或提交密钥值。
- 当前原生基线继续使用已验证的 `agentteams-gateway/deepseek-v4-flash`，直到 M1 原生稳定性收口；异构资产接入前不得为了提前展示而修改在途 Run 的模型、账号、推理强度或 service tier。
- 异构阶段的 DSH 是 provider-agnostic Harness，不得只用 DeepSeek 形成“异构”结论；必须复用现有受保护配置，让至少一个真实 DSH Worker 调用阿里云百炼模型，并把 provider/model/usage/延迟和结果证据与 DeepSeek 路径分开记录。
- 首个真实 Hero 的 DSH→百炼接线优先复用目标 Worker 已由 AgentTeams 注入的 `AGENTTEAMS_AI_GATEWAY_URL` 与 `AGENTTEAMS_WORKER_GATEWAY_KEY`，仅补非密钥模型引用并实测现有 `testweaver-bailian-route` 的 Worker consumer 权限；这比新增宿主密钥投影更符合原生边界。只有真实预检证明该网关路径不能安全提供百炼调用时，才允许把现有百炼凭据以只读容器 Secret 仅挂载给目标 DSH adapter。两种路径都不得让 Secret 进入镜像、仓库、Prompt、任务产物、日志或 receipt，并必须记录同一 Run 的 provider/model、usage、延迟、HTTP/退出状态、request/response hash 和 Worker/Task 身份。
- 统一网关的完整限流、计费和轮换属于 P1；首个 Hero 只要求当前 Worker consumer 鉴权和一次真实百炼调用成立。不得为此重写上层任务链或增加第二路由层。
- Codex CLI 外部 Worker 必须由 `codex-cc` 启动，不使用裸 `codex`；计划模型固定为 `gpt-5.6-luna`、推理强度 `max`。首跑复用当前已登录的受保护 `CODEX_HOME`，只挂载到目标 Codex Worker，不复制认证缓存；M4 稳定复跑可把同一 CLI adapter 改为 API Key 登录。完整 Responses API adapter 属于 P1，不阻塞首次闭环。
- Codex Worker 不再扩写第二套 runtime：优先复用旧资产树 `AgentTeams-pr1139/plugins/teamharness/remote/codex-cli/` 在提交 `071ae6e` 的原生 TeamHarness remote-member、Codex app-server、Matrix assignment、taskflow 和安全隔离能力；当前新仓库 `testweaver/adapters/codex_cli.py` 只保留固定 `codex-cc` 启动约束与 TestWeaver result/receipt 映射。旧资产树的未提交修改不直接复制，必须先证明相对 `071ae6e` 的必要性并独立复核。
- 当前协作在同一工作区完成；按文件范围并行，不再为小任务创建大量 worktree。
- Element 与演示材料统一使用中文角色显示名，内部 AgentTeams resource name、Matrix ID、Task ID 保持英文稳定标识，避免破坏房间、委派和证据关联。默认映射：Manager=`总控协调者`；`native-m0-clean-leader`=`异构探索团队-组长`；`native-m0-clean-dsh-worker`=`异构探索团队-探索者1（DSH）`；`native-m0-clean-worker`=`异构探索团队-证据分析员`；`native-m0-boundary-oracle`=`异构探索团队-边界验证者`；`native-m1-verify-leader`=`收敛验证团队-组长`；`native-m1-verify-worker`=`收敛验证团队-修复验证者`；`native-m1-outcome-oracle`=`收敛验证团队-结果验证者`。Manager、Leader、Worker 的任务正文和面向 Human 的回报默认使用中文，协议字段、代码、日志键和证据标识保持英文。显示名只在当前 Run 进入终态后统一应用，不在运行中途改身份元数据。
- 完整目标态以 [`semifinal-complete-project-proposal.md`](semifinal-complete-project-proposal.md) 为准；该方案已按最新复赛五项评分维度、工程安全七个子项和 AgentTeams 原生边界修订。它不承载实时进度，本文件仍是唯一实施总控。

## 2. 目标、评分与最低交付

复赛权重：场景价值与复制性 20%、多 Agent 协同 25%、Skill 工程 20%、工程落地与安全审计 30%、开源贡献 5%。

最低交付不是流程图，而是一个真实、可复现、有效果的纵向闭环：

`Human → Manager 动态选 Team/Leader → Leader 原生分解/委派 → Worker 真实模型/工具/Skill → Leader 验收 → Manager 二次决策 → HITL/恢复 → 双 Oracle → 同 Run 证据与评估`

## 3. AgentTeams 与 TestWeaver 的边界

AgentTeams 原生负责最复杂的通用协议：Manager、Team、Leader、Worker、Human、Matrix、身份与房间、Project/Task 生命周期、`roomflow/projectflow/taskflow`、委派/提交/验收、运行时与 MCP/Skill 装配。

TestWeaver 只做产品差异：

- 3–5 个领域 Skill 及 Nacos/SkillOps 治理；
- Failure/Process Capsule 领域资产：把真实故障或低效过程的指纹、环境、触发条件、证据、根因、修复和回归引用做成不可变 revision/hash；PostgreSQL 只保存 append-only 事件与可检索索引，正文进入受控 artifact store。Leader 在同类任务执行前检索并引用命中项，验证结果回流 Golden Dataset/Skill Candidate。它不拥有 Project/Task 调度权，也不得承诺“永不再犯”；只能以重复命中、阻断或后续同条件复跑证明复发控制有效。
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

每个实现 Step 开始前必须先搜索当前仓库、24 项资产清单和对应供体路径；已有能力只能复用、配置或做薄映射，不得重新实现。当前继承优先级保持为：五个领域 Skill 与 Context/Evidence/Handoff（已迁入，待 LIVE）→ DSH 与 PR1139 Codex Worker（正在 LIVE）→ HITL/恢复/双 Oracle（已有真实 PARTIAL/PASS 资产，补同 Hero 关联）→ AgentLoop/OTel 与 PostgreSQL 证据关联 → Golden/E0–E3 → 离线包与开源材料。历史 receipt 只作来源线索，不替代新运行。

2026-09-02 最终财产扫尾将原 24 项清单与旧 `quality_domain/heterogeneity_policy.py`、`skillops/{nacos.py,agentloop_release.py}`、`benchmarking/agentloop_evolution.py`、`agentteams_adapter/hero_run_bundle.py` 和 `release/bundle.py` 再次交叉核对。新增可取部分只有三类薄能力：异构选择的可审计 Policy fact、Nacos `nacos://` Skill candidate 发布/回读、同 Run LIVE 离线包关联；不得迁入其中任何调度、Worker 生命周期或 replay 驱动逻辑。当前批次完成后差异化资产代码面冻结，后续只修静态验收或真实 Hero 暴露的通用缺陷。

2026-09-03 又完成一次旧仓库→新仓库只读缺口审计。DSH、Context/Claim/Evidence/Handoff、PG authority/Failure Capsule/HITL/Oracle/side-effect、SkillOps/Nacos、OTLP protobuf/SLS、Golden/paired metrics 和 offline bundle 的核心代码均已存在，不再回灌旧大模块。完整 Hero 前只允许补六个运行接线：原生事件→同 Run PG 只读投影（含 recovery/generation/late-reject 引用）、Matrix 原始事件→HITL verifier、Outcome/Boundary 纯 verifier 分模式并由两个现有原生 Oracle Worker 独立运行、异构选择 sealed fact、AgentLoop Dataset/EvaluationTask 最薄写入/回读、真实采集与独立离线复跑 CLI。这些模块只投影或验证已发生事实，不创建 Project/Task、不发 Matrix 调度消息、不代替 Manager/Leader/Worker 作决策。

当前 8 小时时间盒顺序固定为：①收口上述薄接线与 DSH→百炼、Nacos、AgentLoop 非 Hero 真传输预检；②只构建/更新一次候选运行态；③发送一条正常业务目标，运行原生 Manager→双 Team/Leader→QwenPaw+DSH/百炼 Worker→结构化 handoff→真实 HITL/恢复→双 Oracle→Manager 二次决策；④将同 Run 原始 Matrix/AgentTeams、provider/tool/Skill、PG、AgentLoop/SLS 事实与复跑脚本打包；⑤只修真实运行暴露的最小通用根因并复跑。HA/PITR/RAG/高并发、Codex 第二外部 Worker、完整 E0–E3 统计与长期 AgentLoop 资源治理都不阻塞首个纵向闭环。

本轮并行边界固定为两条且互不改同一文件：`testweaver/authority/` 收口 PostgreSQL append-only 质量事件、Failure/Process Capsule、HITL authority、双 Oracle 和 side-effect ledger；`testweaver/{skillops,observability,integrations,evaluation,adapters}/` 收口真实 Matrix Human verification、AgentLoop/SLS trace/evaluation 回读、Nacos Skill 发布回读、DSH→百炼受保护调用和 LIVE 离线包。二者通过稳定 `campaign_id/run_id/trace_id/pg_revision/content_hash` 合约连接，不互相调用调度接口。

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
- M2-D run `m2d-20260901T223736Z` 的 continuation-2 已真实完成 Human→Manager→Leader HITL 决策、同一 Project `resume_project`、恢复 Task、Worker ack/in_progress/submit、Leader accept、`FAULT_READY`、授权范围内唯一 `docker rm -f` 与 Controller 自动重建；真实 HITL 与容器恢复 PASS。故障发生时 recovery Task 已进入终态，重建后未观察到原生 `cancel old with replacementTaskId`、replacement delegate/execute/submit/check/accept 或旧 Task 迟到 ack/submit 拒绝（`NOT_OBSERVED`）。这是本次实验时序边界，不归因于 AgentTeams 故障；整体收据仍为 `PARTIAL`。
- M2-E run `m2e-20260902T001049Z` 已真实完成新 Human 输入、Manager 基于 fresh roster 的动态 Team/Leader 选择、Leader 原生 Project/Task/delegate、Worker ack/真实只读源码与配置观察/partial artifact/唯一 `FAULT_READY`、窄范围 Human 批准、唯一 `docker rm -f`、同一 Worker CR/Matrix identity 的 Controller 重建、Human→Manager→Leader 恢复事实转交，以及 Leader 原生 `cancel_task(old,replacementTaskId=new)`→replacement delegate→真实 Worker artifact/submit→Leader check/accept。Project 最终 completed，old Task 为 cancelled，replacement Task 为 completed。由于容器重建丢失旧 Worker 上下文，未观察到恢复后 Worker 在 old cancelled Task 上下文的真实迟到 submit，故该段诚实记为 `NOT_OBSERVED`，M2-E 整体为 `PARTIAL`；不得伪造拒绝或新增协调器。完整 receipt/manifest 位于 `testweaver/evidence/m2e/m2e-20260902T001049Z/`。
- M2-F run `m2f-20260902T012601Z` 的父收据 `e2bdb1f` 保持原观察窗 `FAIL` 不改写：故障后约 3 分 35 秒冻结时尚未见新容器。其 superseding continuation 随后以只读事实确认 Controller 在约五分钟周期内自然重建同名 Worker（同 CR/Matrix identity，new container `69817b42fde9`，应用 health 200）；Leader 原生完成 old cancel→replacement delegate→Worker submit→check/accept。恢复后的旧 Task 真实 `submit_task` 返回 `ok:false`、`submit_task cannot update terminal task: cancelled`，所以 P0 rejection PASS；但 Leader 重复唤醒发出两次 continuation，产生两次真实拒绝探针，exactly-once FAIL，M2-F 整体 `PARTIAL`。完整增量 manifest/receipt 位于 `testweaver/evidence/m2f/m2f-20260902T012601Z/continuation-20260902T020051Z/`；不得改写父收据或把重复探针升级为 PASS。
- `oracle-dual-20260902T022530Z` 已收口为 `PARTIAL`：独立 roster、Project/Task/delegate 与两个 Worker 的 initial ack 为 PASS；初始 evidence delivery 缺失。四个冻结证据文件随后完成发布、hash/readback，以及一次 Human→Manager→Leader→既有 Task room 的补通知，均为 PASS；补通知后两 Worker lifecycle 均为 `NOT_RESPONDED`，双 Oracle verdict/submit/check/accept 均为 `NOT_OBSERVED`，不得称双 Oracle PASS。完整 closeout 位于 `testweaver/evidence/m2f/m2f-20260902T012601Z/oracle-dual-20260902T022530Z/`；误发 Manager 事件、失败发送尝试及原始 event ID index 均保留。
- fresh retry `m2f-oracle-retry-20260902T030843Z` 已在不重建两个现有 Oracle Worker、无中途补通知的前提下收口：同一冻结 evidence bytes/hash、`gold_ref=null`、一次 Human initial；两个既有 Team/Leader 分别原生创建 fresh Project/Task/room 并 delegate。Boundary Task 的 Worker ack→result→submit、Leader check/accept 与 TeamHarness completed metadata 均已观察；Outcome Task 的实际 Leader-created Task 为 `m2f-oracle-retry-20260902-030843-01`（初始 global projection `task-20260902-030843-outcome-oracle` 保持未修改），同样观察到 Worker ack→result→submit、Leader check/accept 与 completed metadata。两个 Oracle 的独立容器/PID/identity/session、usage 与结果 hash 已脱敏记录；Task room 未观察到跨 Oracle 引用。Manager 在 Human room 的最终汇总未观察到，故 fresh retry 整体仍为 `PARTIAL`，不得升级为双 Oracle PASS。receipt/manifest 位于 `testweaver/evidence/m2f/m2f-20260902T012601Z/oracle-retry-20260902T030843Z/`，manifest sha256 为 `56c515f5c04279000a6dd381616b5f46e8e8abcbb667d157b4c16b703f12d4eb`。
- `83f502f` 独立 reviewer 发现 Outcome lifecycle 的 `assignment_event` 与 `worker_ack_event` 两个引用未进入原始 event-index；两项 exact Matrix 回读均为 `NOT_FOUND`。两支功能 lifecycle 虽观察到结果与 Leader accept，但原始索引未闭合，整体继续为 `PARTIAL`，不得称双 Oracle 已独立 PASS。
- 异构 Worker 最薄适配已由 `2e1ef40` source-only 完成：DSH 显式支持 DeepSeek 与阿里云百炼，Codex 使用 `codex-cc`、`gpt-5.6-luna`、`max`；尚未 LIVE，不得替代原生 Leader 分配或回收结果。
- 观测基座现状（不代表任何 Hero）：LoongSuite Pilot 与 OTel Collector 已 READY；SLS 签名/只读查询已真实返回 HTTP 200，但当前 Trace logstore 的 100 行中没有完整同 Run 关联，`evaluation_detail` 尚不存在并返回 404。现有 Collector 只有本地 file exporter，Manager/Worker 也未消费官方 CMS OTLP 配置，因此云写链仍为 `NOT_VERIFIED`。下一步是发送明确标为 `NOT_LIVE_PROBE` 的真实 OTLP/protobuf 探针并从绑定 SLS 回读，随后才由 Hero 的真实 provider turn 产生 LIVE Trace；不得把本地文件、readiness 或旧 span 升级为 LIVE。
- AgentLoop 旧资产目前只可称合同/replay/历史受限证据；本批次复用现有 LoongSuite、OTel、AgentLoop 与受保护配置，补真实 span、同 Run 关联和权威回读。若现有账号确实缺 AgentSpace/SLS 查询权限，保留原始鉴权失败并诚实标记外部 `BLOCKED`，不得以 synthetic 数据补 LIVE。
- M2-G Stage B run `m2g-stageb-20260902T041117Z-container` 已收口为 `PARTIAL/NOT_OBSERVED`：Human initial 与 Manager 原生响应事件回读 PASS；未观察到新的原生 Project、Task 对象或 Task room，也未观察到 Leader assignment、Worker ack、DSH provider/model/tool call、submit/check/accept 或 Manager 二次决策。唯一 Manager 响应中的 task reference 不足以证明原生 Task；不得补消息、代行或升级为 LIVE。脱敏 receipt/manifest/hash 位于 `testweaver/evidence/m2g/m2g-stageb-20260902T041117Z-container/`。
- M2-G Stage B2 run `m2g-stageb2-20260902T044457Z-container` 同样诚实收口为 `PARTIAL/NOT_OBSERVED`：新的 Human initial 与 Manager 响应已回读；Manager 真实 model turn、`agt get` roster 查询、task directory（`meta.json`/`spec.md`）和 MinIO `mc` 准备动作已观察，但未观察到原生 Project/Task state、Leader room assignment、Worker ack、DSH provider/tool call 或 submit/check/accept。无补消息、无脚本代建 Task、无 Worker 指定；不得升级为 LIVE。脱敏 receipt/manifest/hash 位于 `testweaver/evidence/m2g/m2g-stageb2-20260902T044457Z-container/`。
- M2-G Stage B3 run `m2g-stageb3-20260902T050009Z-container` 在 Manager `AGENTS.md` 通用委派规则提交 `10cb365` 并通过现有 builtin merge 精确同步后执行；Human initial 单次发送/回读 PASS。3 分钟窄观察只见文件层 `task-20260902-050009-m2g-stageb3` 的 `meta.json`/`spec.md`，未观察到精确 run 的 Manager session/model 响应、state 注册、原生 Project/Task 对象或 Task room、Leader assignment、Worker ack、DSH provider/tool call、submit/check/accept 或 Manager 二次决策。文件准备不等于原生委派；无补消息、无脚本代建、无 Worker 指定，整体继续 `PARTIAL/NOT_OBSERVED`。脱敏 receipt/manifest/hash 位于 `testweaver/evidence/m2g/m2g-stageb3-20260902T050009Z-container/`。
- 对 B3 的后续独立精确回读不改写 `3b701ac` 或其冻结收据：原始“未观察”结论由观测面缺陷造成（Manager 容器无 `rg` 且 stderr 被吞掉；Matrix `/messages` 返回事件缺少 `.room_id`，旧过滤器因此丢弃全部事件）。回读实际找到 B3 的 Manager session/model、文件/MinIO/manage-state 准备、Manager→Leader 真实 assignment 与 Leader 原生委派，故不能再把 B3 说成没有进入 Leader；功能结论仍保持 `PARTIAL`。同时，B2/B3 都复用了 `agent:main:main` 的 session `72f72165-65e6-4911-95d4-415b63ffac21`，而 `10cb365` workspace builtin 同步发生在复用期间；OpenClaw 的 bootstrap snapshot 按 `sessionKey` 缓存，未轮换 session 时不能证明新 builtin 进入系统上下文。
- 按官方 `sessions.reset` 路径将同一 Manager/room 的 main session 轮换为 `6db603cd-7097-4be7-b900-462df3aacbd5`，workspace `AGENTS.md` 已经由现有 builtin merge 同步并在新 session 的 system-prompt report 中 readback（source `10cb365`、workspace hash 已收据化）；模型、镜像、账号、Team 与 room 未改变。fresh Stage C `m2g-stagec-20260902T052613Z-container` 的唯一 Human initial 回读 PASS，Manager→Leader 原生 Project/Task/delegate、Worker 真实 model/tool/Skill turn 与 `ack_task(in_progress)` 已观察；但 run-scoped DSH/百炼 provider call、usage/latency、result、submit/check/accept 和 Manager 二次决策均未观察到，Task room wire 仅见 create 且无 `m.room.message`，所以 Stage C 诚实收口为 `PARTIAL/NOT_OBSERVED`，不再补消息、轮询或修运行态。脱敏 receipt/manifest/hash 位于 `testweaver/evidence/m2g/m2g-stagec-20260902T052613Z-container/`。
- 2026-09-03 Hero 前薄接线已提交：双 Oracle 分模式与外部密封离线证明 `4fb580c`；只读原生采集器 `92314b6`、生命周期加固 `52cd73a`、真实 Skill API 兼容 `0855fbd`；Oracle 隔离 AgentSpec 包 `abfd7f7`；AgentLoop signed transport/XTrace 回读 `0855fbd` + `5d0562c`；原生事实 exact-GET/Actor/HITL/Oracle 可信化 `8994b8d`。采集器已在当前两 Team/七 Agent 栈做临时真实只读演练，最终 checksum PASS，未发送消息或调用模型。
- 两个现有 Oracle 已通过原生 AgentSpec desired-state 应用隔离配置：Boundary 只有公开输入/Policy 与 `verify_boundary`；Outcome 独占私有 Gold 与 `verify_outcome`。普通 Worker、两名 Leader、DSH、Boundary、Manager mirror 与共享对象存储均回读为无 Gold；Outcome 私有文件只在自身容器存在。真实 verdict 仍须由新 Hero 中两个原生 Task/两个身份/进程产生，当前仅为配置预检。
- DSH package、固定 Node22、pnpm forest 与 runtime-root 投影修复已提交为 `13c6b02`、`a3412a8`、`3eb5875`、`7f3d0c8`、`ff865bd`、`3d060b5`、`5ef1760`、`f1a230a`、`6c50233`、`bb5f38f`。运行时随后暴露底座没有带入既有 QwenPaw bounded MCP readiness；`b28baee` 将已有 `a2ad50e` 源投影进扩展镜像，真实 Worker 已自然达到 health/version/MCP 200。第一次修复后 DSH probe 已实际启动 child 并生成 session，但统一结果目录被 Filesync 以 `0755` 恢复，安全门拒绝落盘；`9aa1d0c` 只对批准 workspace 内、非 symlink、当前 Worker 属主的固定结果目录收紧为 `0700`，77 项 adapter tests PASS。修复后经 AgentTeams 网关的唯一 probe 实际到达 DSH child，但上游返回 HTTP 404；同一受保护 endpoint/model/key 的百炼直连最小调用为 HTTP 200，证明故障在 Higress 路径转换。按时间盒降级为 P1 后，三个值以 root:root、目录 `0700`、文件 `0400` 的只读 file refs 投影到该 Worker 独占 auth volume；唯一 file-ref `aliyun-bailian` 调用已由同一 MCP 启动真实 DSH、exit 0、result `completed` 并生成 artifact，因此 DSH/百炼 preflight 升级为 `DSH_BAILIAN_LIVE`，hash-only 证据提交为 `c3eaf93`；该调用未暴露的数值 usage/HTTP 保持 `NOT_OBSERVED`，不得借用独立直连调用补齐。
- `b28baee` 独立复核无 P0、保留两个 P1：构建 staging 当前复制整个 `qwenpaw_worker` 工作树且只做 marker smoke，可能携带 ignored `__pycache__`/本机路径，源码也未由固定 blob/hash fail-closed。当前实测目录未发现秘密值且镜像只在本机运行，首个 Hero 可登记 `P1_BUILD_PROVENANCE` 后继续；闭环后必须收紧为 tracked `worker.py` 单文件、固定 blob/SHA-256 与实际 import/readback，再制作发布镜像和离线包。
- `9aa1d0c` 独立复核无 P0、保留一个 P1：结果目录完成二次校验后仍按路径名创建 artifact，恶意并发替换父目录为 symlink 时存在 TOCTOU。当前 Hero 沙箱无恶意并发替换者，可登记 `P1_ARTIFACT_DIR_TOCTOU` 后继续；发布镜像前改为固定目录 FD、`O_DIRECTORY|O_NOFOLLOW`、`fstat/fchmod` 和 `openat`。
- Skill 进化可信修复 `fa97634` 已将调用者自报 Matrix/Nacos/AgentLoop/canary 收据降为 `UNATTESTED_PARTIAL/BLOCKED`，并要求真实 Nacos exact readback 与最终官方 PROMOTE/ROLLBACK operation receipt；109 项测试 PASS。它仍须消费本次 Hero 的真实 Trace、Human、canary 与复评事实，当前不是 LIVE。
- AgentLoop 真回读层已恢复 Dataset/EvaluationTask 的严格 scope/hidden-gold/终态/非空结果门槛，并实现 XTrace `GetTrace` 最多三次、90 秒的 hash-only 回读。2026-09-03 使用现有受保护凭据的只读 STS 与 `ListEvaluationTasks` 已返回 200，历史 403 不再作为当前事实；Hero 后先做基于真实 native provider/session/Task facts 的 `PROJECTED_LIVE_TRACE`，只有 LoongSuite 原生 span 云端同一行完整回读才称 `NATIVE_LIVE_TRACE`。
- 2026-09-03 `889039b` 增加 trace-native `CreateEvaluationTask` 接线：真实同一 campaign/run/trace 的任务创建、归属/范围/evidence binding 回读和终态均已被 AgentLoop 接受；backfill 返回 0 条源记录，故仍为 `NOT_VERIFIED`，不把 API 接受误写成 LIVE 评估。v9 离线包已纳入该安全事实，`verify`/`replay` 通过且整体仍为 `PARTIAL`。下一系统阻塞是同一真实 Trace 的 AgentLoop/SLS 源记录摄取与可回读，不再扩展采集器。
- 2026-09-03 后续收口为 `verify_trace_evaluation_task_run`：Hero 回读现在还必须验证 AgentLoop 任务的 `dataType=trace`、`config.dataScope=trace` 与精确 TraceID 过滤，避免同标签 Dataset 任务误通过；47 项集成/桥接测试通过。该修复只收紧证据边界，不改变当前云端 0 条源记录的 `NOT_VERIFIED` 结论。
- Hero capture 与 AgentLoop exact scope/hash 校验已提交 `96af1e8`：真实 PG 查询会保存 raw tuple/exact readback，AgentLoop 核验 trace/content/provider record/source hash，无配置时仅为 `LOCAL_PROJECTED`；无法可靠绑定 provider turn 或 Skill 时保持 `NOT_OBSERVED`。独立复核同时确认本地 fixture 可重封自身哈希，因此仅凭 capture/SHA256SUMS 最高只能称 `UNATTESTED_CAPTURE/OFFLINE_HASH_CLOSED`，不能标记 LIVE；真实升级必须由受保护身份重新执行 Matrix exact GET 与 AgentLoop/XTrace/SLS query，并绑定同一 capture root。完整离线防伪还需包外签名或在线 append-only 信任根，首跑不新增此 Gate。
- 当前 Manager/Leader/Worker 容器未注入 `OTEL_*`/LoongSuite 自动探针环境。首个 Hero 允许把真实 provider/session/Task 原始事实转换为标准 OTel GenAI span并经现有 Collector 写入云端，但只能称 `PROJECTED_LIVE_TRACE`；只有自动探针原始 span 与同 Run 云端回读同时成立才称 `NATIVE_LIVE_TRACE`。这不阻塞 AgentTeams 纵向闭环，但材料必须如实区分。
- 独立运行期复核确认 TeamHarness MCP 当前信任调用者自报 `role`，普通 Worker/Oracle 在能力上可冒充 Leader 调用部分管理动作。首个 Hero 可继续，但必须登记 `P1_SECURITY_GAP / LEAST_PRIVILEGE_NOT_ENFORCED`，保存 Oracle 未调用管理工具及 Leader 实际验收的原始证据，且不得宣称强 RBAC；闭环后在 AgentTeams TeamHarness 单点以运行时身份和 action allowlist 修复，禁止另造 TestWeaver 权限层。
- 首轮完整 Hero `openworker-pr161-hero-20260902T221938Z` 已停止采集并通过全量 `SHA256SUMS` 校验，独立评估固定为 `PARTIAL`，不得补写为 PASS。真实观察到 Manager 首次选探索 Team、探索 Leader 原生 DAG/双 Worker 委派、QwenPaw 模型/工具执行、证据根冻结、Manager 基于新证据二次选路、收敛 Team 复核以及两个独立 Oracle 任务/进程。未闭合项为：DSH→百炼因审批超时未到 provider；旧 ACL 拦截第一次 Human 决定；DSH 正文 `BLOCKED` 与 Taskflow metadata `SUCCESS` 冲突；重叠 QwenPaw channel 对同一 Matrix event 重复入队；探索 Leader closeout `CONTEXT_UNFIT`；Outcome 被错误下发 Gold-free 约束而未用隔离私有 Gold；恢复、Skill invoke、PG tuple 与 AgentLoop 同 Run 回读未观察。封存根位于 `testweaver/evidence/hero/openworker-pr161-hero-20260902T221938Z/`，外部评估位于 `testweaver/evidence/hero/assessments/openworker-pr161-hero-20260902T221938Z.json`。
- 唯一外部 Human `@nativeadmin:matrix-native-m0-20260901.agentteams.local:28080` 已通过 QwenPaw ACL API 精确加入当前七个 Hero Worker/Leader 并逐个回读为 true；随后一次自然触发的高风险清理请求已由该身份在 Matrix 中实时 `DENY`，pending 数回到 0，证明身份通路已修复。该动作发生在首轮 capture STOP 边界之后，只是下一轮预检证据，不能回填首轮 HITL。

## 6. 实施顺序与完成条件

### 2026-09-02 核心批量收口顺序（supersedes 本节中更严格的首次闭环前置）

- 当前失败 Run 已冻结，不再继续或补造事件。先收口它揭示的 DSH profile 裸包解析根因；AgentLoop 传输/查询与 Skill 进化合同并行达到 fail-closed 后立即启动新的完整 Hero。两者的同 Run 真结果在 Hero 后生成，不再作为逻辑上不可能满足的 Hero 前置。
- 本批次提交后的下一唯一验收是一个新的、同一权威 `run_id/campaign_id/trace_id` 的真实 Hero。Human 只提供业务目标，不指定 Team、Worker、分支、审批结果或 Oracle 结论；系统必须自主完成 Manager 动态选择 Team/Leader → Leader 原生拆解与委派 → QwenPaw 与 DSH/百炼异构 Worker 真实执行及领域 Skill 真实调用 → 证据驱动的结构化 handoff → Policy 触发真实 Human PAUSE/外部决定/new revision resume → 两个独立身份/进程的 Outcome/Boundary Oracle → Leader 汇总 → Manager 读取新证据并作第二次真实决策。同时必须把该 Run 的 OTel GenAI Trace 经 LoongSuite/Collector 写入 AgentLoop/AgentSpace 绑定的 SLS 并按同一关联键查询回读；随后至少选择一次本 Run 暴露的真实问题，经冻结 dataset/evaluation、归因、版本化 Skill proposal、外部 Human approval、canary、同集复评和 promote/rollback 形成可审计 Skill 进化收据。
- 同一真实问题还必须生成持久化 Failure Capsule，并在下一次复跑前由 Leader 按指纹检索/readback；复跑收据记录是否命中、采用了哪条证据/修复/回归引用以及问题是否复发。这一证明并入 Skill 进化闭环，不新增调度状态机。当前新仓库只有方案与诊断 Skill 引用，旧仓库的 `capsule_event/capsule_projection` 是待薄迁移供体；在真实 PostgreSQL 写入、重启后回读及复跑命中之前保持 `NOT_VERIFIED`。
- 上述各项必须由同一 Run 的原始 AgentTeams、provider/tool/Skill、Matrix、PostgreSQL/Event Store 与 AgentLoop/SLS 事实互相对账。缺项即按 `PARTIAL/NOT_OBSERVED/BLOCKED` 诚实分类；禁止用此前分散 Run、静态合同、fixture、synthetic span、提示词自述或脚本注入补齐。首次执行只修真实运行揭示的最小通用根因并复跑，不把案例改造成预定成功路径。
- 今晚 P0 是同一真实输入完成：Manager 动态选择 Team/Leader → Leader 原生委派 → QwenPaw 与 DSH 两种真实运行时 → 真实模型/工具/领域 Skill → Context/Evidence/Claim 约束与结构化 handoff → 真实 HITL → Outcome Oracle 与 Boundary Oracle 两个独立身份/进程实际执行 → Leader 汇总 → Manager 二次决策，并保留同一 run 的原始身份、来源、hash 与生命周期证据。不得为凑项修改案例或结果。
- 今晚闭环若使用 DSH+DeepSeek，只证明“AgentTeams 原生协作 + DSH 异构运行时”，不声称不同模型供应商异构；分类必须诚实。M2-D/M2-F 的既有 HITL/恢复证据保留，但不能冒充在今晚同一 run 内发生。
- DSH→百炼真实调用、双 Oracle、AgentLoop 同 Run 真回读以及至少一项 Skill 的版本化改进循环属于作品核心，不得后置；`codex-cc` 第二外部 Worker、恢复同 Run 重演、完整 E0–E3 三轮统计和材料打包在首个完整 Hero 后连续完成。
- PG 在首个完整 Hero 前只承担现有权威 Run/事件/证据关联；PG 强一致扩展、HA/PITR/RAG、高并发、容量与灾备后置。真实性、身份、来源、越权和危险操作审批始终硬阻断。

1. `M0 原生闭环`：同一真实请求完成 Manager→Leader→Worker→Leader→Manager 二次决策；无旧 Runner 参与。
2. `M1 协作与 Skill`：双 Team、至少三个不同职能 Agent、真实 Skill discovery/load/invoke、结构化 Handoff；证据改变至少一次后续路径。
3. `M2-C`：run `m2c-20260901T211748Z` 保持冻结 `PARTIAL`，不回填未观察的 Skill invoke、HITL、恢复或 Oracle。
4. `M2-D`：continuation-2 已证明真实 HITL 与 Controller 容器恢复；由于故障发生时 Task 已终态，原生 replacement/迟到拒绝为 `NOT_OBSERVED`。若后续需要复制该边界，必须先确保故障发生时 Task 仍处于可取消执行态；本次结论是实验时序边界，不归因于 AgentTeams 故障。
5. `M2-G 异构闭环`：先以只读容器 Secret 完成一次真实 DSH→百炼调用和原生 submit/check/accept；只有实际运行需要且能在短时间内完成时才切统一网关。随后以 `codex-cc` 受保护登录完成独立 Codex Worker 证据。两条路径都必须有模型身份、usage、延迟、hash、进程/runtime 与同一权威 Run 关联，凭据值永不进入证据包。
6. `M3 效果`：冻结同输入、预算和 Oracle，单 Agent、同质多 Agent、异质多 Agent至少三次配对复跑；报告质量、重复率、幻觉阻断、协调开销、Token/成本和净价值。
7. `M4 交付`：clean-room 一键运行/复跑、离线包、产品接入、PPT/PDF、8 分钟内视频、许可证/SBOM/贡献指南。第二场景随后用于证明复制性。

HA、PITR、RAG、高并发、容量和灾备在核心闭环前只保留设计，不阻塞 M0–M3。

## 7. 一票否决

- 不得硬编码 Manager choice、Agent 输出、分支结果、HITL 决定或 Oracle 结论。
- 不得用 fixture、静态事件、旧收据、synthetic Trace 或 UI 文案冒充 LIVE。
- Prompt 不能替代身份、来源、权限、状态、恢复、usage 和审计证据。
- 未观察、未查询或未复跑的能力必须标记 `PARTIAL/NOT_OBSERVED/NOT_AVAILABLE`。

## 8. 维护纪律

本文件是当前方向、状态和后续计划的唯一持久化总纲。只在基线、决策、里程碑状态、真实 Gate 或唯一下一步变化时更新；详细命令、日志、Trace、测试和复核进入机器收据，不再建立逐命令长台账。

两名实施 Codex 固定采用“单主线 + 独立加速线”：主线独占当前真实 Run 与本次运行暴露的最小根因；加速线只处理已冻结输入上的证据补采、下一里程碑资产薄化准备或独立模块，不对在途 Run 做提前复核。Reviewer 只在 receipt 冻结后启动。不得并行修改同一文件，不在一次真实 Run 中途频繁改令；只在 run/commit 边界审计和切换唯一任务。发送 tmux 指令后必须回读到明确的 `Working` 或首条回复，输入框中的未提交文字不算已下达。

总控当前对 Oracle retry 使用每 3 分钟检查两个 Codex 的进度、工作区边界和唯一下一步，覆盖原先的 10 分钟监控文字，不做高频打断。只有出现明确求助、同一错误连续失败、运行无进展、证据/安全红线或需要独立根因定位时，才提前检查并直接提供已验证的最小纠偏。
