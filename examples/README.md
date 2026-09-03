# AgentSwarm 最小真实任务示例

这个示例用于评委或外部贡献者验证：源码能够启动真实系统，Manager 能够通过 Matrix 接收一条真实任务并返回响应。它不使用 mock、固定回复、离线回放或预录证据。

## 1. 固定版本并配置本地秘密

在一个全新的终端中执行：

~~~bash
git clone https://github.com/wanghaowei06-ui/AgentSwarm.git
cd AgentSwarm
git checkout competition-v1.2

export VERSION=competition-v1.2
export OPENCLAW_BASE_IMAGE=agentteams/openclaw-base
export OPENCLAW_BASE_VERSION=competition-v1.2
export AGENTTEAMS_LLM_PROVIDER=qwen
export AGENTTEAMS_DEFAULT_MODEL=qwen3.5-plus
export AGENTTEAMS_ADMIN_USER=admin
export AGENTTEAMS_NON_INTERACTIVE=1
export AGENTTEAMS_MOUNT_SOCKET=1
export AGENTTEAMS_MATRIX_E2EE=0

read -rsp "LLM API key: " AGENTTEAMS_LLM_API_KEY
printf "\n"
export AGENTTEAMS_LLM_API_KEY
read -rsp "Local admin password: " AGENTTEAMS_ADMIN_PASSWORD
printf "\n"
export AGENTTEAMS_ADMIN_PASSWORD
~~~

如果使用其他 OpenAI-compatible provider，变量和 Base URL 见
[比赛版复现指南](../docs/competition-reproduction.md)。

## 2. 构建并启动真实系统

~~~bash
export AGENTTEAMS_DASHBOARD=0
make build-openclaw-base
make install-embedded
make wait-ready-embedded
make verify
~~~

这些命令会从当前 checkout 构建镜像并启动 embedded Controller、基础设施和 Manager。首次构建需要访问公共镜像 registry、依赖 registry 和模型服务。

## 3. 发送第一条真实任务

~~~bash
make replay TASK="请在 Matrix 房间中回复一句可识别的中文确认，并说明你是 Manager"
~~~

然后检查：

~~~bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
make test-installed TEST_FILTER="01"
~~~

可在 Element Web 中打开本地 Matrix 房间，查看真实的 Manager 回复和协作上下文。回复内容和耗时由评委自己的模型服务、网络和运行环境决定，本仓库不提供预录答案。

## 4. 清理

~~~bash
make uninstall-embedded
~~~

这会删除本次 embedded 容器、网络和卷，但不会删除 Git checkout 或本仓库文件。完整端口、故障排查、Dashboard 和结果留存说明见[比赛版复现指南](../docs/competition-reproduction.md)。
