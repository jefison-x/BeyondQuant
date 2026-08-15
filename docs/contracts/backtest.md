# Backtest Job and Worker Contract — Phase 12

Phase 12 executes a frozen, BYQ-owned signal snapshot with the native
deterministic engine. It does not execute StrategyVersion Python source. The
strategy version and its approved `strategy_approval` artifact authorize the
attempt; the input manifest freezes the actual execution data.

## Submission

`POST /v1/research/backtests` and `byq_backtest_submit` require:

- a `validated` `strategy_version` artifact and a matching approved,
  `execution_authorized` `strategy_approval` artifact;
- a frozen universe with canonical symbols, `version_id`, and a membership
  SHA-256 matching the sorted symbol set;
- one deterministic OHLC bar per `(symbol, trade_date)` and a stable signal
  snapshot; and
- explicit execution rules or the BYQ defaults for capital, fees, lot size,
  position limit, slippage, A-share rules, and runtime bound.

The resulting `backtest-input-v1` manifest is content-addressed. It contains
the strategy/approval identities, universe, bars, signals, corporate actions,
execution rules, and native engine contract version. It excludes credentials,
mutable timestamps, prompts, Agent runtime state, and strategy source.

## Native execution rules

- Signals observed on a session execute at the next available session open.
- Orders are processed in symbol order, sells before buys.
- A-share mode enforces T+1 lots, limit-up/limit-down, suspension, lot size,
  cash, commission, sell-side stamp tax, and an active-position limit.
- Corporate actions are frozen in the input and apply share/cash adjustments
  before the ex-date orders.
- Every rejected order emits a stable reason code such as `t_plus_one`,
  `limit_up`, `limit_down`, `suspended`, `insufficient_capital`, or
  `max_positions`.

The result is deterministic and includes the equity curve, trades, blocked
trades, corporate-action events, summary metrics, engine contract version,
and the input manifest identity.

## Jobs and result objects

Jobs use the state machine:

```text
queued → running → completed
             ├──→ queued  (bounded retry)
             ├──→ failed
             └──→ cancelled
queued ─────────→ cancelled
```

The same task/idempotency key and request returns the original job. Reusing
the key with a different request is a conflict. A worker claims one queued job
and increments its bounded attempt count (1–3 attempts). Stale running jobs
are requeued after a worker restart. Business state remains Backend/
Domain-owned; the full result is an immutable object reference containing
namespace, object identity, media type, size, and SHA-256. The
`backtest_result` Artifact stores only the reference and bounded summary.

Object deletion requires matching owner scope and an authoritative live
reference set. Referenced, missing, or tampered objects fail closed.

The Phase 12 worker can run as a separate process using
`workers/backtest/worker.py`. The HTTP run operation is a keyless contract
fixture and operator control path, not a strategy-source execution shortcut.
