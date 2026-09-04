# ADR-0052：中央 Feedback Hub 与会话内审批提交

- Status: Accepted
- Date: 2026-09-04
- Accepted: 2026-09-04
- Decision scope: Phase 92 官方反馈汇聚、匿名投递、中央审核与小巴会话内审批提交
- Related: ADR-0015、ADR-0019、ADR-0024、ADR-0025、ADR-0044、ADR-0049、ADR-0051

## 背景

ADR-0049 的 self-hosted publisher 需要每个部署维护者配置自己的 GitHub App/仓库，不能满足开源用户把问题默认反馈给
`jefison-x/BeyondQuant` 的目标；没有 GitHub 账号的普通用户更不应理解 publisher。小巴原先还要求预览后在下一条聊天中
再次确认，与 ADR-0051 已建立的全局审批中心重复。

只读 Community 没有中央反馈服务、匿名安装身份、relay 或可迁移的反馈实现，因此全部为 `REPLACE`；仅保留集中审批、
角标和原会话恢复的既有 `PORT_UX` 结论。没有复制 Community 源码、运行时或数据。

## 决策

1. 用户在小巴会话中描述问题后，小巴创建私有草稿、展示 Backend 生成的公开候选快照，并立即为精确
   `byq_feedback_submit/product_feedback/<feedback_id>` 请求一次全局审批。审批中心是唯一 Agent 确认入口；批准后续接原
   durable conversation，小巴携带 approval ID 提交同一 version/hash，不再要求第二条聊天确认或跳转业务页。
2. Browser 用户本人仍可在反馈页预览并直接确认。Backend 对 Agent 路径额外校验 approval 的 owner、actor、session、action、
   resource type/id、human reviewer 和 authorized outcome；两条路径共享同一隐私和不可变快照 invariant。
3. 提交与 `feedback-hub-delivery.v1` transactional outbox 同事务。独立、无 GitHub/数据库/源码权限的 local relay 通过 internal
   lease/fence API 向 operator 配置的单一 HTTPS Hub 投递；断网有界重试。Hub 未配置时本地反馈和 outbox 完整保留。
4. Backend 首次建表生成并持久化一个随机、非用户身份的 installation ID。普通用户不提供 GitHub 账号、Token、邮箱、Hub
   凭据或仓库。Hub 只保存 installation/event 的 HMAC，不保存 BYQ user/workspace/session/trace identity。
5. 中央 Hub 再验证大小、schema、hash、secret/PII/security-report policy，按匿名 installation 限流并生成跨安装 fingerprint。
   公开 status 必须同时持有不可猜 receipt 与 HMAC capability token，且只返回状态和最终 Issue 链接，不返回反馈内容。
6. 中央审核状态为 `received -> triaged -> accepted|rejected|duplicate`。只有 `accepted` 才进入中央 transactional GitHub outbox。
   中央 publisher 固定 `jefison-x/BeyondQuant`，复用 ADR-0049 的最小权限 GitHub App、reconciliation、lease/fence 和有限重试；
   local approval 不等于中央采纳，也不承诺公开。
7. 中央 admin token、status secret、PostgreSQL credential 和 GitHub App private key 只存在于 Hub 部署。local BYQ 只配置公开
   HTTPS Hub origin 和 local relay token；Frontend/Gateway/MCP/DSH 不持有中央 secret 或 GitHub credential。
8. 旧 local direct publisher 保留为高级 self-hosted 兼容出口，但不是开源用户默认路径，不影响中央状态。不得让 feedback
   自动变为 EngineeringTask、源码修改或 PR 授权。

## 验收

- Backend tests 证明提交/outbox 原子、Agent approval 精确绑定、撤回、lease/fence、restart 和无 Hub 降级；
- Hub tests 证明二次校验、匿名限流、幂等 receipt、中央审核、固定仓库 outbox 和 capability-token status；
- relay/fake GitHub tests 证明不持有用户/GitHub credential、网络失败有界重试且不重复 Issue；
- MCP/skill/frontend tests 及真实 Chrome 流程证明只需审批中心一次确认、自动返回原会话、普通用户零配置；
- Hub 安装包默认只监听 loopback，必须经 operator TLS reverse proxy 后才可配置到 local relay。

## 拒绝的替代方案

- 每个用户配置 GitHub OAuth/PAT：账号门槛高且扩大 credential 风险。
- 在公开客户端硬编码可写 secret：开源后无法保密，也不能防滥用。
- local approval 后直接创建官方 Issue：绕过中央反滥用/审核，并把官方仓库权限下放到不可信实例。
- Hub 读取 local PostgreSQL 或 DSH 直接请求 Hub：破坏 Domain/MCP 边界和故障隔离。
- 仅按 IP 识别用户：代理/NAT 不可靠且收集不必要身份；IP 只能由边缘限速，不写入反馈记录。

## 回滚

清空 local `BYQ_FEEDBACK_HUB_URL` 并停止 relay 外发，保留全部本地反馈/outbox；中央侧停止 publisher 后再停止 intake，保留
receipt、审核、outbox 和 Issue mapping。不得删除已创建 Issue、重写审核或将中央凭据下放客户端。小巴可降级为只保存私有
草稿并说明 Hub 未配置。
