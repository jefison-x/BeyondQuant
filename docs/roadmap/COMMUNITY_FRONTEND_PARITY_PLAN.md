# Community Parity Delivery Plan

Status: `COMPLETE`

This plan restores Community user features in BeyondQuant while preserving the
new architecture:

```text
Browser -> BYQ Product API / Gateway -> BYQ domain or Runtime Adapter
        -> MCP / Backend / DSH behind accepted boundaries
```

Every phase must deliver three layers together:

1. Frontend page/UX aligned with the Community reference.
2. Product API and Backend capability behind that page.
3. Community-derived contract/regression tests plus BYQ Playwright coverage.

No phase is complete with a page-only shell or placeholder business state.

## Guiding rules

- One phase per isolated worktree/branch/Draft PR.
- Build one business block, test its business capabilities, then stop at the
  human merge gate.
- Community source is read-only reference; port logic/tests only after the
  inspect -> classify -> extract invariants -> implement sequence.
- BaoStock, AKShare, VectorBT, PydanticAI, Hermes, and old raw API/event/DB
  coupling remain `DROP` or `REPLACE`.
- Browser time values use `Asia/Shanghai`.
- Durable browser session survives refresh.

## Phase 1 - Session reliability and timezone

Frontend:

- Fix auth bootstrap refresh redirect.
- China-time formatting.

Backend/Product API:

- `/api/auth/me` returns a durable subject and role.

Tests:

- Playwright reload-after-login.
- Time formatter unit test.

Status: merged in PR #34.

## Phase 2 - Admin operations workspace and operations projections

Frontend:

- Role-protected `OpsLayout + OpsSidebar`.
- Nine operations pages: database, sources, cache, models, agents, budget,
  runtime, graphs, access.

Backend/Product API:

- Add owner-scoped list projections used by operations and research pages:
  - `GET /api/product/research/tasks`
  - `GET /api/product/research/experiments`
  - `GET /api/product/backtests`
  - `GET /api/product/strategies`
  - `GET /api/product/factors`
- Add a real dashboard aggregation endpoint:
  - `GET /api/product/dashboard` returns counts/status from BYQ stores.
- Keep destructive operations read-only behind RBAC.

Community tests to port/adapt:

- Research transition/idempotency regression ideas.
- Backtest job/retry/resource regression ideas.
- Owner/actor authorization assertions.

Tests:

- Product API contract tests for every new list/aggregation endpoint.
- Playwright admin journey and list/empty/error states.

Status: merged in PR #35.

## Phase 3 - Home dashboard parity

Frontend:

- Community Home cards: strategies, backtests, stock pools, cache coverage,
  system health, quick actions, recent results, resource bars.

Backend/Product API:

- Dashboard aggregation from BYQ stores (strategy/backtest/pool/artifact
  counts, recent items, data status).
- Health/status projections from real service readiness.

Community tests to port/adapt:

- Partial-failure summary semantics.
- Asset/resource count regression expectations.

Tests:

- Dashboard aggregation contract tests.
- Playwright dashboard partial-failure journeys.

Status: merged in PR #36 and #37.

## Phase 4 - Agent research workbench parity

Frontend:

- Conversation-first flow, session history, streaming WorkflowTrace, thinking
  steps, artifact cards, approvals, backtest context.

Backend/Product API:

- Session list/projection, turn/resume/cancel already exists; add normalized
  event replay where required.
- Approval inbox/decision projections.

Community tests to port/adapt:

- Approval policy/audit invariants.
- Session history and recovery expectations.

Tests:

- Agent session/turn contract tests.
- Playwright stream/history/approval/error states.

Status: merged in PR #38, #39, #40, and #41.

## Phase 5 - Strategy and Backtest workspaces

Frontend:

- Strategy list/detail, Python editor, templates, validation, version history.
- Backtest task list/filters/compare/preflight/result detail with charts,
  trades, positions, returns, logs, metrics.

Backend/Product API:

- Strategy list/version/export/validation endpoints.
- Backtest list/submit/run/cancel/result endpoints.
- Content-addressed manifests and immutable result references.

Community tests to port/adapt:

- Strategy version snapshot tests.
- Backtest input manifest tests.
- Native A-share execution golden regression tests.
- Backtest result object integrity tests.

Tests:

- Product API contract tests for strategy/backtest.
- Playwright list/detail/editor/compare journeys.

Status: merged in PR #42, #43, #44, #45, and #46.

## Phase 6 - Stock Pool and Paper Trading

Frontend:

- Pool catalog, create dialog, membership, snapshots, weights, mobile cards.
- Paper accounts, positions, orders, ledger, snapshots, strategy tracking,
  risk controls.

Backend/Product API:

- Stock pool list/version/membership endpoints.
- Paper account list, order, position/ledger/snapshot endpoints.

Community tests to port/adapt:

- Stock pool version snapshot tests.
- Universe authorization guard tests.
- Paper trade/risk semantics.

Tests:

- Paper/pool contract tests.
- Playwright create/list/detail and owner isolation.

Status: merged in PR #47.

## Phase 7 - My Space pages

Frontend:

- Split assets, models, agent policy, profile pages.

Backend/Product API:

- Durable profile/preferences endpoints.
- Masked model credential endpoints.
- Owner-scoped asset index/export/import.

Community tests to port/adapt:

- Asset bundle determinism/secret exclusion tests.
- Object lifecycle ownership tests.

Tests:

- Settings/profile/asset contract tests.
- Playwright masked secrets and owner scoping.

Status: merged in PR #48.

## Phase 8 - Release parity and browser evidence

Scope:

- Full Community feature checklist.
- Chrome MCP review of every restored page.
- Playwright golden journey through real Product API.
- Update `COMMUNITY_FEATURE_PARITY_MATRIX_V2.md`.

Status: merged in PR #49.

Each phase stops at a Draft PR and the human merge gate.

Phases 1-8 restored the product shell, and the subsequent product-depth
phases delivered Backtest result workspace, Strategy, Stock Pool, Paper
Trading, Agent workbench, personal Agent Policy, and Data Center depth.
Explicitly deferred items (Backtest create wizard pending a strategy
signal-source ADR, model credential CRUD, asset re-import, agent policy
presets/rule CRUD, operations workbenches, data sync jobs, paper
snapshots/settlement) are recorded in
`docs/roadmap/COMMUNITY_FEATURE_PARITY_MATRIX_V2.md` for the v1.0 RC review.
