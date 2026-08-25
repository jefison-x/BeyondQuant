# Phase 57 acceptance evidence

Date: 2026-08-25

## Automated verification

- Architecture and complete PostgreSQL-backed Backend suites passed; the direct
  diagnostic run reported 155 passed and 1 environment-dependent skip.
- Frontend TypeScript/Vite build, 32 files / 79 tests, and the high-severity
  dependency audit passed.
- The forced full local pipeline rebuilt the isolated topology and passed all
  14 checks: Backend, Gateway, Runtime Adapter, MCP, frontend, 15 mocked UI E2E
  flows, full Compose smoke, 3 real Product API browser flows and the no-mock
  two-user golden journey.

## Point-in-time and benchmark proof

Provider tests prove bounded closed `index_daily`, `index_weight`, exact-date
`daily_basic` and per-symbol `fina_indicator` mappings, canonical identities,
finite fields, request fingerprints and fail-closed malformed rows.

PostgreSQL/coordinator tests prove exact-session valuation, monthly membership
completeness, latest-snapshot-at-or-before-session selection, next-calendar-day
financial announcement visibility and content-addressed ready inputs. Sandbox
tests reject non-zero signals outside point-in-time membership. Native engine
tests freeze a benchmark series and compute benchmark and excess return without
making the index tradeable.

## Chrome MCP review

Chrome MCP reviewed the real Product on desktop and a `390x844@3` mobile touch
viewport. Data Center's daily automation visibly lists daily valuation, CSI 300
benchmark/membership and strategy-declared financial indicators. Strategy shows
the closed declared-data JSON editor. Backtest shows Benchmark Return and Excess
Return alongside the equity curve.

The first desktop review found that a legacy result without a benchmark rendered
`null` as `0.00%`. The formatter was corrected and a rebuilt-container review
verified both benchmark metrics render `-` instead. Fresh pages produced no
console warning, error or issue. All observed requests were same-origin static,
`/api/auth/*` or `/api/product/*`; the browser did not access Backend, MCP, DSH,
PostgreSQL or Tushare directly.

## Boundary result

The trusted Data Worker alone accesses Tushare. Signal and backtest workers stay
provider-free, optional inputs are declaration-bounded, and immutable identities
cover benchmark, membership, valuation and visible financial rows. Community
remained read-only; no BaoStock, AKShare, VectorBT or ETF/fund compatibility path
was introduced. The product remains Beta and no release/tag/publication occurred.
