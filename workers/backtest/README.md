# Backtest Worker

Phase 12 提供 BYQ-owned deterministic worker boundary。Worker 获取一个
queued `backtest_*` job，只执行其 frozen signal snapshot；不执行 strategy
Python source、不访问 DSH state，也不接收 provider credentials。Durable
job/result artifact 仍归 Backend 所有；worker 经 Backend store layer
（ADR-0016 的 PostgreSQL `BYQ_DATABASE_URL`）读取 job，将完整 result 存为
immutable content-addressed object，domain row 只记录 reference/summary。

本地运行一个 job：

```text
BYQ_DATABASE_URL=postgresql+psycopg://byq_app:byq-app-dev@postgres:5432/byq_domain \
BYQ_BACKTEST_OBJECT_ROOT=/var/lib/byq/backtest-objects \
python worker.py --job-id backtest_<32-hex-digits>
```

HTTP `/v1/research/backtests/{job_id}/run` endpoint 是 keyless contract
fixture/operator control path。Production deployment 可从独立 worker process
或 queue adapter 运行同一 `BacktestWorker`。
