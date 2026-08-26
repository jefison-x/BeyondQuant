# ADR-0021：Paper Trading Account、Settlement、Risk 与 Transfer Contract

- Status: Accepted
- Date: 2026-08-22
- Accepted: 2026-08-22
- Decision scope: Phase 35 Paper Trading depth
- Related: ADR-0007、ADR-0009、ADR-0012、ADR-0014、ADR-0015、ADR-0016、ADR-0020

## 背景

Phase 35 深化 BYQ 仅模拟的 Paper Trading capability。当时实现持久化 owner-scoped
account、position、order 和 fill，并从 fill 派生 ledger，但未持久化 daily account
snapshot、settlement、risk control、order detail event 或安全 portable account bundle。
Position 只保留 aggregate quantity 和 last buy date，因此 same-day buy 可能错误地使旧
holding 不可 sell。

Read-only Community implementation 为 account selection、六个 detail view、T+1 sellable
quantity、append-only settlement、order lifecycle display、kill switch/max-notional control
和 account transfer UX 提供证据；其 runtime/transfer boundary 不能复制。Community 使用
旧 broker/Agent architecture，并以不足的 canonical validation import 外部 account ID 和
nested record。

## 决策

### 1. BYQ 持有 simulation state machine

Paper Trading 是 PostgreSQL-backed BYQ domain，不是 Backtest 或 live broker。Backend 是
account、order、fill、position、ledger、settlement、risk 和 transfer state 的唯一权威。
不引入 broker credential、external execution call、Community runtime、VectorBT、
BaoStock 或 AKShare path。

每个 mutation 按 owner 隔离、transactional、audited、idempotent。Browser 只通过
Gateway/Product API 提供 durable user identity。DSH 只能用 trusted owner/actor context
propose/invoke 有界 MCP capability，不能访问 PostgreSQL 或 raw Backend route。

### 2. Account 与 frozen universe identity

Account 有 Backend-generated global ID、owner、name、CNY currency、initial/current cash、
current equity、realized P&L、active status、monotonic version、last settlement date 和
timestamp。Money/quantity 使用 exact decimal/integer Contract，不使用 binary-float
identity。

首次 accepted order 前，account 明确绑定 active、owner-equal Stock Pool snapshot。每条
order 也保存 immutable `stock_pool_snapshot_id`。Pool edit 不改变 account binding。
Rebinding 要求没有 open position、compare-and-set account version、idempotency key 和
audit record；automatic rebalance 不属于 Phase 35。Pool inactive/deleted 后 existing order
仍可 replay。

### 3. Order、fill 与 Approval boundary

Phase 35 engine 保持 deterministic immediate simulation：order 要么一次 `filled`，要么以
稳定 reason code `blocked`。不伪造 partial fill、async broker state、cancel/replace 或 live
execution。Order detail 暴露 normalized request、frozen pool snapshot、decision
provenance、risk evaluation、fill、fee/tax 和 immutable event。

Human owner 可在 Product UI 直接 submit simulation order。Agent-originated mutation 必须
携带 accepted ADR-0009 Approval/action reference，并保留 trace/session/run correlation。
Approval 只授权 attempt，不保证 fill，也不绕过 risk 或 market rule。

Authoritative A-share check 保持：canonical symbol、frozen-universe membership、positive
whole-lot quantity、suspension、price limit、sufficient cash/position、T+1、fee 和 sell-side
stamp tax。Caller-supplied market-rule fact 标记为 simulation input，不表示 trusted market-
data provenance。

### 4. Position 与 T+1 settlement

Position persistence total quantity、sellable quantity、same-day locked quantity、average
cost、last mark 和 mark provenance。Buy 增加 total/locked quantity，不减少已有 sellable
holding；sell 只能使用 sellable quantity。通过 additive verified migration 替换 aggregate
`last_buy_date` shortcut。

Manual settlement 接受 canonical trading date 和每个 open position 的一个 positive finite
mark。日期必须严格晚于 account last settlement date，且不早于任何 recorded trade。它
原子地：

1. 将 eligible locked quantity 提升为 sellable；
2. 应用 submitted mark，并记录明确 `manual` provenance；
3. 计算 cash、market value、equity、realized/unrealized 和 daily P&L；
4. append 一个 immutable account snapshot 和一个 settlement audit/ledger event；
5. 推进 account version 和 settlement date。

第一次 identical replay 是 idempotent；相同 account/date 但 mark/semantics 不同的第二次
request conflict。Historical snapshot 绝不 update。Missing/extra mark、non-positive/non-
finite mark、backward date 和 stale account version 均 fail closed。

### 5. Append-only ledger 与 projection

Ledger 由 Backend 生成并持久化为 append-only。它包含 initial funding、每次 fill cash
movement、zero-cash settlement audit event 和 transfer-import provenance。Entry 有稳定 ID、
idempotency reference、event type、trade date、order/fill/snapshot reference、amount
component 和 account-state summary。Valuation change 不伪装成 cash flow。

六个真实 Product view 为 Overview、Positions、Orders & Fills、Ledger、Snapshots、Risk &
Transfer。Order detail 是 persisted projection，不是 raw database 或 DSH event JSON。所有
collection endpoint 都有界且 owner-scoped。

### 6. 明确 risk control

每个 account 保存 versioned control record：

- kill switch 及有界 reason/audit metadata；
- optional maximum order notional，使用 exact CNY decimal。

Control 在 market/execution check 前 evaluate，并记录于 order detail。Kill switch/max-
notional violation 产生稳定 blocked order。Control update 要求 expected version 和
idempotency key。不移植 Community failure circuit breaker：同步 BYQ engine 没有 external
broker failure stream，添加它会形成 false control。未来 async execution Contract 可通过
ADR 增加。

### 7. BYQ Paper account asset bundle

Export 生成有界 canonical JSON bundle，包含 versioned schema、manifest、per-section
count/SHA-256 digest、account semantics、position、order/fill/event、ledger、snapshot、risk
control、frozen universe reference 和 export provenance。排除 owner identity、credential、
token、runtime setting、raw DSH event、market dataset 和 application/Strategy source。

Import 在任何 write 前验证 schema、size/count bound、canonical value、referential
integrity、digest、arithmetic/account invariant、chronology、snapshot immutability 和允许的
local Stock Pool snapshot reference。它始终创建新 Backend-generated account ID、绑定
current authenticated owner、remap internal ID、记录 source bundle SHA-256/import audit，
且不 overwrite account。Imported kill switch 可保持 engaged，但 bundle 中的 actor/owner/
Approval authority 不可信。Invalid bundle 被 atomic reject，不产生 partial state。

### 8. Migration

Current BYQ account 以 logical/idempotent 方式迁移。验证 existing cash、order、fill 和
position；只有 persisted history 可证明时才 reconstruct initial cash，否则 quarantine
等待 operator review。Existing position quantity 变为 sellable，除非 latest unsettled buy
date 证明部分 quantity 应保持 locked。Fill-derived ledger entry 按 migration manifest
deterministically backfill。Ambiguous chronology、invalid arithmetic、cross-owner pool
reference 和 unprovable state 被 quarantine，不静默修复。

Community account/PostgreSQL row 不是本 Phase migration input。Community code、UI、
schema 和 test 保持 read-only evidence。

## 后果

- Phase 35 需要 additive account/position column，以及新 binding、control、event、ledger、
  snapshot、settlement-audit、transfer-audit、idempotency 和 migration-manifest record。
- Existing immediate-fill UX 保持诚实，同时获得 auditable detail、准确 T+1 behavior、
  reproducible valuation snapshot 和实用 control。
- Portable account 成为 BYQ-owned Artifact，不 import authority，也不信任 external ID。
- 未来 live/paper broker Adapter、async lifecycle、cancellation、circuit breaker 或 automatic
  rebalance 需要独立 Accepted ADR。

## 拒绝的替代方案

- 复制 Community broker/ORM/Agent code：违反 BYQ domain、runtime 和 PostgreSQL
  ownership boundary。
- 继续仅从 fill 派生 ledger：丢失 funding、settlement/import provenance，无法提供稳定
  audit trail。
- 将 `last_buy_date` 作为 all-or-nothing T+1 state：same-day purchase 后会错误锁定旧
  holding。
- Update daily snapshot：破坏 replay 和 performance lineage。
- Import 时保留 Community account ID：允许 collision，并 import external identity/
  authority。
- 增加 Community circuit breaker：同步 engine 没有 external failure signal，因此只是
  cosmetic control。

## 回滚

Phase 35 write 存在前，可移除 additive record 并恢复 prior read model。Order、ledger、
settlement、snapshot 或 import 使用新 Contract 后，rollback 表示 disable new write，同时
保留 read-only resolver 和 audit/export path。Immutable history 不得删除或改写。

## Acceptance review（2026-08-22）

维护者指示继续 recommended remediation sequence 后接受本 ADR。Acceptance 建立在对
Community `PaperTradingView.vue`、model、execution/read/repository/tracking/transfer
service、migration 和 test 的 read-only inspection/classification，对当前 BYQ PostgreSQL
storage、Product API、frontend、order rule、Stock Pool reference 和 derived ledger 的
audit，以及对相关 Accepted ADR 的 review 之上。

Acceptance 以 `docs/contracts/paper-trading.md` 中的 contract test 和 Chrome evidence 为
条件。它只在本 ADR merge 后授权在新 isolated worktree 实现 Phase 35；不表示 Phase 35
完成，也不授权 Phase 36。
