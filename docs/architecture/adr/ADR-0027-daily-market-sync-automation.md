# ADR-0027：Durable Daily Market Synchronization Automation

- Status: Accepted
- Date: 2026-08-25
- Accepted: 2026-08-25
- Decision scope: Phase 54 trading calendar、daily full-market synchronization 和 trusted
  Data Plane worker
- Related: ADR-0005、ADR-0008、ADR-0013、ADR-0015、ADR-0023、ADR-0026

## 背景

Phase 53 可 bootstrap stock catalogue 并运行 durable daily-bar job，但 full-market path 对
每个 symbol 调一次 Tushare，且要求 administrator 选择 calendar date。因此 Beta database
可能有完整 security master，却只有少量 bar；也没有 durable process 在每次 close 后推进
market cache。

Read-only Community scheduler 证明了 useful operational invariant：configurable Asia/
Shanghai schedule time、每日期一个 durable job、catch-up、claim lease、restart recovery
和 bounded retry。其 ORM、in-process thread、provider registry、broad endpoint passthrough、
cache 和 frontend-to-internal API coupling 不兼容 BYQ，不复用。

## 决策

1. BYQ 增加 provider-neutral `trading-calendar.v1` Contract，只由 closed Tushare
   `trade_cal` mapping 支撑。SSE 是本 Phase canonical A-share session calendar。Date、
   exchange、open state、previous open date、bound、uniqueness 和 provenance 在 persistence
   前验证。
2. Trusted、independently deployable `data-worker` 持有 schedule evaluation、provider
   access 和 daily ingestion。它拥有 PostgreSQL 和 encrypted Tushare credential access，
   但无 DSH、MCP、model、Browser、repository-write 或 Docker authority。
3. Schedule configuration 由 PostgreSQL 持有，versioned、idempotent。Timezone 固定
   `Asia/Shanghai`，default time 18:30；administrator enable 前 automatic sync disabled。
   Catch-up 限制 1-30 calendar day。
4. 每个 due open session 恰有一个 durable job。Worker 以 `FOR UPDATE SKIP LOCKED`
   claim、增加有界 attempt、持有 lease、recover stale work，并对 provider failure 使用有界
   exponential backoff retry。
5. Nightly price 使用一个 unscoped exact-date Tushare `daily` request，而非每 security
   一个 call。Full response 经过 normalization、duplicate/OHLC/value validation，并依据
   ADR-0013 `KEEP_NEW` atomic import。Raw `pre_close` 与 unadjusted execution price 保留。
6. Successful non-empty exact-date provider response 生成 content-addressed
   `provider_snapshot_complete` record。这表示 mapped provider snapshot 已完整 retrieve/
   import，不表示每个 catalogue security 当日均交易。
7. Automatic security-master refresh 可选且 default enabled；在新 scheduled daily job 处理
   前复用 ADR-0026 atomic `L/P/D` snapshot Contract。
8. Browser request 保持 same-origin Gateway/Product API。Administrator 可 read status、
   update configuration 和 enqueue idempotent run-now command；HTTP request 本身不执行
   provider sync。
9. Phase 54 不增加 suspension、exact price limit、adjustment factor、corporate action、
   benchmark、index membership、valuation 或 fundamental Contract；这些由独立 Phase gate。

## 后果

- 正常 daily operation 每 scheduling cycle 一个 calendar request、每 open session 一个
  market-wide daily request，而不是数千 symbol request。
- Restart/concurrent worker 不重复 session job；immutable dataset hash 和 `KEEP_NEW` 保持
  reproducibility。
- Data Center 可区分 latest calendar session、latest complete market snapshot、worker
  health 和 failed/retrying work。
- Historical per-symbol job 继续用于有界 manual backfill。
- 后续 readiness gate 可使用 durable calendar/session-completeness evidence，而不给 signal/
  Backtest worker provider access。

## 拒绝的替代方案

- Backend 内 scheduler thread：耦合 request serving 与 long-running provider work，削弱
  restart/lease behavior。
- Browser timer 或 DSH scheduling：均不持有 Data Plane credential/durable sync。
- Per-symbol nightly incremental request：对 A-share catalogue 无界且浪费 provider quota。
- 用 natural-day `today` 表示 completeness：weekend、holiday、provider delay 使其错误。
- 复制 Community scheduler/provider stack：违反 migration 和 Product API boundary。

## Acceptance evidence

Provider Contract test 覆盖 calendar bound、normalization、duplicate rejection、secret-free
provenance。PostgreSQL test 覆盖 optimistic/idempotent configuration、open-session
scheduling、once-per-date restart behavior、full-market normalization/import、completeness
record 和 Product API RBAC。Compose/browser evidence 必须显示健康 independent worker、
desktop/mobile configuration card、same-origin Product request 和无 console error。

## 回滚

Disable schedule 并移除 `data-worker` service。Manual Phase 53 job 继续工作。Additive
calendar/job/configuration/completeness table 保留 audit evidence；market row 不删除或覆盖。
