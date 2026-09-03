# AgentSwarm competition-v1.3

## 版本定位

- 固定 tag：`competition-v1.3`
- 公开分支：`main`
- 项目身份：AgentSwarm 比赛发行版，运行时代码基于上游 AgentTeams
- 目标：提供包含最新主系统 Dashboard 代码的可联网、可复现源码快照

本版本在 `competition-v1.2` 的开源边界和治理文档基础上，同步主开发工作区已经完成的 Dashboard 更新，包括项目空间、Manager 消息流、真实 Matrix/Controller 数据投影、证据展示和对应测试。同步范围不包含主开发工作区的 `testweaver/evidence/`、本地日志、运行时配置或密钥。

## 复现命令

```bash
git clone https://github.com/wanghaowei06-ui/AgentSwarm.git
cd AgentSwarm
git checkout competition-v1.3

export VERSION=competition-v1.3
export OPENCLAW_BASE_IMAGE=agentteams/openclaw-base
export OPENCLAW_BASE_VERSION=competition-v1.3
export AGENTTEAMS_DASHBOARD=0

make build-openclaw-base
make install-embedded
make wait-ready-embedded
make verify
```

Dashboard 源码检查和单独构建：

```bash
cd dashboard
npm ci
npm test
npm run lint
npm run typecheck
npm run build
```

真实任务、模型 API、管理员密码、端口和故障排查见[比赛版复现指南](../competition-reproduction.md)。所有秘密必须由评委在本地通过环境变量或交互式输入提供。

## 本次快速验证

- Dashboard：18 个测试文件、76 个测试通过。
- ESLint：通过。
- TypeScript `tsc --noEmit`：通过。
- Go 控制器测试：在补齐 `unzip` 的 Go 1.25 容器中执行通过；控制器源码和 `go.mod/go.sum` 仍完整公开，评委可在具备 Go 与 `unzip` 的环境中执行 `go test ./internal/... ./cmd/...`。
- 公开树检查：未包含 `testweaver/evidence`、运行时密钥、依赖缓存、`node_modules` 或 `.next`。

外部模型响应、公共 registry、第三方服务可用性和运行耗时不由本 tag 固定；评委应保存实际 commit、镜像、环境和实时输出作为本次复现记录。
