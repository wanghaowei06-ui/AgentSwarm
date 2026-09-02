# TestWeaver 复赛唯一总控

更新时间：2026-09-02（Asia/Shanghai）

状态：`M2-C_PARTIAL / M2-D_HITL_AND_CONTAINER_RECOVERY_PASS / M2-D_REPLACEMENT_NOT_OBSERVED / M2-E_NATIVE_RECOVERY_PARTIAL / M2-F_PARTIAL`

唯一当前里程碑：跨房间 assignment 通知修复镜像 `be10aaf` 已部署并由 M2-D 的真实 Worker assignment/submit 验证；M2-D continuation-2 已证明真实 HITL 与单容器恢复 PASS。M2-F continuation 已确认 Controller 在约五分钟周期内自然恢复同一 Worker；P0 terminal-cancelled rejection PASS，但 Leader 重复唤醒导致两次旧 Task submit 探针、exactly-once FAIL，整体为 `PARTIAL`。原 M2-F 观察窗 FAIL 保持不改写。

## 1. 已冻结决策

- 产品仓库：`/root/projects/agentteams`；分支：`testweaver-semifinal`。
- 底座：官方 AgentTeams `2ea027403398dfa06f3fc86445042d59f4684d71`。
- 初赛公开提交 `45070b6`、GitHub `main` `2901065` 和旧仓库 `/root/projects/muti-agent` 只作资产供体与历史证据，不再作为开发主线。
- 选择原因：初赛代码包含可复用领域资产，但也包含自定义 Scheduler、固定 G3 资源、Hermes Leader 和 Python Runner 调度；直接延续会重新形成第二编排器。
- 现有 API Key、AgentLoop、LoongSuite、OTel 和 Nacos 配置必须复用，不要求用户重新填写。只引用 `/etc` 下受保护文件或受控挂载，不读取到输出、不复制或提交密钥值。
- 当前原生基线继续使用已验证的 `agentteams-gateway/deepseek-v4-flash`，直到 M1 原生稳定性收口；异构资产接入前不得为了提前展示而修改在途 Run 的模型、账号、推理强度或 service tier。
- 异构阶段的 DSH 是 provider-agnostic Harness，不得只用 DeepSeek 形成“异构”结论；必须复用现有受保护配置，让至少一个真实 DSH Worker 调用阿里云百炼模型，并把 provider/model/usage/延迟和结果证据与 DeepSeek 路径分开记录。
- 首个真实 Hero 的 DSH 百炼接线采用风险分层：P0 允许把现有百炼凭据以只读容器 Secret 仅挂载给目标 DSH adapter，先直连百炼跑通真实调用；Secret 不得进入镜像、仓库、Prompt、任务产物、日志或 receipt，运行后必须做 names-only readback 与泄密扫描。即使暂时绕过统一网关，adapter 仍必须记录同一 Run 的 provider/model、usage、延迟、HTTP/退出状态、request/response hash 和 Worker/Task 身份。该路径只证明真实异构调用，不得宣称已完成网关级统一限流、计费、轮换或消费者鉴权。
- P1 在首个 Hero 冻结后把 DSH 切回现有 AgentTeams Provider/Route 和 Worker consumer credential；沿用同一统计/receipt schema，不重写上层任务链。网关化不得重新成为首次闭环前置条件。
- Codex CLI 外部 Worker 必须由 `codex-cc` 启动，不使用裸 `codex`；计划模型固定为 `gpt-5.6-luna`、推理强度 `max`。首跑复用当前已登录的受保护 `CODEX_HOME`，只挂载到目标 Codex Worker，不复制认证缓存；M4 稳定复跑可把同一 CLI adapter 改为 API Key 登录。完整 Responses API adapter 属于 P1，不阻塞首次闭环。
- Codex Worker 不再扩写第二套 runtime：优先复用旧资产树 `AgentTeams-pr1139/plugins/teamharness/remote/codex-cli/` 在提交 `071ae6e` 的原生 TeamHarness remote-member、Codex app-server、Matrix assignment、taskflow 和安全隔离能力；当前新仓库 `testweaver/adapters/codex_cli.py` 只保留固定 `codex-cc` 启动约束与 TestWeaver result/receipt 映射。旧资产树的未提交修改不直接复制，必须先证明相对 `071ae6e` 的必要性并独立复核。
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

每个实现 Step 开始前必须先搜索当前仓库、24 项资产清单和对应供体路径；已有能力只能复用、配置或做薄映射，不得重新实现。当前继承优先级保持为：五个领域 Skill 与 Context/Evidence/Handoff（已迁入，待 LIVE）→ DSH 与 PR1139 Codex Worker（正在 LIVE）→ HITL/恢复/双 Oracle（已有真实 PARTIAL/PASS 资产，补同 Hero 关联）→ AgentLoop/OTel 与 PostgreSQL 证据关联 → Golden/E0–E3 → 离线包与开源材料。历史 receipt 只作来源线索，不替代新运行。

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
- 配置线已建立 names-only preflight，并确认 `/etc/agentteams/agentteams.env`、`providers.env`、LoongSuite、OTel 和 Nacos 只通过外部受保护引用复用；当前 Nacos 探测、OTel Collector 和 LoongSuite 服务状态如实标为延后，不冒充 LIVE。
- AgentLoop 旧资产目前只可称合同/replay/历史受限证据；必须等待同一真实 M0/Hero 后完成真实查询回读。
- M2-G Stage B run `m2g-stageb-20260902T041117Z-container` 已收口为 `PARTIAL/NOT_OBSERVED`：Human initial 与 Manager 原生响应事件回读 PASS；未观察到新的原生 Project、Task 对象或 Task room，也未观察到 Leader assignment、Worker ack、DSH provider/model/tool call、submit/check/accept 或 Manager 二次决策。唯一 Manager 响应中的 task reference 不足以证明原生 Task；不得补消息、代行或升级为 LIVE。脱敏 receipt/manifest/hash 位于 `testweaver/evidence/m2g/m2g-stageb-20260902T041117Z-container/`。
- M2-G Stage B2 run `m2g-stageb2-20260902T044457Z-container` 同样诚实收口为 `PARTIAL/NOT_OBSERVED`：新的 Human initial 与 Manager 响应已回读；Manager 真实 model turn、`agt get` roster 查询、task directory（`meta.json`/`spec.md`）和 MinIO `mc` 准备动作已观察，但未观察到原生 Project/Task state、Leader room assignment、Worker ack、DSH provider/tool call 或 submit/check/accept。无补消息、无脚本代建 Task、无 Worker 指定；不得升级为 LIVE。脱敏 receipt/manifest/hash 位于 `testweaver/evidence/m2g/m2g-stageb2-20260902T044457Z-container/`。
- M2-G Stage B3 run `m2g-stageb3-20260902T050009Z-container` 在 Manager `AGENTS.md` 通用委派规则提交 `10cb365` 并通过现有 builtin merge 精确同步后执行；Human initial 单次发送/回读 PASS。3 分钟窄观察只见文件层 `task-20260902-050009-m2g-stageb3` 的 `meta.json`/`spec.md`，未观察到精确 run 的 Manager session/model 响应、state 注册、原生 Project/Task 对象或 Task room、Leader assignment、Worker ack、DSH provider/tool call、submit/check/accept 或 Manager 二次决策。文件准备不等于原生委派；无补消息、无脚本代建、无 Worker 指定，整体继续 `PARTIAL/NOT_OBSERVED`。脱敏 receipt/manifest/hash 位于 `testweaver/evidence/m2g/m2g-stageb3-20260902T050009Z-container/`。
- 对 B3 的后续独立精确回读不改写 `3b701ac` 或其冻结收据：原始“未观察”结论由观测面缺陷造成（Manager 容器无 `rg` 且 stderr 被吞掉；Matrix `/messages` 返回事件缺少 `.room_id`，旧过滤器因此丢弃全部事件）。回读实际找到 B3 的 Manager session/model、文件/MinIO/manage-state 准备、Manager→Leader 真实 assignment 与 Leader 原生委派，故不能再把 B3 说成没有进入 Leader；功能结论仍保持 `PARTIAL`。同时，B2/B3 都复用了 `agent:main:main` 的 session `72f72165-65e6-4911-95d4-415b63ffac21`，而 `10cb365` workspace builtin 同步发生在复用期间；OpenClaw 的 bootstrap snapshot 按 `sessionKey` 缓存，未轮换 session 时不能证明新 builtin 进入系统上下文。
- 按官方 `sessions.reset` 路径将同一 Manager/room 的 main session 轮换为 `6db603cd-7097-4be7-b900-462df3aacbd5`，workspace `AGENTS.md` 已经由现有 builtin merge 同步并在新 session 的 system-prompt report 中 readback（source `10cb365`、workspace hash 已收据化）；模型、镜像、账号、Team 与 room 未改变。fresh Stage C `m2g-stagec-20260902T052613Z-container` 的唯一 Human initial 回读 PASS，Manager→Leader 原生 Project/Task/delegate、Worker 真实 model/tool/Skill turn 与 `ack_task(in_progress)` 已观察；但 run-scoped DSH/百炼 provider call、usage/latency、result、submit/check/accept 和 Manager 二次决策均未观察到，Task room wire 仅见 create 且无 `m.room.message`，所以 Stage C 诚实收口为 `PARTIAL/NOT_OBSERVED`，不再补消息、轮询或修运行态。脱敏 receipt/manifest/hash 位于 `testweaver/evidence/m2g/m2g-stagec-20260902T052613Z-container/`。

## 6. 实施顺序与完成条件

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
