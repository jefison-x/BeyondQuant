# Backtest Worker

Phase 12 provides a BYQ-owned deterministic worker boundary. The worker takes
one queued `backtest_*` job and executes only its frozen signal snapshot. It
does not execute strategy Python source, access DSH state, receive provider
credentials, or connect to PostgreSQL. The durable job and result artifact
remain Backend-owned; the worker stores the full result as an immutable,
content-addressed object and records only its reference and summary in the
domain row.

Run one job locally with:

```text
BYQ_DOMAIN_DB_PATH=/var/lib/byq/domain/byq.sqlite3 \
BYQ_BACKTEST_OBJECT_ROOT=/var/lib/byq/backtest-objects \
python worker.py --job-id backtest_<32-hex-digits>
```

The HTTP `/v1/research/backtests/{job_id}/run` endpoint is a keyless contract
fixture and operator control path. Production deployments may run the same
`BacktestWorker` from a separate worker process or queue adapter.
