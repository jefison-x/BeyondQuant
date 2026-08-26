# Community Full Parity — Phase 33–40 Detailed Task Table

Status: `COMPLETE`（2026-08-22）。本文补充 `IMPLEMENTATION_PLAN.md` 和 `COMMUNITY_FULL_PARITY_PLAN.md`，记录 per-phase Community comparison、current state、gaps、dependencies、classification 和 estimates。

Legend：`REUSE_AS_IS`、`PORT_COMPONENT`、`PORT_STYLE`、`PORT_LAYOUT`、`PORT_UX`、`REFACTOR`、`REFERENCE_ONLY`、`REPLACE`、`DROP`。

## Phase 33 — Strategy workspace depth

- Status: `COMPLETE`（2026-08-20，PR #85/#86）。
- Community `StrategyView.vue`（1008 lines）：list/detail、Python editor、templates/snippets、validate/save/delete、backtest counts、history/read-only。
- Delivered：list/detail、editor insertion、validation、durable draft save/soft-supersede、immutable version/export、approval、history、real counts、read-only version。
- Follow-ups D-0009–D-0012 转 Phase 40；dependencies 为 Backend `strategy_draft` CRUD/history/count、Product routes、MCP `byq_strategy_draft_save`。
- Classification：editor/templates=`PORT_UX`；history=`REFACTOR`；validation=`REPLACE`。Estimate 10 person-days（L）。Exit criteria 已满足。

## Phase 34 — Stock Pool depth

- Status: `COMPLETE`（2026-08-21，ADR-0020）。
- Community visual baseline 索引于 `docs/evidence/phase-34/community-stock-pool/README.md`，仅 reference evidence，不替代真实 Product API gate。
- Community `StockPoolView.vue`（925 lines）：catalog、filters、create、members、index history、types、snapshots、weights、mobile、lifecycle。
- Delivered：owner-scoped paged catalog、五个 persisted detail tabs、immutable snapshots、weight validation、trusted/no-look-ahead index provenance、filter/reference、tombstone、frozen references、MCP、responsive UX。
- 关闭 persisted taxonomy/writer rules、member/weight editing、index as-of、filter/provenance、history、lifecycle、shared projections 七项 gap。
- Dependencies：ADR-0020、Backend CRUD/weights/snapshots/types、Product routes、`byq_pool_*`。Classification：catalog/member/snapshot=`REFACTOR`；weights/filter=`PORT_UX`；dialog=`PORT_COMPONENT`。Estimate 14 person-days（XL），exit 已满足。

## Phase 35 — Paper Trading depth

- Community `PaperTradingView.vue`（597 lines）：account、五 tabs、order detail、create/import、settlement、risk、transfer。
- Delivered：六 tabs、精确 T+1/cash ledger、immutable settlement、order audit、versioned risk、frozen pool binding、canonical new-ID bundle。
- Accepted contract 内无 gap；live brokerage 明确 out of scope。
- Dependencies：Backend snapshot/settlement/risk/import-export、Product routes。Classification：account/order=`REFACTOR`；settlement/snapshot/risk=`PORT_UX`；transfer=`REPLACE`。Estimate 9 person-days（M），exit 已满足。

## Phase 36 — Agent workbench depth

- Community `AgentView.vue`（2057）及 `AgentThinking`（155）、approval panels（385/300）、drawer（285）。
- Delivered：sessions/turn/resume/cancel、closed WorkflowTrace cards/activity、actionable cards、有界 progress、local/global approvals、starters、responsive drawer。
- 原九项 gaps 覆盖 drawer、thinking、approval panels、strategy/stock/optimization cards、tool visualization、starters，均已关闭。
- Dependency：ADR-0018/normalization。Phase 36 拥有 acceptance 所需 specific components，Phase 40 可后续 generalize。
- Classification：drawer/thinking=`PORT_COMPONENT`；cards/tool viz=`REFACTOR`。Estimate 14 person-days（XL）；2026-08-22 满足，证据 `docs/evidence/phase-36/`。

## Phase 37 — My Space depth

- Community：UserModels/SettingsPanel、UserAssets、UserAgentPolicy、UserProfile。
- 原 gaps：credential CRUD/binding、strategy/backtest re-import、policy presets/rule CRUD，均交付。
- Dependency：ADR-0019 和 Backend capabilities；Phase 37 拥有 model-settings component。
- Classification：credentials=`REPLACE`；asset bundle=`REFACTOR`；policy rules=`PORT_UX`。Estimate 14 person-days（XL）；2026-08-22 满足，证据 `docs/evidence/phase-37/`。

## Phase 38 — Operations workbenches

- Community 总计约 5700 lines：SystemMaintenance、Model、Graph、Runtime、Access、DataSource、DataSync。
- Delivered：九个 responsive workbenches 使用有界 Product API；budget writes/audit 真实，graph/runtime 使用 normalized BYQ contracts。Phase 39 负责 Tushare credential/test/sync。
- Decisions：cache=PostgreSQL status（无 Redis）；budget=DSH model-call tokens。Dependencies：ADR-0019/ADR-0022、Backend projections/RBAC writes。
- Classification：layout=`PORT_LAYOUT`；workbenches=`REFACTOR`+`PORT_UX`；access audit=`REPLACE`。Estimate 27 person-days（XL）；2026-08-22 满足，证据 `docs/evidence/phase-38/`。

## Phase 39 — Data Center / Data Sync depth

- Community DataSourceConfig/DataSync；初始 BYQ 只有 `DataCenterView` 和 status。
- Gaps：Tushare-only config、test、sync job、coverage，均关闭。
- Dependency：ADR-0019、Backend source/sync/coverage。Classification：config/sync=`REFACTOR`；cache=`REPLACE`；coverage=`PORT_UX`。Estimate 11 person-days（L）；2026-08-22 满足，证据 `docs/evidence/phase-39/`。

## Phase 40 — Shared components + final parity closure

- Community components：`AppStateBlock`、`EntityPagination`、approval panels、drawer、thinking、pool dialog、model panel、analytics、chart。
- Delivered：shared state/pagination、经验证 phase-specific components、deep strategy projections、ADR-0023 isolated signal production。
- 全部 transferred items 已关闭或明确 drop；no-mock two-user journey/Chrome evidence 在 `docs/evidence/phase-40/`。
- Classification：全部 `PORT_COMPONENT`（layout/style）+`REFACTOR`（BYQ Product API）。Estimate 8 person-days（M）；Status `COMPLETE`。

## Cross-phase dependencies 与总估算

Phase 40 shared components 只在明确声明时作为 prerequisite；Phase 36/37/38/39 分别在 ADR-0018、ADR-0019、ADR-0019+ADR-0022 下完成；Phase 32 wizard 依赖 ADR-0017。Phase 33–40 总估算约 107 person-days（单 engineer），可按 module parallelize。
