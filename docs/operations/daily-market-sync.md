# Daily Market Synchronization

Phase 54 在 trusted `data-worker` Compose service 中运行 daily automation。
Schedule 默认 disabled，可由 administrator 在 Data Center → 行情同步 →
每日自动同步 中启用。

## 正常运行

- 默认 schedule：18:30 Asia/Shanghai。
- 默认 catch-up：最近 7 个 calendar days，上限 30。
- 每个 cycle 刷新 SSE trading calendar，并为每个缺失 open session 创建一个 job。
- 每个 job 请求该精确日期完整 Tushare stock `daily` snapshot，并以
  `KEEP_NEW` import。
- 启用时，先刷新 atomic `L/P/D` stock catalogue，再处理新排队 daily jobs。

Data Center 应显示不超过两分钟的 worker heartbeat。Completed session 显示
provider row count 和 content hash。

## Recovery

Provider/credential failures 保持 secret-free。Session jobs 以有界 interval
retry，四次 attempts 后转为 `failed`。Worker 启动时将 expired running leases
退回 queue。修复 source 后使用“立即检查并同步”；run-now command 重置 due
session 的 failed jobs，但 HTTP request 本身不执行 provider work。

Worker unhealthy 时，只检查 `data-worker` service logs 和 Compose
health/dependency state。不得向 browser、DSH、MCP、signal sandbox 或 backtest
worker 暴露 database、credential envelope、raw Tushare response/provider
access。

## Completeness 含义

`provider_snapshot_complete` 只证明一个非空 exact-date provider snapshot
已规范化并完整 import；不证明当日每个 security 都可交易。Phase 55 增加面向
signal/backtest execution 的 lifecycle/suspension-aware readiness。
