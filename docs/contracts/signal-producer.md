# Signal Producer Contract

Status: Phase 40 implementation of Accepted ADR-0023.

## Product request

`POST /api/product/signal-producer/jobs` accepts an owner-scoped validated
`strategy_version_artifact_id`, immutable `stock_pool_snapshot_id`, inclusive
`start_date`/`end_date`, finite JSON parameters, ADR-0017 execution settings,
an explicit lot-aligned `order_quantity`, trace identity and idempotency key.
The browser sends this request only to Gateway Product API.

Backend verifies task, strategy and pool ownership, rejects inactive pools and
unsupported `generate_target_weights` versions, and reads the complete bounded
window from canonical `market_daily_bars`. Missing pool-member coverage fails
before the job is queued. No provider fallback occurs.

## Durable state

Jobs transition `queued → running → completed|failed`. Product responses omit
strategy source and frozen bars; they expose only profile/runtime-lock identity,
symbol/bar counts, stable error fields and the completed
`result_artifact_id`. `(owner_principal, idempotency_key)` is unique and reuse
with different frozen input is a conflict.

## Execution protocol

The trusted coordinator claims PostgreSQL jobs and calls the credential-free
`signal-sandbox` over the internal-only sandbox network. The sandbox accepts
only `byq-signal-sandbox-request-v1` with execution profile
`byq-signal-python-v1`. Every request starts a fresh child with fixed runtime
lock `python-3.13/pandas-2.3.3/numpy-2.3.3`, deterministic thread/hash settings,
resource limits and a sanitized environment.

`CustomStrategy.generate_signals(data, parameters)` receives canonical bars as
a Pandas DataFrame indexed by `(symbol, trade_date)`. It must return a mapping
of canonical symbols to date-indexed Pandas Series containing only `-1`, `0` or
`1`. Unknown or duplicate symbols/dates, non-finite values, oversized output,
timeouts and unsupported imports fail closed with stable codes.

The coordinator drops hold rows, applies the explicit order quantity, and
revalidates all output through ADR-0017 `normalize_signal_snapshot` before
creating or reusing a validated, content-addressed `signal_snapshot` Artifact.
Producer completion neither approves nor starts a backtest.

## Isolation guarantees

The sandbox has no Product network, PostgreSQL URL, Tushare/model/MCP/DSH
credential, Docker socket, repository mount or application source. Its
filesystem is read-only except bounded `/tmp`; it is non-root with all Linux
capabilities dropped, `no-new-privileges`, and bounded PID, memory, CPU and
wall time. The coordinator has PostgreSQL access but never calls `exec()` on
strategy source.
