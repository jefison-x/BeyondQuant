# Community Frontend Migration

Status: `HISTORICAL_BASELINE` for Productization Phases 17–23. Current delivery
status is tracked by `docs/roadmap/STATUS.md`, the implementation plan and the
Community parity matrices; per-row status is retained as the original migration
decision unless explicitly reconciled.

Stock Pool reconciliation: Phase 34 delivered durable snapshot/lifecycle semantics,
Phase 46 standardized responsive UX, Phases 67–69 delivered trusted producers, and
Phase 70 closed multi-index catalogue coverage. The result is `REDESIGNED_PASS`;
Community remains read-only evidence.

本文记录只读 Community frontend reference 的 inspect → classify →
port/rewrite → test 计划，不授权复制 frontend，也不授权实现未来 phase。

> 中文说明负责 policy、边界和结论。Page/component inventory 保留英文
> source paths、classification、API names 和逐项审计描述，便于与 Community
> reference 核对；所有实现仍必须改用 BYQ Product API。

## Reference 与 policy

- Source: `/home/jefison/projects/BeyondQuant-community/frontend`.
- Reference revision: `58dd99d` on `agent/workspace-community`.
- Framework stack: Vue 3, Vite, Vue Router, Pinia, Element Plus, ECharts,
  Axios, Playwright, and OpenAPI type generation.
- New target: `apps/frontend`, using Vue 3/Vite/TypeScript, Vue Router,
  Pinia, Element Plus, ECharts, a typed Product API client, generated
  OpenAPI types, and Playwright unless an ADR records a blocker.
- Community source and API contracts are reference-only. No Community file is
  modified, and no `cp -r frontend` migration is permitted.

The classifications used here are:

`REUSE_AS_IS`, `PORT_COMPONENT`, `PORT_STYLE`, `PORT_LAYOUT`, `PORT_UX`,
`REFACTOR`, `REFERENCE_ONLY`, `REPLACE`, and `DROP`.

“Visual” and “UX” reuse never means API, state, runtime, auth, storage, or
event-schema reuse. Every browser request must follow:

```text
Frontend → BYQ Product API / Gateway → BYQ Domain or Runtime Adapter
        → MCP / Backend / DSH behind accepted boundaries
```

The frontend must not call raw Backend-internal APIs, MCP, DSH, provider
endpoints, PostgreSQL, Redis, or raw DSH event schemas.

## 已观察的信息架构与交互模式

### Shell 与 navigation

`App.vue` applies theme/locale classes and mounts `AppLayout`. `AppLayout`
switches between public Login and an authenticated workspace. Desktop/tablet
uses a collapsible 260px/68px sidebar plus a 64px header; mobile uses a bottom
navigation bar. Operations routes use a separate `OpsSidebar` and are gated by
superadmin route metadata. The primary groups are 投研工作台, 研究与策略,
验证与执行, 我的空间, and a separate System Operations surface.

`AppHeader` exposes page metadata and page-level actions, and includes a
global approval trigger. The sidebar also provides recent session history with
open, pin, rename, and delete actions. This is a strong Phase 17 layout/UX
reference, but session history and approval data must come from BYQ Product
projections.

### 通用 visual/state language

The theme uses a light neutral surface, orange brand accent, compact cards,
rounded Element Plus controls, dense tables, status tags, metric strips, and a
two-column workbench (`--byq-workbench-columns`) that collapses on narrow
screens. `AppStateBlock` standardizes empty/error/info states; `ChartWrapper`
provides ECharts lifecycle, resize observation, skeleton loading, and empty
data handling; `EntityPagination` standardizes paged lists. These are good
component/style/UX candidates, but their data inputs must be typed Product API
contracts.

### User workflows

- Login stores access/refresh tokens in browser storage and bootstraps
  `/api/v1/auth/me`; BYQ will preserve the user-facing flow but replace the
  auth/session contract.
- Home loads independent strategy, backtest, stock-pool, cache, and system
  summaries with partial-failure messaging, quick actions, recent results,
  resource bars, and refresh actions.
- Agent uses a conversation-first flow with starter prompts, session history,
  streaming messages, thinking steps, strategy/stock-candidate/optimization
  cards, approvals, a backtest context pane, and a composer. BYQ will replace
  old Agent API/SSE payloads with normalized WorkflowTrace/product events.
- Strategy uses list/detail split panes, mobile cards, built-in read-only
  strategy inspection, a Python textarea editor, template/snippet insertion,
  validation, save, delete, and backtest counts. BYQ will retain domain-artifact
  UX while using immutable StrategyVersion/Approval contracts.
- Backtest uses a task table/mobile card list, search/status filters,
  pagination, two-item comparison, a result detail pane with overview,
  ECharts equity curve, trades, daily positions/returns, logs, metrics,
  preflight/data-sync dialogs, and explicit execution/data-quality summaries.
- Stock Pool uses a paged catalog, type filters, create dialog with candidate
  filters, final membership tab, custom/index/dynamic detail branches,
  historical snapshots, weights, and mobile cards. Domain semantics must be
  inspected and reimplemented under BYQ ownership.
- Paper Trading uses account selection plus detail tabs for overview,
  positions, orders, ledger, snapshots, strategy tracking, and risk controls;
  dialogs cover create/import/order/settlement. It is UX evidence only; BYQ
  must define a distinct paper domain.
- Settings cover profile, model credentials/profiles and Agent bindings,
  assets with import/export, personal approval policies/presets/history, and
  a global approval center. Secret fields are write-only/masked in the new
  product.
- Operations provides read-mostly database/source/cache/model/agent/budget,
  runtime, graph, access/audit, sync, migration, and maintenance workbenches.
  BYQ will keep the information architecture but replace old runtime/API and
  protect destructive actions.

## Page/component migration inventory（保留英文逐项审计记录）

| Community source | Visual reuse | UX reuse | API/state dependency | New BYQ target | Classification | Target phase | Status |
|---|---|---|---|---|---|---|---|
| `frontend/src/App.vue` | Theme class and global reset | App mount/back-to-top | Pinia theme state | `apps/frontend` app shell | `PORT_LAYOUT` + `PORT_STYLE`, auth rewrite | 17 | `PLANNED` |
| `frontend/src/router/index.js` | Route grouping and metadata | Login guard, business vs ops split | Old auth role/JWT and route API assumptions | Product Router + auth/session guard | `PORT_UX`, `REFACTOR` | 17 | `PLANNED` |
| `frontend/src/store/*` | Store organization | Theme/locale/sidebar/notification patterns | Local app-only state | Pinia Product UI stores | `PORT_COMPONENT`, `REFACTOR` | 17 | `PLANNED` |
| `frontend/src/api/*`, `utils/request.js` | None | Request loading/error ergonomics | `/api/v1/*`, `/agent-api/*`, old error payloads | Typed Product API client and generated types | `REPLACE` | 16–17 | `PLANNED` |
| `frontend/src/auth/*` | Login/session interaction | token bootstrap/logout/profile | Browser token storage and old auth endpoints | BYQ auth/session contract | `PORT_UX`, `REPLACE` | 16–17 | `PLANNED` |
| `components/layout/AppLayout.vue` | Workspace/public split and breakpoints | Desktop/tablet/mobile layout | Route metadata only | Product App Shell | `PORT_LAYOUT` + `PORT_STYLE` | 17 | `PLANNED` |
| `components/layout/AppHeader.vue` | Header, actions, approval affordance | Page action injection | Global approval API | Product header/actions projection | `PORT_LAYOUT` + `PORT_UX`, API rewrite | 17–20 | `PLANNED` |
| `components/layout/AppSidebar.vue` | Brand, grouped nav, collapsible sidebar | Session history pin/rename/delete | Old Agent session API | Product navigation/session projection | `PORT_LAYOUT` + `PORT_UX`, API rewrite | 17–18 | `PLANNED` |
| `components/layout/AppBottomNav.vue` | Mobile navigation | Mobile route switching | Route metadata | Product mobile navigation | `PORT_LAYOUT` + `PORT_UX` | 17 | `PLANNED` |
| `components/layout/UserSettingsMenu.vue` | User menu | Profile/settings/logout shortcuts | Old auth/user fields | Product user menu | `PORT_COMPONENT` + `PORT_UX`, API rewrite | 17, 20 | `PLANNED` |
| `components/layout/OpsLayout.vue`, `OpsSidebar.vue` | Operations shell/sidebar | Role-protected grouped operations | Superadmin route guard and old ops routes | Product Operations shell | `PORT_LAYOUT` + `PORT_UX`, API rewrite | 22 | `PLANNED` |
| `components/common/AppStateBlock.vue` | Empty/error/info visuals | Recovery action slot | None | Shared Product state component | `PORT_COMPONENT` + `PORT_STYLE` | 17 | `PLANNED` |
| `components/common/EntityPagination.vue` | Pagination layout | Page/size changes | Offset/limit assumptions | Typed Product pagination | `PORT_COMPONENT` + `REFACTOR` | 16–17 | `PLANNED` |
| `components/charts/ChartWrapper.vue` | ECharts lifecycle, resize, skeleton | Loading/empty chart behavior | Old result shape | Product chart adapter | `PORT_COMPONENT` + `PORT_STYLE`, API rewrite | 17, 19 | `PLANNED` |
| `components/agent/AgentThinking.vue` | Compact step disclosure | Expandable progress/tool labels | Old Agent step types | BYQ normalized trace step projection | `PORT_COMPONENT` + `PORT_UX`, schema rewrite | 18 | `PLANNED` |
| `components/agent/XiaobaAssistantDrawer.vue` | Assistant drawer/cards | Ask, approve, generate strategy/select stocks | Old Agent endpoints and artifact payloads | Product assistant surface | `PORT_UX`, `REFACTOR` | 18–19 | `PLANNED` |
| `components/agent/GlobalApprovalCenter.vue` | Approval bell/dropdown | Pending list and decision actions | Old Agent approvals | BYQ Approval Inbox projection | `PORT_COMPONENT` + `PORT_UX`, API rewrite | 18, 20 | `PLANNED` |
| `components/agent/ApprovalManagementPanel.vue` | Policy cards/forms/tables | Policy edit, presets, history | Old Agent policy schema and actions | BYQ approval policy UI | `PORT_UX`, `REFACTOR` | 20 | `PLANNED` |
| `components/stocks/StockPoolDialog.vue` | Multi-step filter/final-list dialog | Candidate search, add/remove, validation | Old stock search/pool APIs | BYQ StockPool draft/version flow | `PORT_COMPONENT` + `PORT_UX`, domain rewrite | 21, 34, 46, 67–70 | `IMPLEMENTED` (`REDESIGNED_PASS`) |
| `components/settings/UserModelSettingsPanel.vue` | Two-column model settings/cards | Credentials/profile/binding flows | Old credential endpoints | Secret-safe Product model settings | `PORT_LAYOUT` + `PORT_UX`, API rewrite | 20 | `PLANNED` |
| `components/system/SystemAnalytics.vue` | Metrics/status cards | Refresh/status visibility | Old system metrics | Product operations health projection | `PORT_STYLE` + `REFACTOR`, API rewrite | 38 | `IMPLEMENTED` |
| `views/LoginView.vue` | Centered login card/form | Submit/loading/error/redirect | `/api/v1/auth/login` | Product Login | `PORT_LAYOUT` + `PORT_UX`, auth rewrite | 17 | `PLANNED` |
| `views/HomeView.vue` | Dashboard cards, stats, quick actions, status bars | Partial-failure load, refresh, links | Strategies/backtests/pools/cache/system endpoints | Product Dashboard | `PORT_LAYOUT` + `PORT_UX`, API rewrite | 17 | `PLANNED` |
| `views/AgentView.vue` | Research workbench and context-pane layout | Chat, stream, history, trace/progress, approvals, artifact cards | `/agent-api`, old SSE/event schema, old backtest API | Agent Research Workbench | `PORT_LAYOUT` + `PORT_UX`, API/event replace | 18 | `PLANNED` |
| `views/BacktestView.vue` | Task/result split, tabs, tables, charts, dialogs | Filter/compare/preflight/result inspection | Old backtest, engine, cache and sync APIs | BYQ Backtest Workspace | `PORT_LAYOUT` + `PORT_UX`, API/domain replace | 19 | `PLANNED` |
| `views/StrategyView.vue` | List/detail/editor split, templates, mobile cards | Draft/edit/validate/save/version inspection | Old strategy and Agent validation endpoints | Strategy Draft/Version product view | `PORT_LAYOUT` + `PORT_UX`, domain/API rewrite | 19 | `PLANNED` |
| `views/StockPoolView.vue` | Catalog/detail tabs, tables, mobile cards | Pool create, membership/snapshot inspection | Old stock-pool APIs and search semantics | Stock Pool workspace | `PORT_LAYOUT` + `PORT_UX`, domain/API rewrite | 21, 34, 46, 67–70 | `IMPLEMENTED` (`REDESIGNED_PASS`) |
| `views/PaperTradingView.vue` | Account/detail/tabs/dialogs/table UX | Simulation account/order/fill/settle/risk flows | Old Agent paper API and legacy execution assumptions | BYQ Paper Trading workspace | `PORT_LAYOUT` + `PORT_UX`, domain/API replace | 21 | `PLANNED` |
| `views/UserProfileView.vue` | Settings card/form | Profile/preference save | Old `/auth/me` | Product profile | `PORT_LAYOUT` + `PORT_UX`, API rewrite | 20 | `PLANNED` |
| `views/UserModelsView.vue` | Settings page framing | User model settings entry | Old user model contracts | Product model settings | `PORT_LAYOUT` + `PORT_UX`, API rewrite | 20 | `PLANNED` |
| `views/UserAssetsView.vue` | Asset panels/tables/summary | Asset navigation and import/export | Old asset bundle/API | Product artifact/asset workspace | `PORT_LAYOUT` + `PORT_UX`, API rewrite | 20 | `PLANNED` |
| `views/UserAgentPolicyView.vue` | Policy cards/forms/tables | Preference, preset, rule, history flows | Old Agent approval-policy API | Product approval preferences | `PORT_LAYOUT` + `PORT_UX`, API rewrite | 20 | `PLANNED` |
| `views/operations/AccessControlOperationsView.vue` | Role cards/audit table | Approval/audit filtering | Old system access and Agent policy APIs | BYQ RBAC/audit operations projection | `PORT_UX`, API/security rewrite | 38 | `IMPLEMENTED` |
| `views/operations/GraphOperationsView.vue` | Graph chart/definition/run table | Run/checkpoint inspection | Old graph/run/checkpoint API | BYQ trace/runtime operations view | `REPLACE`, BYQ AgentRun/WorkflowTrace projection | 38 | `IMPLEMENTED` |
| `views/operations/ModelOperationsView.vue` | Provider/model/binding panels | Provider/model binding and refresh | Old global model config APIs/secrets | Secret-safe model operations | `PORT_UX`, metadata-only security rewrite | 38 | `IMPLEMENTED` |
| `views/operations/RuntimeOperationsView.vue` | Status cards/table/drawer | Runtime diagnostic drill-down | Old Agent diagnostics/run schema | Product-safe runtime/trace status | `PORT_UX`, normalized usage/schema rewrite | 38 | `IMPLEMENTED` |
| `views/operations/SystemMaintenanceWorkbench.vue` | Tabbed maintenance workbench | Cache/data sync/database/migration controls | Direct old Backend control APIs, destructive actions | Role-protected BYQ operations BFF | `PORT_LAYOUT` + `PORT_UX` + `REFACTOR`; unsafe controls DROP | 38 | `IMPLEMENTED` |
| `views/system/DataSourceConfig.vue`, `DataSync.vue` | Data source/sync forms and tables | Configure/status/sync interactions | Old provider/plugin/fallback model | Tushare capability and migration status views | `PORT_UX`, `REFACTOR` / `DROP` old providers | 20, 22 | `PLANNED` |
| `frontend/src/styles/byq-theme.css` | Tokens, cards, tables, responsive rules | Consistent visual language | None | BYQ design tokens after review | `PORT_STYLE` | 17 | `PLANNED` |
| `frontend/tests/smoke/app.spec.js` | Browser smoke/test structure | Login/navigation/dashboard checks | Old API mocks and route contracts | Product API/Playwright smoke and golden journey | `PORT_TESTS`, `REFACTOR` | 17, 23 | `PLANNED` |

## 显式 replacements 与 drops

| Community dependency/assumption | Decision | Reason |
|---|---|---|
| `/agent-api/*` and old Backend `/api/v1/*` calls from browser | `REPLACE` | Product frontend must consume a stable BYQ Product API/BFF. |
| Agent SSE payloads and old Agent step/event names | `REPLACE` | Frontend consumes BYQ WorkflowTrace/product events, never raw DSH/Agent schemas. |
| Frontend → MCP, DSH, PostgreSQL, Redis, or provider endpoints | `DROP` | Violates BYQ integration and data ownership boundaries. |
| PydanticAI/Hermes assumptions in Agent UX | `REPLACE` | DSH owns generic runtime; BYQ owns domain projections. |
| BaoStock, AKShare, VectorBT selectors or capability flags | `DROP` | Permanently excluded by `AGENTS.md` and migration inventory. |
| Community global/superadmin privilege model | `REFERENCE_ONLY` | Port role-protected UX, but use BYQ RBAC/approval/audit contracts. |

## Migration test obligations

Each ported page/component must have a Product API contract fixture and state
coverage for loading, empty, error, retry/cancel where relevant, and success.
Playwright must review desktop, tablet, mobile, keyboard/focus, and responsive
table/card behavior. Agent, Strategy, Backtest, Stock Pool, Paper Trading, and
Operations flows must include secret-boundary and owner-isolation assertions.
The Phase 23 parity matrix is the release-level source of truth; this
inventory remains the pre-implementation classification record.
