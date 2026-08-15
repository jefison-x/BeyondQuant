# ADR-0005: Phase 8 Data Provider Boundary and Tushare Adapter

- Status: Accepted
- Date: 2026-08-15
- Decision scope: Phase 8 Data Plane / Quant Domain provider contract
- Supersedes: the Phase 5 data-worker placeholder

## Context

Phase 8 introduces the first BYQ-owned market-data provider. The provider
must remain a Data/Domain capability, while Product DSH can reach it only
through the BeyondQuant MCP boundary. Tushare credentials must not enter DSH,
MCP, WorkflowTrace, frontend responses, or application logs.

The first contract is intentionally limited to Tushare's A-share unadjusted
daily endpoint. The contract needs explicit symbol/date semantics, bounded
request cost, retries for transport/rate-limit failures, a local cache policy,
and provenance metadata before later factors or backtests depend on it.

## Decision

1. BYQ owns a framework-neutral daily-bar contract in the Backend Domain/Data
   boundary. It accepts one canonical A-share symbol (`NNNNNN.SH`,
   `NNNNNN.SZ`, or `NNNNNN.BJ`) and either one `trade_date` or a bounded date
   range. A full date-range request must name a symbol; an unscoped request is
   allowed only for one exact trade date.
2. The Backend owns the Tushare adapter and receives `TUSHARE_TOKEN` only as
   a Backend environment secret. The token is sent only to the official
   Tushare API request and is never returned in errors, provenance, logs, MCP
   payloads, or DSH configuration.
3. The adapter uses the official JSON POST endpoint and an explicit stable
   field list for the Phase 8 daily-bar contract. Raw Tushare envelopes are
   translated into BYQ records before crossing the Backend API.
4. Backend exposes the normalized contract at its internal data endpoint.
   BeyondQuant MCP exposes `byq_market_daily` as the only Agent-to-Domain
   capability for this data. DSH never receives direct provider credentials or
   raw provider response schemas.
5. The adapter uses bounded exponential backoff for HTTP 429/5xx transport
   failures and a bounded in-memory TTL cache keyed by canonical request
   parameters. Errors are not cached and the cache is process-local; durable
   market-data storage is deferred to a later Data Worker decision.
6. Every successful response includes BYQ provenance: provider, endpoint,
   normalized request fingerprint, retrieval time, cache-hit state, and row
   count. The fingerprint is a hash of provider request parameters and never
   includes the token.

## Consequences

- Keyless CI can exercise validation, translation, retry, cache, and MCP
  contracts with redacted fixtures.
- A live integration check requires operator-provided `TUSHARE_TOKEN` and may
  still fail when the account lacks the Tushare endpoint permission or points.
- The first contract deliberately does not provide arbitrary Tushare query
  passthrough, factor data, adjusted bars, trading-calendar semantics, or
  agent-controlled provider configuration.
- A later durable Data Worker may replace the Backend adapter while retaining
  the BYQ contract, provenance shape, and MCP capability.

## Rejected alternatives

- Passing `TUSHARE_TOKEN` through Gateway or Runtime Adapter would violate the
  Product/Agent secret boundary.
- Letting DSH call Tushare directly would bypass BeyondQuant MCP and expose a
  provider schema rather than a BYQ domain contract.
- Adding the `tushare` SDK as a new runtime dependency is unnecessary for the
  first contract; the documented JSON POST API is sufficient and keeps the
  adapter's transport and retry behavior explicit.
- Allowing arbitrary symbols, date ranges, or raw endpoint parameters would
  make request cost and A-share semantics implicit and unbounded.
