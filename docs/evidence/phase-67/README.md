# Phase 67 Index Stock Pools Evidence

## Scope and boundary

- Implemented ADR-0041 index producer only; Phase 68 dynamic evaluation is not included.
- Community stock-pool index semantics and information hierarchy were classified as
  `PORT_LOGIC` / `PORT_UX`; direct ORM/provider paths were `REPLACE`, and dynamic placeholders
  remain `DROP` as recorded in the migration inventory.
- Browser traffic uses same-origin Gateway/Product API. The producer reads only validated
  ADR-0030 canonical index weights; it does not import data or call Tushare.
- Product submits intent. The trusted Data Worker owns leasing, point-in-time selection,
  validation, immutable snapshot creation, and atomic current-pointer promotion.

## Verification

- Repository CI-equivalent suites: architecture, full PostgreSQL backend, gateway, frontend
  build/unit tests all passed locally.
- Backend tests cover no-look-ahead selection, percent-to-fraction normalization, idempotency,
  owner isolation, failed-run atomicity, lease recovery, and out-of-order completion.
- Real Product API Playwright Chromium journey passed against a fresh isolated Compose stack:
  durable login, index catalog selection, pool creation, worker materialization, members,
  history, desktop/mobile responsive rendering, no cross-origin request, and no HTTP 5xx.
- Chrome DevTools MCP independently created `Chrome MCP 指数验收池`, observed queued →
  succeeded after reload, verified the two-member immutable snapshot and materialization
  history, reviewed a 390 × 844 mobile viewport, and found no console messages. Its Network
  log contained only `http://127.0.0.1:18067` requests and Product routes returned 2xx.
- The acceptance fixture is synthetic and evidence-only; it writes canonical validated rows
  directly in the isolated database and is not a provider adapter or production seed.

## Artifacts

- `01-index-pool-desktop.png`: Playwright desktop history and succeeded run.
- `02-index-pool-mobile.png`: Playwright responsive catalog/detail hierarchy.
- `03-chrome-mcp-index-history.png`: Chrome DevTools MCP desktop history review.
- `04-chrome-mcp-mobile.png`: Chrome DevTools MCP mobile viewport review.
- `SHA256SUMS`: checksums for all screenshots.
