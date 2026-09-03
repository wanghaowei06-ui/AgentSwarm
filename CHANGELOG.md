# AgentSwarm 版本记录

本文件只记录 AgentSwarm 比赛发行版和公开整理层的变化，不复制
[AgentTeams 上游项目](https://github.com/agentscope-ai/AgentTeams)的完整历史。

当前公开发行版：`competition-v1.3`。对应的复现入口见
[`docs/releases/competition-v1.3.md`](docs/releases/competition-v1.3.md)。

## competition-v1.3

- 同步主开发工作区中已验证的 Dashboard 项目空间、Manager 消息流和证据展示代码。
- 纳入 Dashboard 的 API、Matrix 投影、项目工作区、运行记录和对应测试。
- 保留 AgentSwarm 的中文复现入口、依赖/许可证边界、贡献、安全和维护文档。
- 快速验证：Dashboard 18 个测试文件、76 个测试通过；ESLint 和 TypeScript 类型检查通过。
- 发布说明：[docs/releases/competition-v1.3.md](docs/releases/competition-v1.3.md)。

## competition-v1.2

- 将根 README 调整为 AgentSwarm 默认中文入口，并保留英文对应入口。
- 明确 AgentTeams 上游来源、Apache License 2.0、第三方依赖和公开/排除边界。
- 增加贡献、安全、行为准则、维护者、Issue/PR 模板和可运行示例。
- 保留真实 AgentTeams Controller、Manager、Worker、Matrix、Helm、安装脚本、Dashboard 和公开测试/Trace 规范。
- 不包含运行时密钥、私有配置、容器日志、历史 evidence、依赖缓存或敏感截图。
- 发布说明：[docs/releases/competition-v1.2.md](docs/releases/competition-v1.2.md)。

## competition-v1.1

此前已发布的不可变比赛快照，继续保留在
[`competition-v1.1`](https://github.com/wanghaowei06-ui/AgentSwarm/tree/competition-v1.1)。
后续版本不会移动或覆盖该 tag。
