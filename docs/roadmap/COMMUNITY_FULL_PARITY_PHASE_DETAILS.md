# Community Full Parity — Phase 33–40 Detailed Task Table

Status: `ACTIVE` — complements `IMPLEMENTATION_PLAN.md` and
`COMMUNITY_FULL_PARITY_PLAN.md` with
per-phase Community comparison, current state, gaps, dependencies,
classification, and estimates.

Legend (classification per AGENTS rule 27): `REUSE_AS_IS`, `PORT_COMPONENT`,
`PORT_STYLE`, `PORT_LAYOUT`, `PORT_UX`, `REFACTOR`, `REFERENCE_ONLY`,
`REPLACE`, `DROP`.

---

## Phase 33 — Strategy workspace depth

- Status: `COMPLETE` (2026-08-20, PR #85/#86).

- Community: `StrategyView.vue` (1008 lines) — list/detail split, Python
  editor, templates/snippets, validate, save, delete, backtest counts,
  version history, read-only mode.
- Delivered BYQ: list/detail, editor + template/snippet insertion, validation,
  durable draft save/soft-supersede, immutable version/export, approval
  banner, version history, real backtest counts, and read-only version mode.
- Transferred follow-ups: D-0009–D-0012 in Phase 40.
- Dependencies: Backend `strategy_draft` CRUD + version-history list +
  backtest-count projection; Product API routes; MCP
  `byq_strategy_draft_save`.
- Classification: editor/templates=`PORT_UX`; version history=`REFACTOR`;
  domain validation=`REPLACE`.
- Estimate: 10 person-days (L).
- Exit criteria: draft save/delete works; version history browsable; backtest
  counts real; Chrome evidence.

---

## Phase 34 — Stock Pool depth

- Status: `NEXT — BLOCKED AT DECISION GATE` until the Stock Pool
  snapshot/version/lifecycle ADR is Accepted.

- Community: `StockPoolView.vue` (925 lines) — catalog, type filters, create
  dialog with candidate filters, member editing, index constituents, custom/
  index/dynamic branches, historical snapshots, weights, mobile cards,
  activate/deactivate/delete.
- Current BYQ: `StockPoolView.vue` (277 lines) — create (name/type/weights
  JSON) + list + type filter.
- Gaps:
  1. Catalog / type taxonomy.
  2. Member editing tab.
  3. Index constituents tab.
  4. Filter conditions tab.
  5. Historical snapshot tab.
  6. Weight editing UI.
  7. Activate/deactivate/delete.
  8. Mobile cards.
- Dependencies: Accepted Stock Pool ADR; Backend pool member CRUD + weights +
  snapshots + catalog type; Product API routes; MCP `byq_pool_*`.
- Classification: catalog/member/snapshot=`REFACTOR`; weights/filter=
  `PORT_UX`; create dialog=`PORT_COMPONENT`.
- Estimate: 14 person-days (XL).
- Exit criteria: full catalog; 5 tabs real; weights/snapshots persisted;
  Chrome evidence.

---

## Phase 35 — Paper Trading depth

- Community: `PaperTradingView.vue` (597 lines) — account select, 5 tabs
  (overview/positions/orders/ledger/snapshots), order detail dialog, create/
  import account, manual settlement, risk controls, import/export.
- Current BYQ: `PaperTradingView.vue` (308 lines) — account create/select,
  overview/positions/orders, order submit; backend already has `ledger`.
- Gaps:
  1. Snapshot tab.
  2. Manual settlement.
  3. Order detail dialog.
  4. Import/export.
  5. Risk controls.
  6. Ledger tab wiring to existing endpoint.
- Dependencies: Backend snapshot + settlement + risk + import/export;
  Product API routes.
- Classification: account/order=`REFACTOR`; settlement/snapshot/risk=
  `PORT_UX`; import/export=`REPLACE` (BYQ asset bundle).
- Estimate: 9 person-days (M).
- Exit criteria: 6 tabs real; settlement/import-export/risk work; Chrome
  evidence.

---

## Phase 36 — Agent workbench depth

- Community: `AgentView.vue` (2057 lines) + `AgentThinking` (155),
  `ApprovalManagementPanel` (385), `GlobalApprovalCenter` (300),
  `XiaobaAssistantDrawer` (285) — conversation, streaming, thinking steps,
  strategy/stock/optimization cards, approval cards, backtest context,
  assistant drawer, tool visualization, starters.
- Current BYQ: `AgentView.vue` (357 lines) — sessions/turn/resume/cancel,
  WorkflowTrace, approval decisions.
- Gaps:
  1. Xiaoba assistant drawer.
  2. AgentThinking component.
  3. ApprovalManagementPanel.
  4. GlobalApprovalCenter.
  5. Strategy-draft card.
  6. Stock-candidates card.
  7. Optimization card.
  8. Tool visualization depth.
  9. Conversation starters.
- Dependencies: ADR-0018 (WorkflowTrace card contract) + normalization
  upgrade (currently only `text_bytes` survives); shared components (Phase 40).
- Classification: drawer/thinking=`PORT_COMPONENT`; cards=`REFACTOR` (BYQ
  WorkflowTrace projection); tool viz=`REFACTOR`.
- Estimate: 14 person-days (XL).
- Exit criteria: strategy/stock/optimization cards appear in conversation and
  are actionable; assistant drawer works; Chrome evidence.

---

## Phase 37 — My Space depth (Models / Assets / Agent Policy)

- Community: `UserModelsView` (36) + `UserModelSettingsPanel` (454),
  `UserAssetsView` (258), `UserAgentPolicyView` (142), `UserProfileView` (133).
- Current BYQ: Profile complete; `ModelsView` (80) masked-only; `AssetsView`
  (213) index + config import/export; `AgentPolicyView` (173) personal policy
  + approval history.
- Gaps:
  1. Model credential CRUD + Agent binding.
  2. Asset strategy/backtest re-import.
  3. Agent policy presets/rule CRUD.
- Dependencies: ADR-0019 (encrypted credential store); Backend model
  credential CRUD + asset re-import + policy presets/rule CRUD.
- Classification: credential CRUD=`REPLACE` (BYQ masked/audit); asset bundle=
  `REFACTOR`; policy rules=`PORT_UX`.
- Estimate: 14 person-days (XL).
- Exit criteria: credentials writable and never echoed; strategy/backtest
  re-importable; rules CRUD effective; Chrome evidence.

---

## Phase 38 — Operations workbenches (largest)

- Community views (total ~5700 lines):
  - `SystemMaintenanceWorkbench` (4402) — database/Redis config + migration.
  - `ModelOperationsView` (540) — provider credentials / models / Agent bind.
  - `GraphOperationsView` (185) — graph runs / checkpoints.
  - `RuntimeOperationsView` (129) — runtime diagnostics / usage / limits.
  - `AccessControlOperationsView` (114) — role permissions + access audit.
  - `DataSourceConfig` (236) — data-source configuration.
  - `DataSync` (165) — sync jobs.
- Current BYQ: 9 routes share one `AdminOpsView` (134 lines); budget/graph
  are explicit placeholders (`尚未接入 BYQ Product API`); rest are status
  tables.
- Gaps: database/Redis/cache/model/agent/budget/runtime/graph/access
  workbenches + data-source/sync surfaces are nearly all missing.
- Decisions: cache = PostgreSQL market-data cache status only (no Redis);
  budget = DSH model-call token accounting.
- Dependencies: ADR-0019 for data-source credentials; Backend read-only
  projections + RBAC-gated write operations; shared components (Phase 40).
- Classification: layout=`PORT_LAYOUT`; each workbench=`REFACTOR` (BYQ
  topology) + `PORT_UX`; access audit=`REPLACE` (BYQ RBAC).
- Estimate: 27 person-days (XL).
- Exit criteria: no placeholders; read-only projections real; write ops carry
  RBAC + audit; Chrome evidence.

---

## Phase 39 — Data Center / Data Sync depth

- Community: `DataSourceConfig` (236) + `DataSync` (165) — source config,
  test connection, cache status, sync jobs, coverage.
- Current BYQ: `DataCenterView` (47) + `/api/product/data-center/status` —
  provider capability + migration status + dataset list.
- Gaps:
  1. Data-source config (Tushare-only; BaoStock/AKShare=DROP).
  2. Test connection.
  3. Sync job create/status.
  4. Coverage audit.
- Dependencies: ADR-0019; Backend data-source CRUD + sync job + coverage.
- Classification: config/sync=`REFACTOR`; cache status=`REPLACE` (BYQ PG
  single store); coverage=`PORT_UX`.
- Estimate: 11 person-days (L).
- Exit criteria: configure Tushare source, trigger sync, view coverage and
  job status; Chrome evidence.

---

## Phase 40 — Shared components + final parity closure

- Community components (lines): `AppStateBlock` (113), `EntityPagination`
  (58), `GlobalApprovalCenter` (300), `ApprovalManagementPanel` (385),
  `XiaobaAssistantDrawer` (285), `AgentThinking` (155), `StockPoolDialog`
  (293), `UserModelSettingsPanel` (454), `SystemAnalytics` (103),
  `ChartWrapper` (197).
- Current BYQ: `ChartWrapper`, `MetricCard`, `Base*` UI present; others
  missing or inlined.
- Gaps: 8 shared components missing; several phases depend on them.
- Recommendation: extract early as a prerequisite for Phases 36–38.
- Classification: all=`PORT_COMPONENT` (layout/style reuse) + `REFACTOR`
  (wire to BYQ Product API).
- Estimate: 8 person-days (M).

---

## Cross-phase dependencies

- Phase 40 shared components → prerequisite for 36/37/38.
- Phase 36 → needs ADR-0018 + Phase 40.
- Phase 37/39 → need ADR-0019.
- Phase 38 → needs ADR-0019 + Phase 40.
- Phase 32 wizard → ADR-0017 (separate from this table; slice already
  tracked in PR #76).

## Total estimate

Phase 33–40 ≈ 107 person-days (single engineer), parallelizable per module.
