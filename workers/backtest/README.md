# Backtest Worker

Phase 12 provides a BYQ-owned deterministic worker boundary. The worker takes
one queued `backtest_*` job and executes only its frozen signal snapshot. It
does not execute strategy Python source, access DSH state, or receive provider
credentials. The durable job and result artifact remain Backend-owned; the
worker reads the job through the Backend store layer (PostgreSQL via
`BYQ_DATABASE_URL`, ADR-0016), stores the full result as an immutable,
content-addressed object, and records only its reference and summary in the
domain row.

Run one job locally with:

```text
BYQ_DATABASE_URL=postgresql+psycopg://byq_app:byq-app-dev@postgres:5432/byq_domain \
BYQ_BACKTEST_OBJECT_ROOT=/var/lib/byq/backtest-objects \
python worker.py --job-id backtest_<32-hex-digits>
```

The HTTP `/v1/research/backtests/{job_id}/run` endpoint is a keyless contract
fixture and operator control path. Production deployments may run the same
`BacktestWorker` from a separate worker process or queue adapter.
