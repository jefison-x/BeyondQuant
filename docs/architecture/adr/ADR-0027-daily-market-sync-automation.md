# ADR-0027: Durable Daily Market Synchronization Automation

- Status: Accepted
- Date: 2026-08-25
- Accepted: 2026-08-25
- Decision scope: Phase 54 trading calendar, daily full-market synchronization,
  and trusted Data Plane worker
- Related: ADR-0005, ADR-0008, ADR-0013, ADR-0015, ADR-0023, ADR-0026

## Context

Phase 53 can bootstrap the stock catalogue and run durable daily-bar jobs, but
its full-market path calls Tushare once per symbol and requires an administrator
to choose calendar dates. The Beta database can therefore contain a complete
security master while holding only a few bars, and no durable process advances
the market cache after each close.

The read-only Community scheduler demonstrates useful operational invariants:
configurable Asia/Shanghai schedule time, one durable job per date, catch-up,
claim leases, restart recovery and bounded retries. Its ORM, in-process threads,
provider registry, broad endpoint passthrough, cache and frontend-to-internal
API coupling are incompatible with BYQ and are not reused.

## Decision

1. BYQ adds a provider-neutral `trading-calendar.v1` contract backed only by
   the closed Tushare `trade_cal` mapping. SSE is the canonical A-share session
   calendar for this phase. Dates, exchange, open state, previous open date,
   bounds, uniqueness and provenance are validated before persistence.
2. A trusted, independently deployable `data-worker` owns schedule evaluation,
   provider access and daily ingestion. It has PostgreSQL and encrypted Tushare
   credential access, but no DSH, MCP, model, browser, repository-write or
   Docker authority.
3. Schedule configuration is PostgreSQL-owned, versioned and idempotent. The
   timezone is fixed to `Asia/Shanghai`; the default time is 18:30; automatic
   synchronization is disabled until an administrator enables it. Catch-up is
   bounded to 1-30 calendar days.
4. Each due open session has one durable job. Workers claim with
   `FOR UPDATE SKIP LOCKED`, increment bounded attempts, hold a lease, recover
   stale work and retry provider failures with bounded exponential backoff.
5. Nightly prices use one unscoped exact-date Tushare `daily` request, not one
   call per security. The full response is normalized, duplicate/OHLC/value
   validated and atomically imported under ADR-0013 `KEEP_NEW`. Raw
   `pre_close` is retained with unadjusted execution prices.
6. A successful non-empty exact-date provider response creates a
   content-addressed `provider_snapshot_complete` record. This asserts that the
   mapped provider snapshot was fully retrieved and imported; it does not claim
   that every catalogue security traded that day.
7. Automatic security-master refresh is optional and enabled by default. It
   reuses ADR-0026's atomic `L/P/D` snapshot contract before newly scheduled
   daily jobs are processed.
8. Browser requests remain same-origin Gateway/Product API. Administrators may
   read status, update configuration and enqueue an idempotent run-now command;
   the HTTP request never performs provider synchronization itself.
9. Phase 54 does not add suspension, exact price-limit, adjustment-factor,
   corporate-action, benchmark, index-membership, valuation or fundamental
   contracts. Those remain separately gated phases.

## Consequences

- Normal daily operation costs one calendar request per scheduling cycle and
  one market-wide daily request per open session, rather than thousands of
  symbol requests.
- Restarts and concurrent workers do not duplicate a session job; immutable
  dataset hashes and `KEEP_NEW` retain reproducibility.
- The Data Center can distinguish latest calendar session, latest complete
  market snapshot, worker health and failed/retrying work.
- Historical per-symbol jobs remain available for bounded manual backfill.
- A later readiness gate can use the durable calendar and session-completeness
  evidence without granting provider access to signal or backtest workers.

## Rejected alternatives

- A scheduler thread inside Backend: couples request serving to long-running
  provider work and weakens restart/lease behavior.
- Browser timers or DSH scheduling: neither owns Data Plane credentials or
  durable domain synchronization.
- Per-symbol nightly incremental requests: unbounded for the A-share catalogue
  and unnecessarily consumes provider quota.
- Natural-day `today` as completeness: weekends, holidays and provider delay
  make it false.
- Copying the Community scheduler/provider stack: violates the migration and
  Product API boundaries.

## Acceptance evidence

Provider contract tests cover calendar bounds, normalization, duplicate
rejection and secret-free provenance. PostgreSQL tests cover optimistic and
idempotent configuration, open-session scheduling, once-per-date restart
behavior, full-market normalization/import, completeness records and Product
API RBAC. Compose and browser evidence must show a healthy independent worker,
the configuration card on desktop/mobile, same-origin Product requests and no
console errors.

## Rollback

Disable the schedule and remove the `data-worker` service. Manual Phase 53 jobs
continue to work. Additive calendar, job, configuration and completeness tables
remain audit evidence; market rows are not deleted or overwritten.
