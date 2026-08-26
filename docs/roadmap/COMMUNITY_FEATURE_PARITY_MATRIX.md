# Community Feature Parity Matrix

Status: **Phase 40 final audit complete（2026-08-22）**。下方保留原 Phase 23 baseline，并由 Phase 40 closure addendum 解决。每个 Community surface 均已分类，不存在无法解释的 `PARTIAL` 或 `MISSING`。

## Product pages

| Community surface | BYQ target | Decision | Phase |
|---|---|---|---|
| Login | `LoginView.vue` | `PORTED` / `REDESIGNED` auth | 17 |
| Home/Dashboard | `HomeView.vue` + Product dashboard | `PORTED` / `REDESIGNED` API | 17 |
| Agent | `AgentView.vue` + WorkflowTrace | `PORTED` UX，`REPLACE` event/API | 18 |
| Research | Quant Workspace + Research entities | `REDESIGNED` BYQ contracts | 19 |
| Strategy | Quant Workspace Strategy tab + BFF | `REDESIGNED` domain/API | 19 |
| Backtest | Quant Workspace Backtest tab + BFF | `PORTED` UX，`REPLACE` engine/API | 19 |
| Stock Pool | `StockPoolView.vue` + BYQ paper pool | `REDESIGNED` semantics/API | 21 |
| Paper Trading | `PaperTradingView.vue` + BYQ paper domain | `PORTED` UX，`REDESIGNED` domain | 21 |
| Profile | `SettingsView.vue` Profile tab | `PORTED` / `REDESIGNED` API | 20 |
| Models | `SettingsView.vue` Models tab | `PORTED` UX，secret-safe rewrite | 20 |
| Assets | `AssetsView.vue` + manifested export/re-import | `REDESIGNED` owner-safe artifacts | 37 |
| Agent policy/approvals | `AgentPolicyView.vue` + global/local approvals | `PORTED` UX / `REDESIGNED` audit | 36–37 |
| Operations | `OperationsView.vue` + operations BFF | `PORTED` IA，`REDESIGNED` topology | 22 |
| Data source/sync | `DataCenterView.vue` + durable sync | `REDESIGNED` Tushare-only data plane | 39 |

## Shared components

| Community component | BYQ target | Decision |
|---|---|---|
| App shell/sidebar/header/bottom nav | `AppShell.vue`、`AppHeader.vue`、`AppSidebar.vue`、`AppBottomNav.vue` | `PORTED` layout/style，`REFACTOR` state/API |
| State/error/empty blocks | `AppStateBlock.vue` + Base state components | `PORT_COMPONENT` / `REFACTOR` |
| Pagination | `EntityPagination.vue` + paginated strategy Product API | `PORT_COMPONENT` / `REFACTOR` |
| Chart wrapper | 真实 backtest results 中的 `ChartWrapper.vue` | `REUSE_AS_IS` BYQ implementation |
| Dialogs/forms | simple forms/views | `PORTED` UX pattern |

## Phase 40 closure addendum

| Community component/capability | BYQ closure | Final decision |
|---|---|---|
| `GlobalApprovalCenter` / `ApprovalManagementPanel` | Phase 36 normalized components | `REUSE_AS_IS` BYQ equivalent |
| `XiaobaAssistantDrawer` | Phase 36 Product Agent drawer | `REUSE_AS_IS` BYQ equivalent |
| `AgentThinking` | `AgentActivityPanel` + public WorkflowTrace cards | `REFACTOR`；hidden reasoning `DROP` |
| `StockPoolDialog` | Phase 34 integrated create/edit/snapshot workflow | `PORT_UX`；duplicate dialog `DROP` |
| `UserModelSettingsPanel` | Phase 37 encrypted credential/profile/binding workbench | ADR-0019 下 `REFACTOR` |
| `SystemAnalytics` | Phase 38 operations workbenches + `MetricCard` | `REFACTOR`；Redis/raw host state `DROP` |
| Strategy description | Editable immutable draft/version snapshot field | `REUSE_AS_IS` |
| Strategy parameters/schema | Finite JSON Product fields，冻结到 StrategyVersion/signal job | `REUSE_AS_IS` / `REFACTOR` |
| Mutable strategy enable/disable 与 non-artifact CRUD | Artifact lifecycle + explicit human approval | `DROP` / `REPLACE` |
| Strategy source execution | ADR-0023 coordinator + credential-free signal sandbox | Community in-process `exec` 为 `REPLACE` |

## 显式 replacements 与 drops

| Community dependency/assumption | Decision |
|---|---|
| `/agent-api/*` 和旧 Backend `/api/v1/*` browser calls | 以 Product API/BFF `REPLACE` |
| Raw Agent/DSH event schemas | 以 BYQ WorkflowTrace projection `REPLACE` |
| PydanticAI/Hermes runtime | `DROP` / `REPLACE` |
| BaoStock、AKShare、VectorBT | `DROP` |
| Frontend → MCP/DSH/PostgreSQL/Redis/provider | `DROP` |
| Community global/superadmin privilege model | `REFERENCE_ONLY`；使用 BYQ RBAC/audit contracts |

## Release-candidate 结论

Browser journey Login → Dashboard → Agent → Research/Strategy → Stock Pool → isolated signal production → Backtest → Paper Trading → Settings → Operations 已由 durable BYQ Product API/WorkflowTrace flows 表示。Phase 40 关闭剩余 signal producer、strategy visibility/projection、shared-state/pagination、chart 和 deep-field decisions。No-mock multi-user golden journey 与 Chrome desktop/mobile review 记录于 `docs/evidence/phase-40/`；release-candidate review 可重新开放。
