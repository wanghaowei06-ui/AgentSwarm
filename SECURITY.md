# AgentSwarm 安全响应

## 报告方式

请不要在公开 Issue、Pull Request、讨论区、聊天记录或截图中发布安全漏洞细节、API Key、Token、密码、私有 URL、未脱敏 Matrix 事件或容器日志。

优先使用本仓库 GitHub **Security** 页面中的 **Report a vulnerability** 私密入口联系维护者：

<https://github.com/wanghaowei06-ui/AgentSwarm/security>

如果当前仓库界面没有可用的私密报告入口，请通过维护者
[@wanghaowei06-ui](https://github.com/wanghaowei06-ui) 的公开资料寻找私密联系方式，不要在公开 Issue 中粘贴敏感内容。

报告中请尽量提供：

- 受影响的版本或 commit；
- 影响组件和部署方式；
- 不包含秘密值的最小复现步骤；
- 影响范围、潜在后果和建议修复方向；
- 已采取的临时缓解措施。

## 重点报告类型

请优先报告：

- 凭证、Token、管理员密码或 Matrix 身份泄露；
- Worker 越权访问其他 Worker、Manager 或共享存储；
- 未授权的 Controller、Dashboard、Matrix 或网关操作；
- 远程代码执行、命令注入、路径穿越和任意文件读写；
- 认证绕过、权限提升、敏感日志或网页响应泄露；
- 安装脚本、Docker 镜像或 Helm 配置造成的默认不安全暴露。

纯粹的模型输出质量、外部模型服务故障和第三方服务漏洞，请在安全报告中说明其边界；外部服务的处理由相应供应商负责。

## 处理范围

当前公开发行版支持核查：

- `competition-v1.2`；
- 仍可从公开仓库复现的 `competition-v1.1`；
- `main` 上已经公开的代码和文档。

维护者会先确认收到报告，再判断影响范围、是否需要临时缓解、修复和公开说明。仓库不承诺外部依赖服务的安全响应 SLA；修复外部依赖时会在发布说明中注明依赖版本和适用范围。

如果秘密已经进入 Git 历史：

1. 立即撤销或轮换该秘密；
2. 通过私密渠道提供 commit/path 信息；
3. 不要自行改写公共历史或在公开讨论中复制秘密；
4. 维护者完成清理后重新执行敏感路径和干净克隆审计。
