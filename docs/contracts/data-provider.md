# Data Provider Contract — Phase 8

## Purpose

Define the BYQ-owned contract for retrieving A-share unadjusted daily bars
from a configured market-data provider. Provider-specific authentication,
response envelopes, and retry behavior remain behind the contract.

## Request semantics

The first operation is `daily`:

- `ts_code` is one uppercase six-digit symbol with `.SH`, `.SZ`, or `.BJ`.
- `trade_date` is an exact `YYYYMMDD` date.
- `start_date` and `end_date` are an inclusive `YYYYMMDD` range.
- An exact `trade_date` may be used without a symbol for one bounded market
  snapshot.
- A date range requires `ts_code`; open-ended ranges are rejected.
- `trade_date` cannot be combined with a date range.

The contract does not accept comma-separated symbols or arbitrary provider
parameters. This keeps request cost and market semantics explicit.

## Response

Each bar contains:

```text
ts_code, trade_date, open, high, low, close, pre_close,
change, pct_chg, vol, amount
```

The values retain the provider's documented units: prices and changes are in
RMB, `pct_chg` is a percentage, `vol` is in lots, and `amount` is in thousand
RMB. The daily contract is unadjusted; adjusted data is a separate future
contract.

Every response also contains `provenance`:

```text
provider, endpoint, request_fingerprint, retrieved_at,
cache_hit, row_count
```

`request_fingerprint` is a stable hash of normalized request parameters. It
never contains a provider token or raw response payload.

## Ownership and security

The Backend owns provider credentials and translates raw provider responses.
MCP exposes normalized BYQ data only. DSH reaches this capability only via
BeyondQuant MCP and never receives `TUSHARE_TOKEN`, raw Tushare envelopes, or
provider-specific error details.
