# ADR-0005：Phase 8 Data Provider Boundary 与 Tushare Adapter

- Status: Accepted
- Date: 2026-08-15
- Decision scope: Phase 8 Data Plane / Quant Domain provider contract
- Supersedes: Phase 5 data-worker placeholder

## 背景

Phase 8 引入第一个 BYQ 自有 market-data provider。Provider 必须保持为 Data/Domain
capability，而 Product DSH 只能通过 BeyondQuant MCP 边界访问它。Tushare credential
不得进入 DSH、MCP、WorkflowTrace、frontend response 或 application log。

首个 Contract 有意限于 Tushare A-share unadjusted daily endpoint。在后续 Factor 或
Backtest 依赖它之前，Contract 需要明确的 symbol/date semantics、有界 request cost、
针对 transport/rate-limit failure 的 retry、local cache policy 和 provenance metadata。

## 决策

1. BYQ 在 Backend Domain/Data boundary 持有 framework-neutral daily-bar Contract。
   它接受一个规范 A-share symbol（`NNNNNN.SH`、`NNNNNN.SZ` 或 `NNNNNN.BJ`），
   以及一个 `trade_date` 或有界 date range。完整 date-range request 必须指定 symbol；
   未限定 symbol 的 request 只允许查询一个准确 trade date。
2. Backend 持有 Tushare Adapter，并只以 Backend environment secret 接收
   `TUSHARE_TOKEN`。token 只发送给 official Tushare API request，绝不出现在 error、
   provenance、log、MCP payload 或 DSH configuration 中。
3. Adapter 使用 official JSON POST endpoint 和 Phase 8 daily-bar Contract 的明确稳定
   field list。Raw Tushare envelope 在越过 Backend API 前转换为 BYQ record。
4. Backend 在内部 data endpoint 暴露 normalized Contract。BeyondQuant MCP 仅通过
   `byq_market_daily` 向 Agent-to-Domain 暴露该数据。DSH 不获得直接 provider
   credential 或 raw provider response schema。
5. Adapter 对 HTTP 429/5xx transport failure 使用有界 exponential backoff，并使用按
   canonical request parameter 建 key 的有界 in-memory TTL cache。Error 不缓存，cache
   仅限 process-local；持久化 market-data storage 延后到后续 Data Worker 决策。
6. 每次成功 response 都包含 BYQ provenance：provider、endpoint、normalized request
   fingerprint、retrieval time、cache-hit state 和 row count。fingerprint 是 provider
   request parameter 的 hash，绝不包含 token。

## 后果

- 无密钥 CI 可以使用 redacted fixture 测试 validation、translation、retry、cache 和
  MCP Contract。
- live integration check 需要 operator 提供 `TUSHARE_TOKEN`，且在账号缺少 Tushare
  endpoint permission 或积分时仍可能失败。
- 首个 Contract 明确不提供 arbitrary Tushare query passthrough、factor data、
  adjusted bar、trading-calendar semantics 或 agent-controlled provider configuration。
- 后续持久化 Data Worker 可以替换 Backend Adapter，但必须保留 BYQ Contract、
  provenance shape 和 MCP capability。

## 拒绝的替代方案

- 通过 Gateway 或 Runtime Adapter 传递 `TUSHARE_TOKEN` 会违反 Product/Agent secret
  boundary。
- 让 DSH 直接调用 Tushare 会绕过 BeyondQuant MCP，并暴露 provider schema 而不是
  BYQ domain Contract。
- 首个 Contract 无需增加 `tushare` SDK runtime dependency；已文档化的 JSON POST API
  已足够，并能使 Adapter transport 和 retry behavior 保持明确。
- 允许任意 symbol、date range 或 raw endpoint parameter，会使 request cost 和 A-share
  semantics 隐含且无界。
