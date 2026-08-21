# Phase 35 BYQ Paper Trading browser acceptance

Captured on 2026-08-22 with Chrome DevTools MCP against an isolated Compose
stack built from the Phase 35 worktree. The browser used durable `ci-admin`
identity and the same-origin Gateway at `http://127.0.0.1:32814`.

## Evidence index

- `01-desktop-overview.png`: persisted account summary, frozen Stock Pool
  snapshot, order form, and six-tab workspace.
- `02-desktop-positions.png`: distinct total, T+1 sellable, and locked
  quantities after immutable manual settlement.
- `03-desktop-order-audit.png`: immediate filled result, risk evaluation,
  frozen snapshot, decision provenance, and immutable order events.
- `04-desktop-risk-migration.png`: persisted maximum-notional/kill-switch
  controls, explicit snapshot rebinding rule, and BYQ bundle transfer actions.
- `05-mobile-overview.png`: 390x844 responsive account, order, metric, tab,
  and bottom-navigation layout.

## Real Product flow

The retained acceptance account was produced by the real-browser smoke: create
a Stock Pool and account, submit a buy, inspect T+1 position state, settle with
a complete manual mark, inspect order audit, save risk controls, export a
digested asset bundle, and import it as a new owner-bound account ID. Both the
Stock Pool and Paper Trading real Product API tests passed.

The independent Chrome MCP review found no console messages. All 23 captured
XHR/fetch requests were same-origin. Authentication used `/api/auth/*`; every
domain request used `/api/product/*`, including accounts, pools, positions,
orders, fills, ledger, snapshots, controls, and order detail. No browser call
targeted Backend, MCP, DSH, PostgreSQL, Redis, or a market-data provider.

## Acceptance observations

- Six tabs render persisted projections: overview, positions, orders/fills,
  ledger, settlement snapshots, and risk/migration.
- Buy cash moves in the correct negative direction; settlement changes market
  value/equity without manufacturing cash flow.
- T+1 locked quantity is promoted only by monotonic settlement, and a settled
  date is immutable/idempotent.
- Risk controls are versioned and evaluated before normal order rules.
- Export/import survives an actual HTTP/JSON/file round trip; manifest and
  section digests are verified, imported references receive new IDs, and
  ownership is rebound from trusted identity rather than bundle content.
- MCP exposes bounded read projections only, so Product DSH cannot bypass the
  Product approval boundary to mutate accounts.

Checklist provenance and migration decisions are recorded in
[`COMMUNITY_FEATURE_CHECKLIST.md`](../COMMUNITY_FEATURE_CHECKLIST.md).
