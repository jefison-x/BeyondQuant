# Phase 34 BYQ Stock Pool browser acceptance

Captured on 2026-08-21 with Chrome DevTools MCP against an isolated Compose
stack and durable `ci-admin` login. The browser used only the same-origin
Gateway/Product API at `http://127.0.0.1:32798`; it did not call Backend, MCP,
PostgreSQL, or a provider directly.

## Evidence index

- `phase34-01-desktop-overview.png`: persisted custom-pool catalog and detail.
- `phase34-02-members-v2.png`: v2 member/weight snapshot after a real Product
  API write.
- `phase34-03-history-readonly.png`: immutable v1 historical snapshot dialog.
- `phase34-04-mobile-overview.png`: 390x844 responsive catalog/card layout.
- `phase34-05-index-as-of.png`: 2024-01-15 no-look-ahead resolution selects the
  2024-01-02 index snapshot instead of the later 2024-02-01 snapshot.
- `phase34-06-provenance.png`: persisted Tushare dataset/unit/normalization
  provenance and downstream-reference projection.

The index rows were inserted into the isolated database through the trusted
Backend data boundary, with two effective dates and complete Tushare
provenance. They are acceptance fixtures exercising the real persisted
contract; no fixture or index-write path is exposed to the browser.

## Acceptance observations

- Custom creation persisted two weighted members; an invalid 0.8 total was
  rejected with HTTP 422 and the domain message reached the UI.
- A valid edit created v2 with a new fingerprint while v1 remained readable.
- Active → inactive → active lifecycle transitions persisted.
- Index membership was read-only and as-of resolution did not look ahead.
- Refreshing the authenticated page produced no console warning/error. All 21
  requests were same-origin; the only domain calls were `/api/auth/*` and
  `/api/product/*`.
- Backend tests cover frozen Paper Trading, research, and backtest snapshot
  references; Gateway/MCP/frontend tests cover owner-scoped projections.

## Community checklist result

All items in the Community-derived checklist are satisfied: owner-scoped
paged catalog, typed persisted projections, immutable member/weight edits,
filter definitions, index effective-date history, stable snapshot identity,
lifecycle semantics, frozen downstream references, shared desktop/mobile
Product API behavior, reachable mobile actions, and captured real-browser
evidence.
