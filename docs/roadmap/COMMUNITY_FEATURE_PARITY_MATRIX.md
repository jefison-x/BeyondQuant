# Community Feature Parity Matrix

Status: Release-candidate evidence for Phase 23. Every Community page,
capability, and component is classified as `PORTED`, `REDESIGNED`,
`REPLACED`, `DROP`, or `DEFERRED`.

## Product pages

| Community surface | BYQ target | Decision | Phase |
|---|---|---|---|
| Login | `LoginView.vue` | `PORTED` / `REDESIGNED` auth | 17 |
| Home/Dashboard | `HomeView.vue` + Product dashboard | `PORTED` / `REDESIGNED` API | 17 |
| Agent | `AgentView.vue` + WorkflowTrace | `PORTED` UX, `REPLACE` event/API | 18 |
| Research | Quant Workspace + Research entities | `REDESIGNED` BYQ contracts | 19 |
| Strategy | Quant Workspace Strategy tab + BFF | `REDESIGNED` domain/API | 19 |
| Backtest | Quant Workspace Backtest tab + BFF | `PORTED` UX, `REPLACE` engine/API | 19 |
| Stock Pool | `StockPoolView.vue` + BYQ paper pool | `REDESIGNED` semantics/API | 21 |
| Paper Trading | `PaperTradingView.vue` + BYQ paper domain | `PORTED` UX, `REDESIGNED` domain | 21 |
| Profile | `SettingsView.vue` Profile tab | `PORTED` / `REDESIGNED` API | 20 |
| Models | `SettingsView.vue` Models tab | `PORTED` UX, secret-safe rewrite | 20 |
| Assets | Settings Assets tab (placeholder) | `DEFERRED` full asset index | 20 |
| Agent policy/approvals | Settings Approvals tab (masked status) | `DEFERRED` full inbox | 20 |
| Operations | `OperationsView.vue` + operations BFF | `PORTED` IA, `REDESIGNED` topology | 22 |
| Data source/sync | Settings Data tab | `REDESIGNED` Tushare/migration status | 20 |

## Shared components

| Community component | BYQ target | Decision |
|---|---|---|
| App shell/sidebar/header/bottom nav | `AppShell.vue`, `AppHeader.vue`, `AppSidebar.vue`, `AppBottomNav.vue` | `PORTED` layout/style, `REFACTOR` state/API |
| State/error/empty blocks | page states and error envelopes | `PORTED` UX |
| Pagination | Product API pagination contract | `REFACTOR` |
| Chart wrapper | not yet charted in Quant Workspace | `DEFERRED` chart parity |
| Dialogs/forms | simple forms/views | `PORTED` UX pattern |

## Explicit replacements and drops

| Community dependency/assumption | Decision |
|---|---|
| `/agent-api/*` and old Backend `/api/v1/*` browser calls | `REPLACE` with Product API/BFF |
| Raw Agent/DSH event schemas | `REPLACE` with BYQ WorkflowTrace projection |
| PydanticAI/Hermes runtime | `DROP` / `REPLACE` |
| BaoStock, AKShare, VectorBT | `DROP` |
| Frontend -> MCP/DSH/PostgreSQL/Redis/provider | `DROP` |
| Community global/superadmin privilege model | `REFERENCE_ONLY`; BYQ RBAC/audit contracts apply |

## Release-candidate conclusion

The browser journey Login -> Dashboard -> Agent -> Quant Workspace -> Stock
Pool -> Paper Trading -> Settings -> Operations is represented by BYQ Product
API/BFF and WorkflowTrace projections. Full artifact/approval asset indexing,
chart parity, and production backup/restore runbooks remain explicit
`DEFERRED` items for post-Phase-23 hardening.
