# QwenPaw HITL 持久化

## 目标

让 AgentTeams 管理的 QwenPaw Worker 在审批通知短暂失败、QwenPaw 进程重启后，仍能看到未过期的 HITL 请求，并用同一个 request ID 完成幂等审批；默认审批窗口从 QwenPaw 的 5 分钟提高为有界的 24 小时。审批仍然 fail-closed，过期或 Human stop 不会自动放行。

## 实施范围

1. 在 AgentTeams 的 `qwenpaw-worker` 中增加原子写入的本地持久化审批状态文件。只保存用于恢复和审计的非敏感字段，过滤 channel 实例和凭据类字段。
2. 在 AgentTeams 自带的 QwenPaw Matrix 插件最早加载阶段安装兼容层，接入 QwenPaw 2.0.1 的 `ApprovalService`：创建、解析、取消、过期、列表和重启恢复均同步持久化；等待 Future 使用 shield，避免超时污染可恢复的 Future。
3. 让通知从已注册的 channel manager 获取 channel 实例，并在暂时不可用时持续有限速重试；解决 driver approval 没有 `_channel_instance` 导致只创建请求、不发送 Matrix 提示的问题。
4. 让 Worker 停止前显式上传 HITL 状态文件，避免正常重启时状态只留在容器本地。
5. 为纯状态存储、审批生命周期、通知重试和 Docker/插件接线增加失败测试，并更新 QwenPaw 运行时说明与变更记录。

## 明确边界

QwenPaw 进程崩溃时，原来的 Python 协程本身无法被序列化。持久化层保证审批记录和已作出的决定不丢失；若原执行协程已经消失，后续同一逻辑工具调用需要由 QwenPaw 的任务/消息恢复流程重新发起，不能仅凭恢复一个 Future 自动执行未知的工具。

## 验收标准

- 新建请求落盘后，重新创建 `ApprovalService` 能恢复为同一 request ID 的 pending 请求。
- APPROVED、DENIED、TIMEOUT、CANCELLED 都会落盘；重复解析不会改变第一次决定。
- 未过期请求可在通知首次失败后重试发送；通知正文包含原 request ID。
- 过期请求 fail-closed，重启不会复活；默认不再使用 QwenPaw 的 300 秒 pending GC。
- driver approval 可以通过已注册的 channel manager 找到 AgentTeams Matrix channel 并发出提示。
- QwenPaw Worker 镜像仍从 pip 安装核心 QwenPaw，AgentTeams 只维护可测试的兼容层，不复制整个第三方运行时。
