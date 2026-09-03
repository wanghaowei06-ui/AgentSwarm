# AgentSwarm 维护者与维护范围

## 当前维护者

| GitHub 账号 | 职责 |
| --- | --- |
| [@wanghaowei06-ui](https://github.com/wanghaowei06-ui) | AgentSwarm 公开仓库、比赛发行版文档、Issue/PR 分流和安全报告入口 |

当前维护者代表 AgentSwarm 公开仓库的维护责任，不代表
[AgentTeams 上游项目](https://github.com/agentscope-ai/AgentTeams)的维护团队，也不表示存在第三方共同维护关系。

## 维护范围

当前维护范围包括：

- `main` 分支中已经公开的仓库文档、安装入口、Dashboard 和公开测试；
- 通过 `competition-v1.3`、`competition-v1.2` 与仍可复现的 `competition-v1.1` 发布的比赛材料；
- 对 AgentTeams 运行时源码的公开问题分流和必要的复现说明。

AgentTeams Controller、Manager、Worker、Matrix、Helm 和运行时的上游路线，应同时参考
[上游仓库](https://github.com/agentscope-ai/AgentTeams)。外部模型、Docker/Kubernetes、Higress、Tuwunel、MinIO、Element Web、Go/npm/PyPI 包和其他服务由各自供应方维护。

## 发布和变更规则

- 重要公开变更先在 `main` 中完成审查和验证；
- 可复现比赛版本使用不可变的 `competition-vX.Y` tag；
- 历史 tag 不移动、不覆盖；
- 发布说明记录源码 commit、验证命令、外部前置条件和已知限制；
- 不将本仓库 commit、内部 evidence 或截图写成未经核验的上游贡献、第三方采用或共同维护证据。

## 联系和反馈

一般问题请使用 GitHub [Issues](https://github.com/wanghaowei06-ui/AgentSwarm/issues)，代码和文档改动请使用 Pull Request，安全问题请遵循
[SECURITY.md](SECURITY.md)。
