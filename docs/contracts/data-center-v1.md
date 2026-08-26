# Data Center v1 Contract（daily-bar compatibility subset）

Phase 39 通过 browser-facing Product API 实现 Accepted ADR-0019 Tushare boundary。Browser 永不直接调用 Backend、PostgreSQL 或 Tushare。

Phase 53 按 ADR-0026 将 Product projection 扩展为 `data-center.v2`。下述原始 daily-bar semantics 保持兼容；security master、catalogue selection、response bounds 和真实 incremental behavior 以 [`security-master-v1.md`](security-master-v1.md) 为准。

Phase 54 按 ADR-0027 扩展为 `data-center.v3`，加入 `market-sync-automation.v1` member，同时保留所有 v1/v2 manual operations。

## Source configuration

- 唯一 provider key 是 `tushare`；不接受 browser 提供的 URL 或 provider name。
- System credential 仅 admin 可用、write-only，由共享 ADR-0019 store 加密，使用 optimistic version，读取时 masked，并可审计。
- Product workflow 只允许一个 non-revoked Tushare system credential。若 storage 中存在多个 active credentials，runtime resolution fail closed，不隐式选择。
- Active database credential 优先于显式 `TUSHARE_TOKEN` bootstrap fallback。Secret/envelope fields 永不进入 Product response、sync row、audit detail、error 或 WorkflowTrace。

## Connection test

Test 接受一个 canonical A-share symbol 和一个 `YYYYMMDD` trade date，通过 Backend-owned Tushare adapter 执行 BYQ `DailyRequest`。Response 只含 provider/endpoint、credential source metadata、row count、有界 latency 和 check time。空的成功 provider result 也是有效连接；authorization/transport failures 使用稳定且不含 secret 的 errors。

## Sync jobs

- Legacy explicit request 包含 1–500 个唯一 canonical symbols。Catalogue 和 Stock Pool orchestration 最多冻结 6,000 symbols。每个 request 包含 `range` 或 `incremental` mode、最多 366 个自然日的闭区间，以及 idempotency key。
- Jobs 持久化为 `queued → running → completed|partial|failed`；刷新页面后仍可读取 progress 和 per-symbol normalized results。
- Provider rows 必须匹配 requested symbol，具有唯一 symbol/date keys、完整 OHLC values 和有效 high/low relationships，之后方可 import。
- Import 使用 `MarketDataStore` 与 `KEEP_NEW`；refresh 不以 last-write-wins 覆盖现有 authoritative BYQ row。
- Tushare daily units 显式记录为 unadjusted stock bars、`lots` 和 `thousand_cny`，并带 BYQ request provenance。

## Coverage audit

Coverage 审计已持久化 observations：total rows/symbols/date bounds、provider/asset groups、per-symbol bounds、non-Tushare source issues 和 OHLC relationship issues。它设置 `completeness_claimed=false`；没有完整 trading-calendar/lifecycle proof 时，不把 date span 表述为完整历史覆盖。

## Daily automation

- Configuration 仅 admin 可用、versioned 且 idempotent：`enabled`、`HH:MM` schedule、固定 `Asia/Shanghai` timezone、1–30 catch-up calendar days，以及可选 atomic security-master refresh。
- Browser 只创建 Product API configuration 或 run-now commands；trusted `data-worker` 刷新 calendar 并执行 provider requests。
- 每个 open session 最多一个 durable job。Jobs leased 后经 `queued → running → completed|failed` 转换，最多四次 attempts，并有 bounded backoff/recovery。
- 每个 session 使用一个 exact-date、unscoped `daily` request，以 `KEEP_NEW` 导入完整 normalized response；`pre_close` 与 raw unadjusted OHLCV/amount 一同保留。
- `provider_snapshot_complete` 表示一个非空 exact-date provider snapshot 通过 normalization 且完整导入；不表示每个 catalogue member 都交易，也不取代 Phase 55 的 lifecycle-aware readiness assessment。
- Public status 包含 worker heartbeat/health、latest calendar open date、latest complete session、next configured run 和有界 recent job/command projections；不暴露 credential 或 raw provider envelope。
