# Daily Market Synchronization

Phase 54 runs daily automation in the trusted `data-worker` Compose service.
The schedule is disabled by default and can be enabled by an administrator in
Data Center → 行情同步 → 每日自动同步.

## Normal operation

- Default schedule: 18:30 Asia/Shanghai.
- Default catch-up: the last 7 calendar days, bounded to 30.
- Each cycle refreshes the SSE trading calendar and creates one job per missing
  open session.
- Each job requests the complete Tushare stock `daily` snapshot for that exact
  date and imports it with `KEEP_NEW`.
- When enabled, the atomic `L/P/D` stock catalogue is refreshed before newly
  scheduled daily jobs are processed.

The Data Center should show a worker heartbeat less than two minutes old. A
completed session displays its provider row count and content hash.

## Recovery

Provider and credential failures remain secret-free. Session jobs retry at
bounded intervals and become `failed` after four attempts. Expired running
leases are returned to the queue when the worker starts. After correcting the
source problem, use “立即检查并同步”; a run-now command resets failed due-session
jobs without performing provider work in the HTTP request.

If the worker is unhealthy, inspect only the `data-worker` service logs and
Compose health/dependency state. Do not expose the database, credential
envelope, raw Tushare response, or provider access to the browser, DSH, MCP,
signal sandbox or backtest worker.

## Completeness meaning

`provider_snapshot_complete` proves that a non-empty exact-date provider
snapshot was normalized and fully imported. It does not prove that every
security was tradable on that date. Phase 55 adds lifecycle/suspension-aware
readiness for signal and backtest execution.
