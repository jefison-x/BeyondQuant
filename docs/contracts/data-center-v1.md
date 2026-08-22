# Data Center v1 Contract

Phase 39 implements the Accepted ADR-0019 Tushare boundary through the
browser-facing Product API. The browser never calls Backend, PostgreSQL, or
Tushare directly.

## Source configuration

- The only provider key is `tushare`; no browser-provided URL or provider name
  is accepted.
- A system credential is admin-only, write-only, encrypted by the shared
  ADR-0019 store, optimistic-versioned, masked on reads, and auditable.
- One non-revoked Tushare system credential is allowed through the Product
  workflow. If storage ever contains multiple active credentials, runtime
  resolution fails closed rather than selecting one implicitly.
- An active database credential takes precedence over the explicit
  `TUSHARE_TOKEN` bootstrap fallback. Secret and envelope fields never enter a
  Product response, sync row, audit detail, error, or WorkflowTrace.

## Connection test

The test accepts one canonical A-share symbol and one `YYYYMMDD` trade date.
It executes the BYQ `DailyRequest` through the Backend-owned Tushare adapter.
The response contains only provider/endpoint, credential source metadata,
row count, bounded latency, and check time. An empty successful provider
result is a valid connection; authorization and transport failures use stable,
secret-free errors.

## Sync jobs

- A request contains 1–20 unique canonical symbols, a `range` or
  `incremental` mode, an inclusive date range of at most 366 natural days, and
  an idempotency key.
- Jobs persist as `queued → running → completed|partial|failed`; progress and
  per-symbol normalized results remain readable after page refresh.
- Provider rows must match the requested symbol, have unique symbol/date keys,
  complete OHLC values, and valid high/low relationships before import.
- Imports use `MarketDataStore` with `KEEP_NEW`; a refresh never overwrites an
  existing authoritative BYQ row by last-write-wins.
- Tushare daily units are recorded explicitly as unadjusted stock bars,
  `lots`, and `thousand_cny`, together with BYQ request provenance.

## Coverage audit

Coverage is an audit of persisted observations: total rows/symbols/date bounds,
provider/asset groups, per-symbol bounds, non-Tushare source issues, and OHLC
relationship issues. It sets `completeness_claimed=false`; without a complete
trading-calendar/lifecycle proof, a date span is not presented as full
historical coverage.
