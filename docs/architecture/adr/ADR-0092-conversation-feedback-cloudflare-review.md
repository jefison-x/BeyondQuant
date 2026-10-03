# ADR-0092 — 会话反馈与 Cloudflare 唯一审核出口

- Status: **Proposed — 2026-10-03；待维护者审阅接受**
- Scope: BYQ 0.10 发布后 R3 反馈入口、审核与发布边界。
- Supersedes: 归档 ADR-0049/0052/0053 中保留本机 direct publisher 与本地审核作为产品路径的历史决定；不改变其历史验收记录。当前 Clean Break ADR-001/002/004/005/006 的身份、数据、审批与 DSH 边界仍适用。

## 背景

当前用户可从会话和独立 `/feedback` 页面提交反馈；BYQ 还有本机管理员审核及 Python `feedback-publisher` 向 GitHub 直发的第二条路径。中央 Cloudflare Hub、私有 Publisher Worker 与本机 `feedback-hub-relay` 已组成目标链路。两条审核/发布路径使用户入口和发布责任不一致。

## 决策

1. 用户在 BYQ 会话中描述反馈。Product Agent 仅经 BYQ MCP 创建私有草稿、显示脱敏预览；用户对准确快照作明确发送确认。该确认授权披露，不等于管理员采纳。
2. BYQ 在同一事务保存提交事实与 Hub outbox；本机 `feedback-hub-relay` 负责有界投递、回执和状态核对。Cloudflare Hub 是唯一审核地点，私有 Cloudflare Publisher Worker 是唯一 GitHub 写入者。
3. 移除本机 `feedback-publisher`、独立反馈/本地审核页面及其产品入口、未来发布构建目标、本机审核和直发 API/状态机。保留 owner-scoped 反馈草稿、版本、准确确认、业务审计、幂等回执、Hub outbox、状态与 Issue 映射。浏览器只访问 Gateway/Product API，Agent 只访问 BYQ MCP。
4. 历史本机 publication/outbox 记录与生产表不得因代码清理而直接删除。现存未决发布责任须先精确分类与核对；新鲜 schema 可在受测切片移除不再使用的表，生产迁移和物理删除另行具名授权。
5. 旧反馈书签应明确引导到会话。公开状态必须来自 BYQ 持久事实与 Hub 回执；投递、审核、发布和未知结果保持不同语义，不伪造成功。

## 验收

覆盖草稿、脱敏预览、精确用户确认、幂等提交、Hub 投递/回执、状态查询及跨用户拒绝、撤销和未知结果；真实 Gateway/Product API 浏览器验证桌面与移动端会话入口及旧书签。验证本机无 direct GitHub writer，Cloudflare Hub/私有 Publisher 与 relay 的凭据、限时、来源证明仍完整。Tester → 独立 Reviewer → Root 后进入 Draft PR 和发布门禁；生产既有表/备份/镜像清理独立处理。

切换前必须按 [R3 旧反馈记录预检](../../operations/feedback-r3-cutover.md) 在目标数据库
重新运行只读分类，并保存带时间的计数回执。只要本机 publication/outbox 有记录、
或已提交反馈缺 Hub outbox，就阻止切换；先为这些记录另行接受精确迁移/归档方案。
代码中的 Hub-only owner 投影和撤回规则不承担旧本机记录的自动迁移。
