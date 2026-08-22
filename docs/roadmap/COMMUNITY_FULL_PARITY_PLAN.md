# Community Full Parity Plan (Phase 32–40)

Status: `ACTIVE` (ADR-0017/0018/0019/0020/0021 Accepted)

This plan describes the remaining Community product-depth workflows that the
Phase 17–31 contract-first skeleton deferred. `IMPLEMENTATION_PLAN.md` is the
normative phase plan, `STATUS.md` identifies the current/next phase, and this
document supplies the parity-batch overview and dependency map.

## Source of truth

- Community reference: `/home/jefison/projects/BeyondQuant-community/frontend`
  (read-only; inspect → classify → port/refactor/replace).
- Current source: `apps/frontend`, `services/gateway`, `services/backend`,
  `services/mcp`, `services/runtime-adapter`.
- Gap inventory: `docs/roadmap/COMMUNITY_FEATURE_PARITY_GAP.md` and
  `COMMUNITY_FEATURE_PARITY_MATRIX_V2.md`.

## Accepted and planned decisions (2026-08-20)

1. Backtest create-wizard signal source = **pre-computed `signal_snapshot`
   artifact** (ADR-0017). No strategy-source execution in this batch.
2. Accepted: Agent workbench cards = **versioned BYQ card contract + curated
   extraction and owner-scoped Domain hydration** (ADR-0018). Raw DSH
   payloads never cross the Gateway and cards never carry executable actions.
3. Accepted: Credentials = **PostgreSQL AES-256-GCM envelope store with a
   private Runtime Adapter resolution seam** (ADR-0019). Public reads are
   masked, writes are audited, and user/system scopes fail closed.
4. Cache management = **PostgreSQL market-data cache status only**; Redis is
   not added in this batch.
5. Execution budget = **DSH model-call token accounting**.
6. Stock Pool identity/snapshots/lifecycle = **mutable owner-scoped catalog +
   immutable content-addressed membership snapshots** (ADR-0020).

## Global delivery rules (per phase)

- One isolated worktree / feature branch / Draft PR; stop at the human merge
  gate (AGENTS 34).
- Frontend calls Gateway Product API only; never MCP / Backend / DSH /
  PostgreSQL / Redis / provider directly (AGENTS 38).
- Every phase: Chrome DevTools MCP real-browser review + Community feature
  checklist evidence (AGENTS 36); no placeholder / fake data / disabled UI.
- Before coding each surface: inspect the Community page/component and
  classify as REUSE_AS_IS / PORT_COMPONENT / PORT_STYLE / PORT_LAYOUT /
  PORT_UX / REFACTOR / REFERENCE_ONLY / REPLACE / DROP (AGENTS 27).
- Contract tests before broad refactors (AGENTS 16).

## Phases

### Phase 32 — Backtest workspace depth
- Status: **COMPLETE (2026-08-18)** — wizard via `signal_snapshot` (ADR-0017,
  PR #81/#82), result depth tabs, delete/compare/mobile, Chrome evidence.
- Community: `BacktestView.vue` (2730 lines) create wizard, compare, 5 tabs
  (overview / trades / daily positions & returns / logs / strategy snapshot),
  delete, rerun, mobile cards.
- Delivered: list/filter/select/run/cancel/delete/compare, wizard, real
  equity/trades, logs, daily positions/returns, strategy snapshot, input
  manifest, and mobile cards.
- Remaining cross-phase gap: strategy source → `signal_snapshot` producer
  (D-0002), transferred to Phase 40 pending a dedicated Accepted ADR.
- Dependency: ADR-0017 (wizard selects a `signal_snapshot`).
- Classification: engine=`REPLACE`, wizard/compare=`PORT_UX`, result
  object=`REFACTOR`.
- Estimate: 16 person-days (L).
- Exit: wizard creates a backtest from a validated strategy + signal
  snapshot; all 5 tabs real; delete/compare/mobile work; Chrome evidence.

### Phase 33 — Strategy workspace depth
- Status: **COMPLETE (2026-08-20)** — durable draft save/soft-supersede,
  version history, real backtest counts, read-only detail, and Chrome evidence
  (PR #85/#86).
- Community: `StrategyView.vue` (1008 lines) editor, templates/snippets,
  validate, save, delete, backtest counts, version history.
- Delivered: editor/templates/snippets, validation, durable draft save/delete,
  immutable version/export, approval banner, version history, backtest counts,
  and read-only version detail.
- Remaining hardening/parity decisions are transferred to Phase 40 as
  D-0009–D-0012.
- Estimate: 10 person-days (L).

### Phase 34 — Stock Pool depth
- Status: **COMPLETE** under Accepted ADR-0020 (2026-08-21).
- Community: `StockPoolView.vue` (925 lines) catalog, member editing, index
  constituents, filters, weights, snapshots, activation/delete, mobile.
- Delivered: persisted typed catalog/detail, immutable member/weight snapshots,
  trusted index as-of history, filter/provenance/reference projections,
  lifecycle/tombstone semantics, and responsive Product API views.
- Dependency: ADR-0020 (Accepted).
- Estimate: 14 person-days (XL).

### Phase 35 — Paper Trading depth
- Status: **COMPLETE**.
- Community: `PaperTradingView.vue` (597 lines) 5 tabs + order detail +
  create/import + settlement + risk controls.
- Current: accounts/overview/positions/orders + order submit; ledger exists
  on backend.
- Gap: snapshots, settlement, order detail dialog, import/export, risk
  controls, ledger tab wiring.
- Delivered: six persisted tabs, immutable settlement snapshots, order audit,
  versioned risk controls, complete ledger, and validated BYQ asset bundles.
- Estimate: 9 person-days (M).

### Phase 36 — Agent workbench depth
- Status: **COMPLETE (2026-08-22)** under Accepted ADR-0018.
- Community: `AgentView.vue` (2057 lines) + AgentThinking /
  ApprovalManagementPanel / GlobalApprovalCenter / XiaobaAssistantDrawer.
- Current: sessions/turn/resume/cancel + WorkflowTrace + approval decisions.
- Gap: structured cards, assistant drawer, thinking panel, approval
  management, tool visualization depth.
- Dependency: ADR-0018 (Accepted). Phase 36 owns its Agent-specific
  components; Phase 40 may generalize them after they are proven.
- Delivered: normalized actionable cards, bounded public activity/answer
  projections, local/global approvals, conversation starters, and the Xiaoba
  assistant drawer; real Product API desktop/mobile Chrome MCP evidence and
  the Community checklist are under `docs/evidence/phase-36/`.
- Estimate: 14 person-days (XL).

### Phase 37 — My Space depth (Models / Assets / Agent Policy)
- Status: **NEXT — IMPLEMENTATION** under Accepted ADR-0019.
- Community: UserModelsView + UserModelSettingsPanel, UserAssetsView,
  UserAgentPolicyView.
- Current: profile complete; models masked-only; assets config import/export;
  agent policy personal only.
- Gap: model credential CRUD + agent binding, strategy/backtest re-import,
  agent policy presets/rule CRUD.
- Dependency: ADR-0019 (Accepted). Phase 37 owns its required model-settings
  component; Phase 40 may generalize it later.
- Estimate: 14 person-days (XL).

### Phase 38 — Operations workbenches
- Community: SystemMaintenanceWorkbench (4402) + ModelOperations (540) +
  GraphOperations (185) + RuntimeOperations (129) + AccessControlOperations
  (114) + DataSourceConfig (236) + DataSync (165).
- Current: 9 routes share one 134-line AdminOpsView; budget/graph are
  explicit placeholders.
- Gap: database/Redis/cache/model/agent/budget/runtime/graph/access work-
  benches and data-source/sync surfaces.
- Decisions: cache=PostgreSQL market-data cache status only (no Redis);
  budget=DSH model-call token accounting.
- Dependency: ADR-0019 for data-source credentials; backend projections.
- Estimate: 27 person-days (XL, largest).

### Phase 39 — Data Center / Data Sync depth
- Community: DataSourceConfig + DataSync.
- Current: provider capability + migration status + dataset list.
- Gap: Tushare-only data-source CRUD, test connection, sync jobs, coverage.
- Dependency: ADR-0019.
- Estimate: 11 person-days (L).

### Phase 40 — Shared components + final parity closure
- Community: AppStateBlock, EntityPagination, GlobalApprovalCenter,
  ApprovalManagementPanel, XiaobaAssistantDrawer, AgentThinking,
  StockPoolDialog, UserModelSettingsPanel, SystemAnalytics, ChartWrapper.
- Current: ChartWrapper/MetricCard/Base UI present; others missing.
- Gap: 8 components; extract early to serve Phases 36–38.
- Estimate: 8 person-days (M).

## Critical path

```
Phase 40 (shared components) ──► later generalization/final closure
Phase 32 (backtest)  ── split: result depth (no blocker) → wizard (ADR-0017)
Phase 33 (strategy)  ── independent
Phase 34 (stock pool) ── independent
Phase 35 (paper trading) ── independent
Phase 36 (agent)     ── complete under ADR-0018
Phase 37 (my space)  ── ADR-0019 accepted; ready
Phase 38 (operations) ── needs ADR-0019 + Phase 40
Phase 39 (data center) ── needs ADR-0019
```

“Independent” means independent of ADR-0018/0019 and Phase 40 components. It
does not waive the Phase 34 Stock Pool snapshot/version/lifecycle decision
gate recorded in `STATUS.md`.

## Total estimate

≈ 123 person-days across Phases 32–40 (single full-stack engineer; parallel
modules compress to roughly 2–3 months).

## Completion definition

All 19 Community views and 8 shared components are represented by real
Product API flows, Chrome DevTools MCP browser evidence, and updated parity
matrix entries with no `MISSING` and no unexplained `PARTIAL`. The v1.0 RC
review gate is then re-opened per `STATUS.md`.
