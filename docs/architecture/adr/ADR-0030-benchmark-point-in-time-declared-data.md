# ADR-0030: Benchmark, Point-in-Time Universe and Declared Research Data

- Status: Accepted
- Date: 2026-08-25
- Accepted: 2026-08-25
- Decision scope: Phase 57 benchmark, historical index membership and optional
  valuation/fundamental research inputs
- Related: ADR-0005, ADR-0013, ADR-0017, ADR-0023, ADR-0027, ADR-0028, ADR-0029

## Context

Relative performance needs a benchmark frozen with the backtest. Historical
index strategies need membership as it was known on each session, not today's
constituents projected backward. Valuation and reported financial indicators
also have different visibility clocks: daily valuation belongs to an exact
market session, while a financial period is unavailable before its public
announcement.

Tushare provides separate `index_daily`, `index_weight`, `daily_basic`, and
`fina_indicator` contracts. The read-only Community implementation demonstrates
the domain need, but couples it to an SDK, ORM, mutable synchronization state,
threads and VectorBT-capable backtests. It also offers a much broader provider
surface than a strategy sandbox should be allowed to request.

## Decision

1. Strategy drafts and immutable versions may declare only four optional
   dependencies: one benchmark index, one index universe, a closed list of
   daily-basic fields, and a closed list of financial-indicator fields. Unknown
   datasets, fields and non-canonical index identities fail closed. The
   declaration is domain data and is frozen into the version and input identity.
2. The trusted Data Worker alone calls closed, bounded provider contracts for
   index daily bars, monthly index-weight snapshots, exact-session daily-basic
   snapshots, and per-symbol financial indicators. Provider credentials and raw
   responses never reach Product, signal or backtest workers.
3. PostgreSQL stores the four datasets separately with canonical symbols,
   provider provenance, content hashes and explicit completeness evidence.
   Valid-empty results are evidence only where the provider contract permits an
   empty snapshot; malformed, duplicate, truncated or unbounded results fail.
4. `market-data-requirement.v3` extends the existing immutable readiness
   requirement. The coordinator synchronizes only declared optional data before
   promotion and refuses to freeze a ready input while any required benchmark,
   daily-basic, membership or financial completeness evidence is absent.
5. Index membership for a session is the latest available provider snapshot
   whose snapshot date is no later than that session. The strategy's frozen
   Stock Pool remains the bounded symbol superset; the sandbox receives an
   `is_universe_member` column and rejects non-zero output for non-members.
   Current membership is never backfilled into earlier dates.
6. Daily-basic values are attached only to their exact session. Financial rows
   preserve both report period and announcement date and become research-visible
   on the calendar day after announcement. For each session, the latest visible
   announcement for the latest visible report period wins. Missing values remain
   explicit; they are not forward-invented from a later report.
7. The benchmark series and all declared research columns are frozen with the
   ready input and its hash. Native backtests compute benchmark return, excess
   return and a benchmark curve from that frozen series; benchmark prices are
   never tradeable portfolio bars.
8. Daily automation refreshes the core CSI 300 benchmark, its current monthly
   membership, and full-market daily-basic data alongside the existing session
   datasets. Custom declared indexes and financial history are filled on demand
   by bounded pre-run repair. Browser traffic remains Gateway/Product API only.
9. ETF and fund identities, arbitrary provider endpoints, BaoStock, AKShare and
   VectorBT remain outside this decision.

## Consequences

- Relative returns and historical index membership are reproducible from the
  same immutable input as the signal and backtest.
- Financial announcements cannot leak into sessions on or before their declared
  publication date under the conservative next-day rule.
- Optional data raises provider permission and repair costs only for strategies
  that declare it; missing authorization remains a visible readiness failure.
- Dataset or declaration revisions produce a new ready identity without
  rewriting existing signal snapshots or backtest results.

## Rejected alternatives

- Use today's index members for all history: introduces survivorship and
  look-ahead bias.
- Let strategy code request arbitrary Tushare endpoints: bypasses the Data Plane,
  weakens bounds and exposes credentials/provider coupling.
- Join financial rows by report period alone or announcement day: makes data
  visible before the conservative public-information boundary.
- Copy Community provider/ORM/VectorBT paths: violates current provider,
  persistence and execution boundaries.

## Acceptance evidence

Provider contract tests cover request bounds, closed fields, normalization and
fail-closed rows. PostgreSQL tests cover exact-session valuation, monthly
membership completeness, latest-snapshot selection, next-day announcement
visibility and immutable hashes. Sandbox and engine regressions cover
non-member output rejection and frozen benchmark/excess performance. Full
Compose and desktop/mobile Chrome review verify worker isolation, Product-only
browser requests and visible dataset/benchmark evidence.

## Rollback

Stop accepting new `data_requirements` and stop v3 optional-input repair. Existing
v1/v2 jobs and immutable snapshots retain their original semantics. Additive
benchmark/factor evidence may remain for audit and can be resynchronized later.
