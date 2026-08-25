# Phase 57 Community feature checklist

The corresponding Community provider, index schema, universe/backtest logic and
frontend views were inspected read-only before implementation.

- [x] Benchmark identity and historical series are frozen with the run.
- [x] Relative/benchmark performance is visible in Backtest Product UI.
- [x] Historical index membership selects a snapshot no later than the session.
- [x] Non-members cannot emit active sandbox signals.
- [x] Daily valuation fields attach only to their exact market session.
- [x] Financial indicators preserve report and announcement identity.
- [x] Financial rows are invisible until the conservative next-day boundary.
- [x] Strategy optional datasets and fields use a closed validated declaration.
- [x] Daily automation covers the core benchmark/membership and valuation data.
- [x] Backtest pre-run repair fills only the immutable declared requirement.
- [x] Browser requests use Gateway/Product API only.
- [x] Desktop and mobile Chrome MCP review is clean.
- [x] Community SDK/ORM/cache/runtime code was not copied.
- [x] BaoStock, AKShare, VectorBT and ETF/fund scope remain excluded.
