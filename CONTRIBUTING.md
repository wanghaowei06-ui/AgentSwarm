# AgentSwarm 贡献指南

感谢你关注 AgentSwarm。AgentSwarm 是基于上游
[AgentTeams](https://github.com/agentscope-ai/AgentTeams) 的公开比赛发行版；源码保留 AgentTeams 的真实运行时契约，仓库入口文档和治理文件负责说明本发行版的边界。

## 贡献前先确认范围

可以在本仓库贡献：

- AgentSwarm 的复现、安装、依赖、开放边界和治理文档；
- Dashboard、公开测试、adapter、Schema、接口和 Trace 规范；
- AgentTeams 运行时的 bug 修复、测试和功能改进，但必须说明它影响的真实组件和兼容性；
- 不包含凭证和私有环境信息的安装脚本、Helm、Docker 和测试改动。

如果你的改动应当进入上游 AgentTeams，请同时遵循上游仓库的贡献要求，并提供公开 PR/Issue URL。AgentSwarm 的本地 commit 不会自动成为 AgentTeams 上游贡献。

## 本地开发

~~~bash
git clone https://github.com/wanghaowei06-ui/AgentSwarm.git
cd AgentSwarm
git checkout main
~~~

按修改范围安装依赖和运行检查：

~~~bash
# Controller
cd agentteams-controller
go test ./...
cd ..

# Dashboard
cd dashboard
npm ci
npm test
npm run lint
npm run typecheck
cd ..

# TestWeaver adapter
python3 -m unittest discover -s testweaver/adapters/tests -p 'test_*.py'

# Shell entrypoints
bash -n scripts/testweaver-config-preflight.sh \
  install/agentteams-install.sh install/agentteams-verify.sh
~~~

涉及真实 Docker、embedded 或 Kubernetes 行为时，还应阅读
[比赛复现指南](docs/competition-reproduction.md)和对应的
[中文开发指南](docs/zh-cn/development.md)，按修改组件运行集成测试。文档-only 改动至少运行
`git diff --check`，并检查相对链接目标。

## 分支、提交和 Pull Request

1. 从最新的 `main` 创建短期分支，例如 `docs/clarify-provenance` 或 `fix/controller-timeout`。
2. 每个 Pull Request 聚焦一个可审查的逻辑变更，说明它属于 AgentSwarm 整理层还是 AgentTeams 运行时。
3. 提交信息应简洁描述行为变化，例如 `docs: clarify dependency boundary` 或 `fix(controller): ...`。
4. PR 描述必须写明运行过的命令、测试结果、兼容性影响和是否需要更新文档/版本记录。
5. 维护者会在合并前检查来源归属、许可证、敏感数据和公开边界。

## 许可证、来源和敏感数据

- 根目录许可证是 Apache License 2.0；新增内容默认遵循该许可证。
- 不删除或改写第三方源文件中的归属和许可证说明。
- 不提交 API Key、Token、密码、私有 URL、未脱敏 Matrix 事件、容器日志、运行证据、数据库、依赖缓存或个人截图。
- 示例和测试使用环境变量传入秘密值，不把真实秘密写入 shell 历史、日志、网页响应或 Git。
- 如果发现已经提交的敏感材料，不要在公开 Issue 复制它；按
  [SECURITY.md](SECURITY.md) 私密报告。

## Issue 和支持

- 可复现的 bug 请使用 [Bug report](https://github.com/wanghaowei06-ui/AgentSwarm/issues/new?template=bug_report.yml)。
- 功能建议请使用 [Feature request](https://github.com/wanghaowei06-ui/AgentSwarm/issues/new?template=feature_request.yml)。
- 安全问题不要公开提交，参见 [SECURITY.md](SECURITY.md)。
- 上游 AgentTeams 的历史、通用社区活动和上游维护范围请以
  [上游仓库](https://github.com/agentscope-ai/AgentTeams)为准。
