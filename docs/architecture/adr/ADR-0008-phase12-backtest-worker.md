# ADR-0008：Phase 12 Native Backtest Job 与 Worker Boundary

- Status: Accepted
- Date: 2026-08-16
- Decision scope: Phase 12 Quant Domain Backtest execution
- Supersedes: Phase 5 backtest-worker placeholder

## 背景

Phase 11 提供不可变、经过验证的 StrategyVersion 和 Approval Artifact，但 BYQ 尚无安全
execution boundary。Community evidence 涵盖有用的 A-share trading rule、frozen
universe authorization、content-addressed input manifest、有界 job retry 和不可变 result
reference；其 Pandas、ORM、Agent workflow、optional engine 和 provider integration 不
属于当前架构。

Phase 12 需要持久化 job state 和可复现 result，但不能在 Backend request 中执行生成的
Strategy source，也不能让 Product DSH 访问 business storage。

## 决策

1. BYQ 持有 native deterministic signal-snapshot engine。Submission 必须引用已验证的
   StrategyVersion 和匹配的 approved Strategy Approval，并提供 frozen bar、signal、
   universe membership、corporate action 和明确 execution rule。本 Phase 不执行
   Strategy Python source。
2. Input boundary 对每个 `(symbol, trade_date)` 规范化一条有限 OHLC bar、canonical
   A-share symbol、匹配的 universe membership fingerprint、稳定 signal ordering 和
   secret-free execution parameter。manifest identity 使用 SHA-256 content addressing。
3. Native A-share execution 强制 next-session-open timing、sell-before-buy、T+1 lot、
   limit-up/limit-down、suspension、lot size、cash、commission、stamp tax、corporate-
   action adjustment 和有界 wall-clock execution。Rejected order 保留稳定 reason code。
4. Backend 持有 durable SQLite job state machine 和严格 task-scoped idempotency。Worker
   claim 一个 queued job，将 attempt 最多增加到三次，restart 后重新 queue stale running
   job，并只在 result Artifact 持久化后记录 completion。
5. 完整 result 是 Backend-owned object root 中的 immutable file。Business state 保存
   namespace/object identity、media type、size、SHA-256 和有界 summary。删除要求 owner
   scope 相等并通过权威 live-reference check；被篡改或仍被引用的 object 保留并 fail
   closed。
6. Product Agent 通过 `byq_backtest_*` MCP tool 调用。DSH 不获得 provider credential、
   raw storage access、Strategy source execution privilege 或 PostgreSQL access。

## 后果

- 无密钥 test 可验证 deterministic execution、input identity、Approval authorization、
  job retry/recovery、result integrity 和 MCP translation。
- 独立 `workers/backtest` process 可 claim 并执行 durable job，而不扩大 Product DSH
  capability。
- Strategy source execution、distributed queue 和 live trading 留待后续决策。
  signal snapshot 是 Phase 12 明确的 execution input，因此本 Phase 不隐含不安全的
  Python sandbox。

## 拒绝的替代方案

- 复制 Community Pandas/ORM/Agent Service Backtest runtime 会违反 BYQ ownership，并
  重新引入被排除的 runtime boundary。
- 明确禁止重新引入 VectorBT、BaoStock 或 AKShare。
- 在 Backend HTTP handler 中执行 generated source 不安全且与 ADR-0007 冲突；隔离的
  source-execution boundary 需要后续 ADR。
- 在 business row 中嵌入完整 result data 会形成无界数据，并妨碍 object integrity/
  lifecycle control。

## 退出证据

Phase 12 test 覆盖 deterministic manifest、OHLC/duplicate rejection、next-session
execution、T+1/limit/suspension/lot/fee/tax behavior、frozen universe containment、
Approval authorization、idempotent job、有界 retry/stale recovery、immutable result
reference、tamper rejection、deletion guard、Backend API integration 和 MCP translation。
