# Factor Research Contract

Phase 10 makes the factor input boundary a BYQ domain contract.  A factor
request contains normalized security, trading-session, lifecycle-status,
daily-bar, point-in-time universe, and provider provenance snapshots.  The
factor service does not accept provider-specific frames or execute arbitrary
source code.

## Required invariants

- Symbols are canonical `NNNNNN.SH`, `NNNNNN.SZ`, or `NNNNNN.BJ`. A bare
  six-digit code is accepted only with an explicit exchange; BYQ never guesses
  an exchange from a code prefix.
- Security listing and delisting dates define the valid lifecycle. A bar before
  listing or after delisting is rejected.
- Sessions are explicit and sorted by `trade_date`. Bars on a non-trading
  session are rejected; factor lags use session positions, not calendar-day
  subtraction.
- There is at most one bar for `(symbol, trade_date)`. Bars are normalized to a
  stable symbol/date order, and finite positive OHLC values must satisfy the
  OHLC envelope.
- A missing bar in an active lifecycle is an input error. A date before listing,
  after delisting, or explicitly suspended is classified separately and is not
  silently treated as a data gap.
- The latest universe snapshot visible on or before `as_of_date` is selected.
  Source announcement/effective dates after `as_of_date`, and future bars,
  statuses, sessions, or snapshots, are rejected to prevent look-ahead.
- The normalized input snapshot is content-addressed with SHA-256. Retrieval
  time is provenance metadata and is not part of the deterministic input ID.
- Results are bounded, deterministic, and persisted as a Phase 9 Artifact with
  a `factor_input` lineage reference. Artifact idempotency is supplied by the
  existing BYQ research store.

## Initial built-in factors

`daily_return` and `momentum` are deterministic close-to-close factors. Both
use only bars at or before `as_of_date`; `momentum` uses an explicit positive
session lookback. Results include the BYQ engine/algorithm metadata and a
deterministic count/mean/min/max evaluation summary. Arbitrary code execution
is outside this contract.

## Endpoint

`POST /v1/research/factors/compute` validates the input, returns the input
manifest summary and coverage classification, computes the result, and stores
the result as a `factor_result` Artifact. The corresponding MCP tool is
`byq_factor_compute`; Agent-to-Domain calls still cross the BeyondQuant MCP
boundary.
