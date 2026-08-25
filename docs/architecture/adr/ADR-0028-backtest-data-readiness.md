# ADR-0028: Lifecycle-Aware Backtest Data Readiness

- Status: Accepted
- Date: 2026-08-25
- Accepted: 2026-08-25
- Decision scope: Phase 55 signal/backtest input readiness and bounded repair
- Related: ADR-0005, ADR-0008, ADR-0013, ADR-0017, ADR-0023, ADR-0026, ADR-0027

## Context

Phase 54 advances durable unadjusted daily bars, but one bar per symbol does not
prove a signal or backtest window complete. A missing row can mean an ingestion
gap, a suspension, or a date outside the security lifecycle. Threshold-derived
limit prices are insufficient when the provider publishes exact daily limits.

Community coverage and repair flows provide useful domain evidence. Their ORM,
thread workers, provider registry, direct internal frontend calls and VectorBT
runtime are incompatible with BYQ and are not reused.

## Decision

1. Every signal request freezes a `market-data-requirement.v1` manifest:
   canonical symbols, date bounds, pool membership fingerprint, security-master
   snapshot, SSE calendar and required daily/status/price-limit datasets.
2. Coverage is evaluated per symbol and open session inside its frozen listing
   lifecycle. Pre-listing and post-delisting dates are not applicable. A
   suspended session is complete without a bar only when durable exact status
   proves it.
3. Tushare `suspend_d` and `stk_limit` are available only through closed,
   exact-date BYQ contracts. Fields, symbols, dates, uniqueness, row bounds and
   values are validated. Daily automation persists secret-free provenance.
4. Incomplete requests create one idempotent bounded repair. The Data Plane
   worker refreshes the calendar range and queues at most 250 full-market
   session jobs; provider work never occurs in HTTP, signal/backtest workers,
   browser, MCP or DSH.
5. Signal jobs begin in `waiting_for_data` and are not claimable. A provider-free
   coordinator promotes them only after constructing `ready_input_sha256`.
6. Immutable signal input freezes exact `pre_close`, suspension and limit fields
   plus requirement and ready identities. Backtests consume only the resulting
   validated snapshot and cannot run ahead of readiness.
7. Requirements are bounded to 2,000 symbols, 250 repair sessions and 50,000
   symbol-session cells. Missing evidence fails closed and stays visible.
8. Adjustment factors, corporate actions, benchmarks, point-in-time index
   membership, valuation and fundamentals remain outside Phase 55.

## Consequences

- Holidays and lifecycle dates do not generate false gaps.
- Suspensions cannot be inferred from missing prices.
- Exact limits replace percentage heuristics in newly frozen inputs.
- Existing raw execution prices stay unadjusted; Phase 56 owns adjustments.

## Rejected alternatives

- Provider access from signal/backtest workers violates immutable boundaries.
- Treating every absent bar as suspension conceals ingestion failures.
- Natural-day or current-lifecycle coverage creates false gaps.
- Copying Community code restores excluded runtime and frontend coupling.

## Acceptance evidence

Provider tests cover exact status/limit mappings. Database and API tests cover
lifecycle readiness, suspension proof, bounded repair, non-claimable waiting,
promotion and immutable identity. Compose and browser evidence prove worker
boundaries and visible automatic preparation.

## Rollback

Disable repair creation and waiting promotion. Existing completed snapshots and
backtests remain valid. Additive provenance remains and bars are not deleted.
