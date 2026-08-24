# Phase 46 acceptance evidence

Phase 46 implements ADR-0024's core-management workspace redesign without
changing the Stock Pool, Strategy, signal-producer or Backtest domain
contracts. The corresponding Community pages were inspected read-only and
classified in `docs/migration/COMMUNITY_MIGRATION_INVENTORY.md` before work.

## Product and boundary evidence

- Stock Pool, Strategy and Backtest use one responsive catalog/detail shell,
  shared hierarchy, real resource counts, refresh and primary creation actions.
- Stock Pool retains mutable catalog metadata, five immutable snapshot/detail
  projections, trusted-source rules and frozen downstream references. Creation
  uses the proven Product API flow in a bounded dialog.
- Strategy retains editable drafts, read-only immutable versions, validation,
  approval, version history, exact Backtest counts and signal lineage.
- Backtest retains comparison, isolated signal creation, immutable inputs,
  charts and all eight deep result tabs.
- A closed frontend mapping handles all five `workflow-card.v1` kinds. It maps
  only validated BYQ identifiers to fixed BYQ routes; cards are not commands or
  URLs. Pool/artifact/job deep links rehydrate owner-scoped current Product
  state and preserve the originating durable conversation ID.
- Mobile catalogs render cards instead of duplicate hidden desktop tables;
  long immutable identifiers are truncated visually without altering values.
- Browser traffic remained same-origin Gateway/Product routes. No Backend,
  MCP, DSH-internal schema, PostgreSQL, Redis, Tushare or Community endpoint
  crossed the browser boundary.

## Automated verification

- Frontend production build: passed.
- Frontend unit tests: 66 passed across 24 files.
- Mocked Chromium Product journeys: 13 passed, including exact pool,
  strategy-artifact and Backtest-job query selection.
- Closed Workflow-card navigation tests cover stock candidates, strategy
  drafts, optimization proposals and Backtest context while retaining the
  conversation ID.
- Complete local CI: recorded after the final code and documentation review.

## Chrome DevTools MCP review

- `stock-pool-desktop.png` / `stock-pool-mobile.png`: three persisted Product
  pools, selected current detail and the five snapshot/provenance surfaces.
- `strategy-desktop.png` / `strategy-mobile.png`: ten persisted strategy
  assets, immutable version detail, source, history and real Backtest count.
- `backtest-desktop.png` / `backtest-mobile.png`: two completed jobs, metrics,
  themed equity chart and all eight result tabs.
- A real durable conversation was created, an exact persisted StrategyVersion
  deep link was opened, and “返回投研对话” restored that exact conversation.
- Console review found no warnings or errors. Network review showed only
  same-origin `/api/auth/*`, `/api/product/*`, `/v1/agent/*` and normalized
  `/v1/workflows/*` Gateway routes.
- A diagnostic Lighthouse snapshot scored Best Practices 100 and Accessibility
  96. Its remaining contrast findings are pre-existing shell secondary text;
  the one Phase 46 summary-text finding was fixed. The complete contrast matrix
  and Lighthouse 100 target remain the explicit Phase 47 acceptance scope.
