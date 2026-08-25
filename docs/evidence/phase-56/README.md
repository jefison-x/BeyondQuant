# Phase 56 acceptance evidence

Date: 2026-08-25

## Automated verification

- Architecture and complete PostgreSQL-backed Backend suites passed.
- Frontend TypeScript/Vite build, 32 files / 79 tests, and the high-severity
  dependency audit passed.
- Full isolated Compose topology, base smoke, MCP contracts, real Product API
  Playwright flows, and the no-mock two-user golden journey passed (10/10 local
  CI checks).
- The golden journey produced a frozen adjusted research input, immutable
  signal snapshot, and a completed raw-price backtest with one trade.

## Adjustment and action proof

Provider tests prove exact-date `adj_factor` and `dividend(ex_date=...)`
requests, strict field mapping, net/gross cash semantics, implemented-only
actions, canonical symbols, and fail-closed invalid or duplicate rows.

PostgreSQL and engine tests prove valid-empty action completeness, independent
raw bars and factors, a deterministic forward-adjusted research view and
identity, frozen actions, reporting-period-aware uniqueness, and distinct
ex-date entitlement, pay-date cash settlement, and share-listing settlement.
The sandbox accepts only its declared adjusted bar schema; the first golden
run caught extra metadata columns and the corrected closed schema passed the
complete suite.

## Chrome MCP review

Chrome MCP reviewed the real Data Center on desktop and a `390x844@3` mobile
touch viewport. The daily automation form visibly lists “复权因子” and
“实施公司行动”. The mobile Backtest company-action tab visibly exposes ex,
payment and share-listing dates, old/new quantities, cash and settlement state.

Fresh authenticated pages produced no console warning, error, or issue. All
observed browser requests were same-origin `/api/auth/*` or `/api/product/*`;
the browser did not access Backend, MCP, DSH, PostgreSQL, or Tushare directly.

## Boundary result

The trusted Data Worker alone accesses Tushare. Signal and backtest workers are
provider-free. Research signals use adjusted prices while executions retain
raw prices; immutable identities cover the research view and corporate
actions. No Community repository/database was modified and no BaoStock,
AKShare, or VectorBT dependency/path was introduced.
