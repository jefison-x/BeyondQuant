# GitHub 标准托管 CI（原 Self-Hosted CI 文档）

Status: **Normative replacement under ADR-0060**。文件名保留以兼容历史链接。

当前工作流仍位于 `.github/workflows/ci-selfhosted.yml`，显示名为 **BeyondQuant CI**，
所有 PR、nightly、manual、汇总和贡献授权检查均使用 `ubuntu-24.04` 标准临时 VM。
**不得把公开仓库重新连接到正式机 runner**；同仓分支、fork 或 maintainer 作者判断均不能
代替主机隔离。过去的本机注册命令已删除，历史工作流仅供审计，不是操作建议。

## 验证与资源

复用 `scripts/ci/local-ci.sh`，保留组件完整测试、独立 PostgreSQL、模拟浏览器和真实 Product
API 旅程；每次 run/attempt 有独立镜像、容器、网络、卷和双重清理。Node 24、Python 3.13、
Chromium OS 依赖显式安装，Docker 构建并发为 2。完整规范见 [ci-policy](ci-policy.md)。

标准公开仓库 runner 执行分钟免费；不意味着大型 runner 或超额缓存/制品永久免费。
不得为故障偷偷切回正式机、提高付费额度或跳过测试。VM 资源必须用真实运行记录验证，
CI 不运行正式大规模行情下载、机器学习训练或回测任务，也不执行正式部署。

## 平台发布顺序

1. 按 ADR-0060 合并一次性的 private 发布准备 PR；精确 head CI 全绿并记录维护者授权和审查。
2. 准备 hosted-only PR，不复用一次性例外。公开前完成历史/截图/讨论/日志/来源审计。
3. 暂停仓库 Actions；确认 runner 不 busy 后停止其 systemd 服务并撤销 GitHub 注册。
   检查仓库 runner 数为零，避免仅改标签或停止服务但保留可重启调度凭据。
4. 仓库改 public；立即启用 main strict/up-to-date 的 local-ci + ci-gate、管理员受约束、
   禁止 force push/delete、PR 合并和外部贡献 workflow 审批，最小 token 权限。
5. 恢复 Actions，验证 hosted-only PR 实际完整 CI，正常门禁合并。预发布 auto-merge 仍受
   ADR-0015/0059 限制；仅公开源码不是 v1.0 release。
6. 校验 nightly/manual/fork 工作流均无正式 runner，记录平台前后状态和无生产服务重启。

配置检查：`python3 scripts/ci/check-github-gates.py --repo jefison-x/BeyondQuant --pr <编号>`。
该命令只读，并重新核查精确 head 的贡献授权；不能用本地通过替代 GitHub 的实际 required checks。

## 故障处理

| 现象 | 处理 |
| --- | --- |
| fork 等待批准 | 维护者审查工作流与所有可执行代码后批准；不是让贡献者获得 secrets |
| hosted pending/billing | 检查 public、标准 runner、平台配额；保持门禁，不连接正式机 |
| OOM / 磁盘不足 | 查看 capacity 与构建日志，控制并发/分段；不得停止生产栈或删测试 |
| CLA / 审查失败 | 按完整 head 与 base 协议重新签署/审查，维护者 rerun；不允许管理员绕过 |
| 取消后残留 | 在该 VM 内按 exact run-attempt scope 执行 cleanup 并验零；禁止 broad prune |
| 密钥扫描命中 | 先停合并，确认与轮换真实泄露；不打印值或用全目录忽略掩盖 |

官方依据：[托管 runner](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)、
[计费边界](https://docs.github.com/en/billing/concepts/product-billing/github-actions)。
