# ADR-0063：禁用身份后的受限 AgentRun 收尾

- Status: Accepted
- Date: 2026-09-07
- Acceptance: 维护者在明确说明清理范围后回复“批准这个受限清理例外”。
- Scope: 可信 BYQ lifecycle consumer 对既有、精确绑定 AgentRun 的终态收尾与原子审计/回执。
- Supersedes: ADR-0025 决策第 6 条的 disabled fail-closed，仅限下述内部清理；其余规则不变。
- Related: ADR-0062 §2、§4。开发接受不授予部署或历史研究续跑权限。

## 决策

用户、工作区或成员关系禁用后，普通读写、创建 AgentRun、注册绑定、审批和后台模型续接
仍拒绝。仅可信 Gateway lifecycle consumer 可提交封闭的规范化终态证据，关闭已经绑定的
AgentRun。此操作不是代表禁用用户恢复业务权限，也不开放 MCP/model 清理工具。

Backend 必须验证持久 personal workspace 的唯一 owner/membership 关系，以及既有 root 的
owner/workspace/session/trace 精确一致；不能根据管理员身份、最新任务、时间或相似主题推测。
禁用情况下不能创建 root、补注册、绑定历史未绑定 run 或修改其他身份字段。
缺失、歧义或无法证明的历史身份保持拒绝并留待隔离盘点。

仅允许 active/pending_binding 的既有绑定 run 单向进入规范化终态；root、run、对应审计和
接收回执必须同事务提交。重复精确证据幂等，矛盾终态拒绝。审计只能追加与该 root/run 的
终态及 sequence 精确相符的 runtime_turn_binding 记录。

数据库触发器保留默认拒绝，并仅针对上述既有 run 的状态/version/更新时间及精确审计允许
窄例外。禁止临时激活账号、关闭触发器、通用 bypass 标志或扩充 Product DSH 权限。
此收尾不改变研究任务、Artifact、训练、回测或 Approval 的状态，也不宣称业务完成。

## 验收与迁移

以隔离 PostgreSQL 覆盖 user/workspace/membership 分别禁用、重复回执、事务回滚、跨身份
拒绝、新建/补绑定拒绝及伪造审计/额外字段变更拒绝。普通 API 授权回归仍须通过。
现有数据不回填猜测身份；使用前向触发器更新，无生产数据删除。撤销例外时恢复默认拒绝，
保留已提交终态与审计事实，不把 terminal run 重新打开。
