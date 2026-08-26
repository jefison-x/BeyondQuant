# Community Full Parity Plan（Phase 32–40）

Status: `COMPLETE`（2026-08-22；按适用范围 ADR-0017–ADR-0023 Accepted）

本计划描述 Phase 17–31 contract-first skeleton 延后的 Community product-depth workflows。`IMPLEMENTATION_PLAN.md` 是规范 phase plan，`STATUS.md` 标识 current/next phase，本文给出 parity batch overview/dependency map。

## Source of truth 与决策

- Community：`/home/jefison/projects/BeyondQuant-community/frontend`，只读并按 inspect → classify → port/refactor/replace。
- Current source：`apps/frontend`、`services/gateway`、`services/backend`、`services/mcp`、`services/runtime-adapter`。
- Gap inventory：`COMMUNITY_FEATURE_PARITY_GAP.md`、`COMMUNITY_FEATURE_PARITY_MATRIX_V2.md`。

截至 2026-08-20：Backtest wizard 使用预计算 `signal_snapshot` artifact（ADR-0017），不执行 strategy source；Agent cards 使用 versioned BYQ card contract、curated extraction/owner-scoped hydration（ADR-0018），raw DSH payload 不跨 Gateway，cards 无 executable actions；credentials 使用 PostgreSQL AES-256-GCM envelope/private resolution seam（ADR-0019），public reads masked、writes audited、scopes fail closed；cache 只表示 PostgreSQL market-data status，不加入 Redis；execution budget 是 DSH model-call token accounting；Stock Pool 为 mutable owner-scoped catalog 加 immutable content-addressed snapshots（ADR-0020）。

每 phase 一个 isolated worktree/branch/Draft PR 并停 human gate；frontend 只调 Gateway Product API；每 phase 要 Chrome DevTools MCP/Community checklist，无 fake data；coding 前分类 Community；先 contract tests。

## Phases

### Phase 32 — Backtest workspace depth

**COMPLETE（2026-08-18）**。PR #81/#82 通过 ADR-0017 `signal_snapshot` 交付 wizard；另有 result tabs、delete/compare/mobile/Chrome。Community `BacktestView.vue` 2730 lines。交付 list/filter/select/run/cancel/delete/compare、wizard、真实 equity/trades/logs/daily positions/returns/strategy snapshot/input manifest/mobile cards。Strategy source→snapshot producer（D-0002）移交 Phase 40。Classification：engine=`REPLACE`，wizard/compare=`PORT_UX`，result=`REFACTOR`。Estimate 16 person-days（L）。

### Phase 33 — Strategy workspace depth

**COMPLETE（2026-08-20，PR #85/#86）**。Community `StrategyView.vue` 1008 lines。交付 editor/templates/snippets、validation、durable draft save/delete、immutable version/export、approval banner、history、real backtest counts、read-only detail。D-0009–D-0012 移交 Phase 40。Estimate 10 person-days（L）。

### Phase 34 — Stock Pool depth

**COMPLETE（2026-08-21，ADR-0020）**。Community `StockPoolView.vue` 925 lines。交付 persisted typed catalog/detail、immutable member/weight snapshots、trusted index as-of/no-look-ahead、filter/provenance/reference、lifecycle/tombstone 和 responsive Product API。Estimate 14 person-days（XL）。

### Phase 35 — Paper Trading depth

**COMPLETE**。Community `PaperTradingView.vue` 597 lines。交付六个 persisted tabs、immutable settlement snapshots、order audit、versioned risk controls、complete ledger 和 validated BYQ asset bundles。Live brokerage 不在 scope。Estimate 9 person-days（M）。

### Phase 36 — Agent workbench depth

**COMPLETE（2026-08-22，ADR-0018）**。Community `AgentView.vue` 2057 lines 及 AgentThinking/Approval panels/Xiaoba drawer。交付 normalized actionable cards、有界 public activity/answer、local/global approvals、starters、responsive drawer；证据在 `docs/evidence/phase-36/`。Phase 36 拥有专用 components，Phase 40 仅可在验证后 generalize。Estimate 14 person-days（XL）。

### Phase 37 — My Space depth

**COMPLETE（2026-08-22，ADR-0019）**。交付 audited write-only encrypted credentials、profiles/private Agent binding、canonical digested asset re-import/new owner-safe IDs、effective policy presets/rule CRUD；证据 `docs/evidence/phase-37/`。Estimate 14 person-days（XL）。

### Phase 38 — Operations workbenches

**COMPLETE（2026-08-22）**。Community SystemMaintenanceWorkbench 4402 lines 加 Model/Graph/Runtime/Access/Data views。交付九个真实 Product API workbenches，覆盖有界 database/cache、model/Agent、budget/runtime/Graph、source readiness、access/audit。Data credential/sync execution 留 Phase 39；cache 无 Redis，budget 为 DSH token accounting。依赖 ADR-0019/ADR-0022。Estimate 27 person-days（XL）。

### Phase 39 — Data Center / Data Sync depth

**COMPLETE（2026-08-22）**。交付 Tushare-only source CRUD/test、durable sync jobs、coverage，并提供 Product API desktop/mobile evidence/checklist。依赖 ADR-0019。Estimate 11 person-days（L）。

### Phase 40 — Shared components + final parity closure

**COMPLETE（2026-08-22）**。交付 shared `AppStateBlock`/`EntityPagination`、经验证的 approval/assistant/model/operations components、deep strategy fields/projections 和 ADR-0023 isolated signal producer。关闭 D-0002、D-0009–D-0012；D-0003 经 zero-orphan audit 后 drop。证据含 no-mock two-user journey、desktop/mobile Chrome/checklist。Estimate 8 person-days（M）。

## Critical path、估算与完成定义

```text
Phase 40 shared components ─ complete under ADR-0023
Phase 32 backtest ─ result depth → wizard (ADR-0017)
Phase 33 strategy ─ independent
Phase 34 stock pool ─ independent
Phase 35 paper trading ─ independent
Phase 36 agent ─ ADR-0018
Phase 37 my space ─ ADR-0019
Phase 38 operations ─ ADR-0019 + ADR-0022
Phase 39 data center ─ ADR-0019
```

“Independent”只表示不依赖 ADR-0018/0019 和 Phase 40 components，不免除 `STATUS.md` 中 Phase 34 decision gate。总估算约 123 person-days（单 full-stack engineer，parallel modules 可压缩至 2–3 months）。完成要求 19 个 Community views/8 shared components 全部由真实 Product API、Chrome MCP evidence 和更新 parity matrix 表示，无 `MISSING` 或无法解释的 `PARTIAL`，之后按 `STATUS.md` 重新开放 v1.0 RC review。
