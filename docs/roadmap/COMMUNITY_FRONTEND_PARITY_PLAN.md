# Community Frontend Parity Plan

Status: `PLANNED`

This plan restores the Community frontend's user features, information
architecture, and interaction patterns in the new BeyondQuant frontend while
keeping the new BYQ architecture intact:

```text
Browser -> BYQ Product API / Gateway -> BYQ domain or Runtime Adapter
        -> MCP / Backend / DSH behind accepted boundaries
```

Community source is read-only reference at
`/home/jefison/projects/BeyondQuant-community/frontend`. Port visual language,
layout, and UX only after classification. No Community API, event schema,
storage, provider, or runtime coupling is reintroduced.

## Guiding rules

- One phase per isolated worktree/branch/Draft PR.
- Build one block, test its business capabilities before moving on.
- No placeholder-only or fake completion.
- Product/Admin UI must use BYQ Product API and normalized projections only.
- Time values are rendered in `Asia/Shanghai` by default.
- Durable browser session survives page refresh.

## Phase 1 - Session reliability and timezone

Scope:

- Fix auth bootstrap so a valid `byq_session` cookie survives refresh without
  redirecting to login.
- Introduce shared China-time formatting and apply it to `created_at` /
  `updated_at` columns in Home, Strategy, Backtest, and Research views.

Tests:

- Playwright: login, reload page, assert dashboard remains authenticated.
- Unit test for the China-time formatter.

## Phase 2 - Admin operations workspace

Community reference:

- `components/layout/OpsLayout.vue`, `OpsSidebar.vue`
- `views/operations/*.vue`

Scope:

- Build a role-protected Admin/Ops shell with grouped sidebar:
  - 基础设施: 数据库管理, 数据源管理, 缓存管理
  - 智能体平台: 模型运维, 智能体运维, 执行预算, 运行诊断, Graph 工作流
  - 权限与审计: 权限与审计
- Build each page with BYQ Product API projections; add gateway/backend
  endpoints only where a real capability already exists.
- Protect destructive actions; keep read-only diagnostics safe.

Tests:

- Product API contract fixtures for each operations projection.
- Playwright admin journey: login as admin, open each operations page,
  verify loading/empty/error/success states.
- Secret-boundary assertions.

## Phase 3 - Home dashboard parity

Community reference: `views/HomeView.vue`

Scope:

- Strategy, backtest, stock-pool, cache coverage, and system health cards.
- Quick actions, recent results, resource bars, partial-failure messaging.
- Reuse the existing Product dashboard/data/status endpoints; add list
  projections as needed.

Tests:

- Playwright dashboard with mocked/real Product API, partial failure cases.

## Phase 4 - Agent research workbench parity

Community reference: `views/AgentView.vue`, `components/agent/*.vue`

Scope:

- Conversation-first flow, session history, streaming normalized
  WorkflowTrace events, thinking steps, artifact cards, approvals.
- Backtest context pane and composer.

Tests:

- Agent session/turn contract tests.
- Playwright stream, history, approval, and empty/error states.

## Phase 5 - Strategy and Backtest workspaces

Community reference: `views/StrategyView.vue`, `views/BacktestView.vue`

Scope:

- Strategy list/detail split, Python editor, templates/snippets, validation,
  version inspection, save/delete.
- Backtest task table, filters, comparison, preflight, result detail with
  equity curve, trades, daily positions/returns, logs, metrics.

Tests:

- Strategy version/validation/export contract tests.
- Backtest run/cancel/result projection tests.
- Playwright list/detail/editor/compare journeys.

## Phase 6 - Stock Pool and Paper Trading

Community reference: `views/StockPoolView.vue`, `views/PaperTradingView.vue`

Scope:

- Pool catalog, create dialog, membership tabs, snapshots, weights, mobile
  cards.
- Paper accounts, positions, orders, ledger, snapshots, strategy tracking,
  risk controls.

Tests:

- Paper domain contract tests.
- Playwright create/list/detail flows and owner isolation.

## Phase 7 - My Space pages

Community reference:

- `views/UserAssetsView.vue`, `UserModelsView.vue`,
  `UserAgentPolicyView.vue`, `UserProfileView.vue`

Scope:

- Split current Settings into durable My Space entries: assets, models,
  agent policy, profile.
- Secret-safe masked model settings; write-only credentials.

Tests:

- Settings/profile/asset contract tests.
- Playwright masked secret fields and owner scoping.

## Phase 8 - Release parity and browser evidence

Scope:

- Run the full Community feature checklist.
- Chrome MCP review of every restored page.
- Playwright golden journey through real Product API.
- Update `COMMUNITY_FEATURE_PARITY_MATRIX_V2.md`.

Each phase stops at a Draft PR and the human merge gate.
