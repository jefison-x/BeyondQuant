# BeyondQuant Implementation Plan

这是 autonomous development 的 repository roadmap。普通 phase branch 只能实现当前 phase；后续 phases 是 planning constraints，不授权提前构建 Product scope。

从 Phase 9 起，永久 migration source of truth 为 `docs/migration/COMMUNITY_MIGRATION_INVENTORY.md`。实现 phase 前必须先检查、分类其 Community candidates。可在 BYQ-owned contracts 中重新实现 provider/engine-independent semantics，但不得复制 Community runtime、storage、provider 或 engine architecture。BaoStock、AKShare、VectorBT、PydanticAI 和 Hermes 保持排除，除非未来 Accepted ADR 明确反转。

所有 phases 遵循 `docs/DEVELOPMENT_WORKFLOW.md`：只执行 `STATUS.md` 指定的 next phase；每 phase 使用 isolated worktree/branch/PR；contract/test 优先；保持 Product/Agent/Quant/Data/Engineering boundaries；CI 与 evidence 完成后才进入 merge gate。

## Phase 6 — Runtime seam、ADR-0003 与 development framework

- **目标/范围**：验证 Gateway → Runtime Adapter → official DSH SDK → explicit DSH runtime seam；研究 official npm/PyPI rc.6；评估 Options A/B/C 并接受 ADR-0003；实现 Python/FastAPI Runtime Adapter 的 keyless initialize、MCP startup、lifecycle、normalization、internal SSE prototype 与最小 `WorkflowTraceEvent`；补 architecture/unit/contract/smoke CI 和 workflow docs。
- **边界**：dedicated Runtime Adapter；Gateway 无 DSH imports/raw events；domain access 走 BeyondQuant MCP；Product DSH coding capability 为 NONE；DSH persistence 留 Agent Plane；rc.6 exact-pin。无 public chat、frontend、real model turn、DSH fork/Web proxy/domain feature。
- **验收/停止**：ADR-0003 Accepted；initialize/MCP/cleanup 与全部 Phase 5/6 CI 通过，STATUS 指向 Phase 7。缺 official evidence、boundary violation、unreliable cancellation、要求 DSH fork 或 workflow stop 时停止。

## Phase 7 — First Product Agent Turn + WorkflowTrace

- **目标/范围**：经 accepted seam 交付第一个 authenticated Product Agent turn 和 BYQ-owned end-to-end WorkflowTrace；覆盖 model/provider secret、prompt flow、resume/interrupted、trace persistence/ordering 和 Gateway internal streaming。
- **边界**：Gateway 只见 BYQ envelopes；domain calls 走 MCP；Product DSH 无 coding/source-write；business state 归 BYQ。无 quant tools 扩展、frontend workflow UI 或 multi-agent research。
- **验收/停止**：真实 model-keyed turn 可从 Gateway→adapter→MCP→返回追踪；cancel/resume/secret tests 通过；keyless CI 无 secrets。发现 secret leakage、raw DSH 跨 Gateway、resume ownership 不清或需扩大 capability 时停止。

## Phase 8 — Data Provider Abstraction + Tushare

- **目标/范围**：引入 BYQ-owned provider contract 和安全 Tushare integration，定义 authentication/configuration、symbol/date semantics、rate limits、cache 和 provenance。
- **边界**：provider 属于 Data/Domain planes；DSH 只经 MCP 访问；不得直接访问 PostgreSQL。无 factor、strategy、backtest 或 agent credential autonomy。
- **验收/停止**：provider/Tushare contract tests、redacted fixtures、retry/rate limit、audit/provenance 通过。A-share semantics 模糊、cost 无界、secret 暴露或 provider 无法 contract-test 时停止。

## Phase 9 — ResearchTask + Experiment + Artifact

- **目标/范围**：定义 durable BYQ research entities、provenance、lineage、state transitions、idempotency、validation 和 MCP contracts。
- **边界**：domain invariants/business state 归 BYQ；DSH workflow state 与 artifact state 分离；artifact 是 auditable domain data。无 factor library、strategy runtime、backtest worker 或第二套 DSH state machine。
- **验收/停止**：versioned state/lineage 由 Backend 持久化，并经 MCP/contract tests 验证。ownership/provenance、DSH/domain state 或 idempotency 不清时停止。

## Phase 10 — Factor Research

- **目标/范围**：在 data/artifact 基础上建立 reproducible factor research。BYQ input boundary 必须覆盖 canonical A-share symbol/exchange/asset type；listing/delisting/suspension lifecycle；区分 missing/not-listed/delisted/suspended/boundary/non-trading；trading-session windows/lags；每 `(symbol, trade_date)` 一个 deterministic bar、duplicate policy、stable ordering、finite/OHLC validation；dataset identity/provenance/reproducibility/effective/announcement/`as_of`；point-in-time universe/index membership。
- **边界**：compute 在 BYQ workers/services；DSH 仅经 MCP propose/invoke；inputs/provenance immutable。Tushare 在 Data Provider Contract 后；不得引入 BaoStock、AKShare 或 Community provider engine。若 Phase 8 hardening 实现 duplicate/order/OHLC，只能限于 contract。
- **验收/停止**：deterministic fixtures、lifecycle/calendar/coverage、PIT/no-lookahead、provenance/lineage 可复现；input identity/visibility/coverage 模糊时不接受 factor。Look-ahead、undefined as-of、missing lifecycle/calendar、malformed bars 或 prompt-only invariants 时停止。

## Phase 11 — Strategy Artifact + Validation

- **目标/范围**：将 strategy code/configuration 表示为 validated、auditable domain artifact；定义 StrategyDraft/Artifact、immutable content-addressed StrategyVersion、validation evidence、approval gates、provenance、version/export 和 MCP。
- **边界**：version identity 来自 deterministic semantic snapshot/source fingerprint，排除 mutable timestamps；export 不含 credentials/runtime/Agent internals；validation、approval、execution outcome 分离。Strategy code 不是 application source，Product DSH 不写 repository，也不 unrestricted execute。
- **验收/停止**：invalid strategy 返回 contract error；versions immutable、replay 精确；exports deterministic/secret-free；evidence/approval auditable 且不把 approval 当 execution success。出现 source access、mutable version、secret export 或 unsafe execution 时停止。

## Phase 12 — Backtest Job + Worker

- **目标/范围**：以 durable isolated jobs 执行 validated strategy artifacts。BYQ native deterministic engine、A-share rules、frozen universe/version authorization、content-addressed input/result manifests、queue/state/retry/idempotency、resource bounds、object lifecycle/audit。
- **规则**：engine 明确测试 T+1、limit-up/down、suspension、lot size、fees、stamp tax、cash、corporate actions 和 stable blocked reasons。Manifest 冻结 signals/prices/status/actions/universe/version/engine/reproducibility。Result rows 仅存 namespace/object ID/media type/size/SHA-256 reference。
- **边界/验收**：worker independently deployable；DSH 不访问 storage/worker；VectorBT 不作为 dependency；owner/live-reference 决定 universe/deletion。Jobs isolated/restartable/idempotent/bounded；golden tests 覆盖 rules、manifests、retry、references 和 fail-closed deletion。Unbounded execution、mutable input、universe escape 或 unsafe artifact 时停止。

## Phase 13 — Quant Research Agents

- **目标/范围**：以 DSH presets/skills/subagents 增加 specialized roles，覆盖 tool permission、delegation、multi-agent trace、owner/actor authorization、human approval、audit 和 DSH correlation。
- **边界**：generic roles/orchestration 归 DSH；domain invariants、authorization、approval、audit、evidence promotion 归 BYQ 并经 MCP。无第二 generic harness、direct DB tools 或 Product Engineering privileges。
- **验收/停止**：least-privilege capabilities、isolation/E2E tests；audit 关联 owner/actor/DSH run/domain action/result/failure；approval failure 与 execution 分离；不能 bypass invariants/promote unreviewed evidence。Privilege escalation、duplicate BYQ invariants 或新 harness 时停止。

## Phase 14 — Quant Learning Loop

- **目标/范围**：闭合 research→experiment→artifact→validation→backtest learning loop，覆盖 evaluation signals、comparison、feedback lineage、repair/retry、evidence promotion 和 bounded iteration。
- **边界/验收**：每步 bounded、reproducible、auditable，经 BYQ contract；prompt 不替代 approval。Runs 有 budgets、stopping rules、human gates 和 replay；promoted lessons 保留 evidence/validation/review/provenance/history，chat 不能直接变 trusted knowledge。Unbounded autonomy、无 rollback/approval 或 feedback 不可复现时停止。

## Phase 15 — Engineering Plane / Code Improvement

- **目标/范围**：在不削弱 Product isolation 的前提下，支持 EngineeringTask、diagnostics、isolated worktrees、tests、Draft PR、CI evidence 和 human merge workflow。
- **边界/验收**：Product/Engineering privileges 分离；不 direct main push/merge、production deploy、destructive migration 或赋予 Product DSH source-write。EngineeringTask 可产出 tested Draft PR、architecture evidence、CI/self-review，并停 human gate。缺 isolation、privilege expansion、CI bypass 或要求 direct main 时停止。

## BeyondQuant Productization Program（Phase 16–23）

Phases 6–15 是 Headless Quant Research Platform Core，不等于 product completion。Phases 16–23 按以下顺序 productize：

```text
Product API + durable data → frontend shell → Agent workbench → Quant workspace
→ user/platform settings → Stock Pool/Paper Trading
→ operations/deployment → parity matrix/release candidate
```

Community 始终是只读 behavioral/visual evidence；不是复制架构的授权。

## Phase 16 — Product API / BFF + Durable Data Migration Foundation

- **目标/范围**：建立 browser-facing Gateway Product API/BFF、auth/session owner/actor、safe error、bounded pagination/filter/sort、versioned OpenAPI/TS types、dashboard/research/factor/strategy/backtest/approval/audit/Agent/WorkflowTrace/data-status projections；接受 Durable Market Data Storage ADR；设计 Community logical cache migration、manifest/validation 和 frontend inventory。
- **Migration invariants**：Community PostgreSQL read-only；仅 logical `SELECT`/`COPY OUT`/data-only export→validate/normalize→manifest→idempotent BYQ import→verify。禁止 physical directory copy/mount。只允许 proven `tushare` 或 provider-independent rows；排除 BaoStock/AKShare。验证 canonical symbols、`YYYYMMDD`、units、finite/OHLC、non-negative vol/amount、adjustment/asset/source、duplicates/order、lifecycle/PIT；invalid rows quarantine/report。Conflict policy 为 `KEEP_NEW`、`VERIFY_EQUAL`、`REPORT_MISMATCH`。
- **边界/验收**：frontend 只用 Product API，不暴露 MCP/DSH/raw events/tokens/storage schema；migration 可 dry-run 出 manifest/quarantine，Community 不变，不在 acceptance 中 bulk import。Ownership/auth、storage ADR、provenance、determinism 或 read-only 被破坏时停止。

## Phase 17 — Frontend Foundation

- **目标/范围**：创建 `apps/frontend` Vue 3+Vite+TypeScript，使用 Vue Router、Pinia、Element Plus、ECharts、typed client、OpenAPI types、Playwright。交付 shell/header/sidebar/mobile nav/router/auth bootstrap/design tokens/responsive/errors/loading/empty/toasts/dialog/chart；首批 Login、Dashboard、System Status、user menu。
- **边界/验收**：先检查分类 Community UI，复用 architecture-neutral visual language，重写 auth/API。Frontend 不直连 MCP/DSH/Backend/provider/database，也不依赖 raw events；core stack change 需 ADR。App boots、responsive states、Playwright CI 和 Community workflow-level review 通过；不得 wholesale copy。Direct coupling、missing auth ownership 或未经 ADR 换 stack 时停止。

## Phase 18 — Agent Research Workbench

- **目标/范围**：围绕 DSH、WorkflowTrace、ResearchTask、Experiment、Artifact、Approval 重设计 Community Agent UX；支持 session create/resume、conversation/stream/cancel/recovery、task/subagent/tool/domain visualization、trace、artifacts/evidence/approval/audit。
- **边界/验收**：browser 只收 normalized Product events，不显示 raw DSH/secret；唯一 path 为 Frontend→Product API→Gateway/Runtime Adapter→DSH/MCP。BYQ 拥有 domain state，DSH 拥有 generic session/orchestration。Core conversation/approval Playwright、stable replay/order 和 secret/raw-schema tests 通过。Raw event/browser DSH access、model identity/approval、unbounded stream 或 capability escalation 时停止。

## Phase 19 — Quant Workspace

- **目标/范围**：用真实 Product API 交付 ResearchTask/Experiment/Factor/Strategy/Backtest workspace。Factor 包含 definition/universe/date/compute/coverage/distribution/metrics/evaluation/lineage；Strategy 包含 draft/editor/validation/immutable version/approval/history/provenance；Backtest 包含 submit/state、equity/benchmark/drawdown/annual return/Sharpe/volatility/win rate、trades/positions/blocked reasons/fees/tax/artifacts/manifest/reproducibility。
- **边界/验收**：invariants 归 BYQ；strategy 是 domain artifact；results 为 immutable authorized references。ECharts states/large results tested；browser 可从 research 到 approved backtest，无 raw APIs/fake charts。Input identity/look-ahead/coverage、mutable history、unbounded results 或 excluded engine/provider 回归时停止。

## Phase 20 — User & Platform Settings

- **目标/范围**：Product API-backed Profile、Model Settings、Data Provider/Tushare capability、Agent Preferences、Approval Inbox、Assets、Storage/System Preferences。
- **边界/验收**：secret fields write-only/masked；browser 只收 `configured`、status/capability/permission/masked metadata，绝不收 `DEEPSEEK_API_KEY`、`TUSHARE_TOKEN`、`BYQ_PRODUCT_TOKEN`、MCP/bearer/decrypted credential。Settings 不授予 Operations/Engineering privilege。Owner isolation、audit 和 secret-boundary network/log/error tests 通过；secret exposure/privilege confusion/cross-owner/internal schema dependency 时停止。

## Phase 21 — Stock Pool & Paper Trading

- **目标/范围**：Stock Pool 支持 watchlists/research/candidates/tags/rankings/Agent recommendations/provenance/snapshot history；只复用 provider-independent semantics。Paper Trading 为独立 BYQ simulation domain，定义 portfolio/cash/positions/orders/fills/fees/tax/T+1/limits/suspension/lots/audit/version/provenance，无 live broker。
- **边界/验收**：paper 不是隐藏 Backtest engine；Product DSH 只经 MCP propose，mutation 受 BYQ idempotency/approval/owner/audit。Versioned pools、historical identity 和 simulation accounts/orders/fills/blocked reasons 真实；golden tests 覆盖规则，无 broker call。State conflation、missing invariants、non-deterministic fills 或 credential exposure 时停止。

## Phase 22 — Operations and Deployment

- **目标/范围**：role-protected、secret-safe、read-mostly Operations projection，覆盖 Gateway、Runtime Adapter、DSH、MCP、Backend、workers、provider、queues、object store、database、Redis、WorkflowTrace、audit、disk/migration；交付 production topology、volumes、backup/restore/migration、health、limits、logs、upgrade/rollback。
- **边界/验收**：operations permission 与 normal Product 分离；destructive actions explicit/audited/fail closed；DSH 不访问 business storage；services 独立升级隔离。Health/backup/real restore/migration procedures 可执行；logical Community migration repeatable/rollback-safe；observability 可关联 request/trace/DSH/domain/job/artifact/audit，不泄 raw events/secrets。Untested restore/destructive defaults/topology drift/unverifiable migration 时停止。

## Phase 23 — Community Feature Parity and BeyondQuant Next Release

- **目标/范围**：维护 `COMMUNITY_FEATURE_PARITY_MATRIX.md`，将每个 page/capability/component/dialog/chart/setting/operations surface 标记 `PORTED`、`REDESIGNED`、`REPLACED`、`DROP` 或 `DEFERRED`，并为每项给理由/target/acceptance。明确 PydanticAI/Hermes、raw Agent coupling、BaoStock/AKShare/VectorBT 被 drop/replace。
- **Product acceptance**：ordinary user 能完成 Login→Dashboard→小巴→ResearchTask/agents/WorkflowTrace→Tushare/cache→Factor→Strategy Draft/Version→human Approval→Backtest/charts/trades→Artifact/Evidence/Lineage→Stock Pool/Paper Trading→Settings→Operations，且 traceable/reproducible/auditable/secret-safe。
- **Golden gate**：Playwright 真实路径 `Login → Dashboard → 小巴 → ResearchTask → Factor → Strategy → Approval → Backtest → Result → Artifact → Stock Pool / Paper Trading`；CI 覆盖 API、secret、migration、responsive、architecture，最后停 human review。Missing journey/unresolved classification/failed secret-trace-restore 或 bypass human gate 时停止。

## BeyondQuant Product Completion Program（Phase 24–30）

Phase 23 只形成 Product Skeleton。Phases 24–30 每 phase 一 isolated worktree/branch/Draft PR/human review，UI phase 还需 Chrome MCP。Vue file/endpoint/placeholder 存在不等于完成；必须经真实 Product API/browser/persistence/states/checklist。

### Phase 24 — Durable User Identity & Authentication

以 BYQ-owned User/password hashing、Gateway username/password、secure HttpOnly session（或 ADR-approved equivalent）、logout/revoke/expiry/change-password、bootstrap admin、roles/disabled-user 和全资源 owner isolation 取代 Product Token browser login。Browser 表单不得使用 Product Token；该 token 仅 internal/service bootstrap。

### Phase 25 — Community Frontend Full UX Restoration

恢复熟悉 shell/navigation、real-data dashboard、shared cards/tables/pagination/dialogs/forms/status/empty/loading/error/charts；使用 BYQ contracts，并记录 Chrome MCP visual comparison。

### Phase 26 — Full Quant Workspace

交付真实 Factor create/compute/coverage/results/history；Strategy draft/editor/validation/version/history/approval/backtest links；Backtest create/status/retry/metrics/ECharts/trades/positions/blocked/fees/tax/manifest/lineage。禁止 fake metrics/charts。

### Phase 27 — Research、Artifact 与 Approval Center

可视化、管理 ResearchTasks、Experiments、Artifacts、Evidence、Lineage、Approvals；artifact browser 展示真实 metadata/hash/lineage/provenance 而不嵌大对象；Approval Inbox 支持 pending/approved/rejected 和 human decisions，并保持 execution outcome 分离。

### Phase 28 — Historical Market Data Migration & Data Center

执行 read-only Community audit 的真实 counts/date/symbol/source；完成 validation/normalization/quarantine/manifest/import/verification 且幂等；禁止 physical PG copy，BaoStock/AKShare/VectorBT 保持 DROP；Data Center 显示真实 datasets/coverage/sync/provider/quality/migration/quarantine/refresh，无 secrets。

### Phase 29 — Platform Administration & Operations Completion

交付 user/model/data/agent management、runtime operations、真实 backup/restore test，以及不泄 credential 的 logging/WorkflowTrace/audit/job-failure lookup。

### Phase 30 — True Community Feature Parity & BeyondQuant Next v1.0 RC

`COMMUNITY_FEATURE_PARITY_MATRIX_V2.md` 对每 feature 使用 `PASS`/`REDESIGNED_PASS`/`INTENTIONAL_DROP`/`FAIL`；release conclusion 无 `DEFERRED`；执行 Community Chrome comparison、无 mock/direct internal call 的真实 Product API golden journey 和 multi-user isolation E2E。Required item 缺失时不得完成。

## Phase 31 — PostgreSQL Single Domain Store（ADR-0016）

- **目标/范围**：以 PostgreSQL 作为唯一 BYQ domain-store engine。增加 `byq_domain`、`byq_domain_test`、`byq_bootstrap`；引入 `services/backend/app/db.py`（SQLAlchemy Core + psycopg），以 ResearchStore 为 pattern 迁移全部 stores；移除 SQLite/`BYQ_DOMAIN_DB_PATH`；提供 idempotent SQLite→PG logical migration（`KEEP_NEW`/`VERIFY_EQUAL`/`REPORT_MISMATCH`）、verification 和 `pg_dump`/`pg_restore` drill。LocalObjectStore 不变，不把 large blobs 存 PG。
- **边界/验收**：DSH/MCP/Gateway/Product boundaries 不变；Community PG 只读。全部 backend tests 使用 PG test DB，无 SQLite path，public store methods 不变；migration 幂等验证、restore drill/Compose/docs 通过。详细计划见 `docs/architecture/POSTGRESQL_MIGRATION_PLAN.md`。

## Phase 32–40 — Community Product-Depth Completion

这些 phases 延续 Product Completion Program；`STATUS.md` 只选择一个 next phase。每 phase 真实 Product API、owner isolation tests、Chrome MCP 和 Community checklist；mock-only Playwright 不是 acceptance evidence。详细清单/依赖见 `COMMUNITY_FULL_PARITY_PHASE_DETAILS.md`、`COMMUNITY_FULL_PARITY_PLAN.md`。

- **Phase 32 Backtest depth（`COMPLETE`）**：交付 `signal_snapshot` submit/wizard、result depth、compare/delete/mobile；producer 由 ADR-0017 排除并转 D-0002。
- **Phase 33 Strategy depth（`COMPLETE`）**：durable drafts、soft-supersede、immutable versions/history/counts/read-only、Product API/MCP/evidence；D-0009–D-0012 转 Phase 40。
- **Phase 34 Stock Pool（`COMPLETE`）**：ADR-0020 mutable identity/immutable snapshots/fingerprint/types/provenance/weights/lifecycle/references；五 detail tabs、`byq_pool_*`、evidence 在 `docs/evidence/phase-34/`。
- **Phase 35 Paper Trading（`COMPLETE`）**：六 tabs、T+1/cash ledger、immutable settlement、frozen pool、controls、order audit、digested bundles、Product API/MCP/E2E；无 live broker。
- **Phase 36 Agent workbench（`COMPLETE`）**：ADR-0018 curated cards/activity/answer、Gateway hydration、approvals/starters/Xiaoba drawer；evidence `phase-36/`。
- **Phase 37 My Space（`COMPLETE`）**：ADR-0019 encrypted credential lifecycle/private resolution、model binding、asset re-import/new IDs、policy rules/audit；evidence `phase-37/`。
- **Phase 38 Operations（`COMPLETE`）**：ADR-0019/0022 下九个 workbenches、`operations.v1`、normalized DSH usage、audited threshold；无 secret/raw events/SQL control/Redis；evidence `phase-38/`。
- **Phase 39 Data Center（`COMPLETE`）**：Tushare-only credential/test/durable jobs/PG import/coverage；BaoStock/AKShare DROP；evidence `phase-39/`。
- **Phase 40 parity closure（`COMPLETE`）**：ADR-0023 isolated producer；关闭 D-0002、D-0009–12，zero-orphan 后 drop D-0003；shared state/pagination/deep strategy；no-mock two-user/Chrome evidence `phase-40/`，重新开放 v1.0 RC gate。
- **Post-Phase 40 DSH Upgrade Lane（`COMPLETE`）**：Python `0.1.1rc1` + exact npm `0.1.1-rc.1` qualified，rc.6 rollback；不改 Product phase/capability。

## Post-parity Product Experience Program（Phase 41–48）

Maintainer 于 2026-08-23 延后 RC，选择 ADR-0024 conversation-first；详细 source 为 `FRONTEND_EXPERIENCE_PLAN.md`。

- **Phase 41 baseline（`COMPLETE`）**：接受 ADR-0024，分类 shell/session/theme/settings，固定 IA、conversation ownership、appearance contract、42–48 sequence/preview；不声称 implementation。
- **Phase 42 shell（`COMPLETE`）**：single-level sidebar/toolbar、Xiaoba default、current sessions、account menu/mobile drawer，保留 routes/admin；durable title 留 Phase 43。
- **Phase 43 conversations（`COMPLETE`）**：owner-scoped catalog、titles/lifecycle/search、restart-safe normalized replay、centered workspace。
- **Phase 44 user center/appearance（`COMPLETE`）**：consolidate Profile/Assets/Models/Policy/Paper；`ui-preferences.v1`、system/light/dark、closed accents/cross-device。
- **Phase 45 System Settings（`COMPLETE`）**：route-backed desktop dialog/mobile full-screen operations/Data Center，不弱化 RBAC/audit。
- **Phase 46 management redesign（`COMPLETE`）**：统一 Pool/Strategy/Backtest catalog/detail、deep links/charts/responsive，保留 domain invariants/results。
- **Phase 47 interaction/accessibility（`COMPLETE`）**：global states、unsaved changes、keyboard/focus/responsive/theme/chart matrix。
- **Phase 48 golden journey（`COMPLETE`）**：fresh no-mock two-user desktop/tablet/mobile journey 覆盖完整 Product；无 crossover/unexplained gap，修复 dark mobile selector contrast，Lighthouse Accessibility/Best Practices 100；human RC open/pending。

## Personal Workspace Tenancy Program（Phase 49–52）

Maintainer 于 2026-08-24 再次延后 RC，以 ADR-0025/`PERSONAL_WORKSPACE_TENANCY_PLAN.md` 建立 explicit personal workspace boundary。

- **Phase 49 boundary（`COMPLETE`）**：分类 Community tenancy；接受 ADR-0025/`personal-workspace.v1`；区分 user/workspace/platform/Engineering，固定 context/migration/rollback/future-team；不声称 schema runtime 完成。
- **Phase 50 foundation/backfill（`COMPLETE`）**：durable workspaces/memberships、atomic provisioning、nullable indexed keys、transactional dry-run/execute backfill；ambiguous rows quarantine/report；authorization 暂保持 owner-based。
- **Phase 51 authorization cutover（`COMPLETE`）**：session workspace resolution、browser-header stripping、Gateway→Runtime Adapter→DSH→MCP→Backend trusted propagation、membership fail closed、write stamping/mismatch rejection、workspace idempotency、31-table non-null；evidence `phase-51/`。
- **Phase 52 closure（`COMPLETE`）**：bounded workspace projection/orientation、bundle diagnostics/Paper not-found；fresh provisioning/restore/restart/forward repair，31 enforced tables、22 zero checks/no quarantine；two-workspace/Product/Chrome evidence `phase-52/`，无 team affordance。

## Beta Data Plane Completion（Phase 53–57）

- **Phase 53 Security Master（`COMPLETE`）**：ADR-0026 closed Tushare `stock_basic` L/P/D，atomic content-addressed snapshots/current catalog，bounded Product search/admin jobs；daily selection `explicit`/`selected`/`security_master`/`stock_pool`，真实 per-symbol incremental。无 ETF/index/fundamental/calendar/alternate provider。Evidence `phase-53/`。
- **Phase 54 Daily automation（`COMPLETE`）**：ADR-0027 Asia/Shanghai schedule、closed trading calendar、exact-date full-market daily snapshot、bounded catch-up/retry/lease、optional security refresh、independent `data-worker`、Product config/run-now/health/history；保留 manual/KEEP_NEW。无 suspension/limit/adjustment/action/benchmark/fundamental。
- **Phase 55 Data readiness（`COMPLETE`）**：ADR-0028 typed requirement manifest、session/lifecycle-aware coverage、bounded repair、`waiting_for_data`、immutable ready identity、exact suspension/status/limits；signal/backtest workers provider-free。Evidence `phase-55/`。
- **Phase 56 Adjusted research/actions（`COMPLETE`）**：ADR-0029 durable factors/implemented actions/effective dates；raw execution prices 不复权，构造 content-addressed research view；actions 冻结进 manifests，并测试 dividends/share ratios/false ex-right signals。Evidence `phase-56/`。
- **Phase 57 Benchmark/PIT/declared data（`COMPLETE`）**：ADR-0030 closed benchmark/index-weight/daily-basic/financial-indicator contracts、daily automation、bounded declared-input repair、immutable v3 readiness、historical membership/announcement no-lookahead、sandbox membership、frozen benchmark/excess performance。ETF/fund 排除；evidence `phase-57/`。

## Post-Acceptance Agent Completion（Phase 58）

- **Phase 58 Agent Domain Action Contract（`COMPLETE`）**
  - **目标/范围**：依据 ADR-0031 打通真实用户的候选股票 → owner-scoped custom Stock
    Pool → validated StrategyDraft/StrategyVersion。升级 BYQ role catalogue，仅为
    `quant_orchestrator` 增加 pool list/get/create；`market_researcher` 保持 evidence-only。
    对齐 MCP、DSH skill 与 Backend 的唯一 `CustomStrategy`/`data_requirements` schema，
    投影安全、有界、可修复的校验信息，并将同类 Domain validation 修正限制为一次。
  - **边界**：不增加 pool snapshot/lifecycle/delete、index/dynamic writer、数据工具、
    public-answer 重构、signal/backtest 语义或第二 Agent harness；不信任 Browser/model
    owner/workspace/provenance；Agent-to-Domain 仍只经 MCP，Backend 仍持有全部 invariant。
  - **验收/停止**：role/owner/workspace/audit contract tests、真实有效最小策略 MCP test、
    planned task validate→version integration、无 403/422 风暴的真实 Product Agent journey、
    Chrome DevTools/Playwright same-origin/secret-boundary evidence。出现 privilege widening、
    raw Backend/DSH leakage、无法安全投影错误、需要 direct DB/source access 或需要改动
    Phase 59/60 scope 时停止。

## Point-in-Time Agent Research（Phase 59–60）

- **Phase 59 persisted valuation/fundamentals read path（`COMPLETE`）**：ADR-0032
  定义最多 20 个 canonical A-share symbols 的 exact-session valuation 和
  announcement-next-day fundamentals reads；只读 BYQ PostgreSQL evidence，经 Backend
  与 MCP 返回 completeness/missing/hash，不调用 Provider、不填值。角色、MCP、完整
  Backend/MCP tests 和真实成功/缺失 Agent journey 均通过；evidence `phase-59/`。
- **Phase 60 public answer/activity projection（`COMPLETE`）**：以 Phase 59 真实旅程中
  英文内部前言、authorize/audit mechanics、raw coverage/field terminology 泄漏为基线；
  先接受独立 ADR，再在 Runtime Adapter/Gateway normalized projection 与 DSH skills
  边界修复。不得隐藏用户有价值的数据时点/失败原因，不得暴露 hidden reasoning、raw
  MCP/DSH schema，不得修改 Domain result 或引入第二 agent harness。

## Machine-readable phase status markers

以下稳定 markers 供 CI 校验 Phase ID 与完成状态；说明正文仍以各 program section 为准。

### Phase 34 — Stock Pool depth(`COMPLETE`)
### Phase 35 — Paper Trading depth(`COMPLETE`)
### Phase 36 — Agent workbench depth(`COMPLETE`)
### Phase 37 — My Space depth(`COMPLETE`)
### Phase 38 — Operations workbenches(`COMPLETE`)
### Phase 39 — Data Center / Data Sync depth(`COMPLETE`)
### Phase 40 — Shared components and parity closure(`COMPLETE`)
### Phase 41 — Product experience baseline(`COMPLETE`)
### Phase 42 — Conversation-first Product shell(`COMPLETE`)
### Phase 43 — Durable conversations and Xiaoba workspace(`COMPLETE`)
### Phase 44 — User center and durable appearance(`COMPLETE`)
### Phase 45 — System Settings dialog(`COMPLETE`)
### Phase 46 — Core management workspace redesign(`COMPLETE`)
### Phase 47 — Interaction, responsive and accessibility closure(`COMPLETE`)
### Phase 48 — Product coherence golden journey(`COMPLETE`)
### Phase 49 — Personal workspace boundary(`COMPLETE`)
### Phase 50 — Workspace foundation and verified backfill(`COMPLETE`)
### Phase 51 — Trusted context and authorization cutover(`COMPLETE`)
### Phase 52 — Product orientation and isolation closure(`COMPLETE`)
### Phase 53 — Security master and bounded synchronization(`COMPLETE`)
### Phase 54 — Daily market synchronization automation(`COMPLETE`)
### Phase 55 — Backtest data readiness and execution status(`COMPLETE`)
### Phase 56 — Adjusted research prices and corporate actions(`COMPLETE`)
### Phase 57 — Benchmark, point-in-time universe and declared data(`COMPLETE`)
### Phase 58 — Agent domain action contract(`COMPLETE`)
### Phase 59 — Agent point-in-time valuation and fundamentals(`COMPLETE`)
### Phase 60 — Public answer and activity projection(`COMPLETE`)
### Phase 61 — User experience acceptance closure(`COMPLETE`)

Phase 61 依据 ADR-0034 关闭专项验收中 Phase 58–60 后仍未关闭或仅部分关闭的问题。
范围限定为 Agent 长任务与调用预算、持久化日线口径、任务 readiness、Strategy/Backtest
普通用户信息层级、回测后续上下文、Login 浏览器语义、最近区间表达和完整黄金旅程复验。
基础 CRUD、登录和普通 API 只做 smoke，不机械重复既有 Evidence。

Browser 只访问 Gateway/Product API；Agent 日线只读 BYQ PostgreSQL，Provider 仅由 Data
Center/Data Worker 调用；内部 ID/manifest 不删除但降级到技术详情；不改审批、backtest
和 domain invariant，不新增 runtime/provider/broker。先完成 Community 分类和原验收报告
入库，再通过 Backend/MCP/frontend/DSH contract tests 与真实 Chrome/DevTools 黄金旅程。

### Phase 62 — User experience P3 polish(`COMPLETE`)

依据 ADR-0035 收口 Phase 61 后剩余非阻断体验项：Data Center 从 owner-scoped 股票池
snapshot 选择至多 20 只成分执行 readiness；普通工作台和导航清除首屏工程术语并统一
中文状态；ECharts 使用实际所需模块，消除回测相关大包 warning。保留管理员诊断术语和
全部审计详情，不改变 Backend/MCP/DSH/domain Contract。

验收包括 frontend 单元测试/build、默认 500 kB chunk gate、architecture、mock/real
Product browser smoke，以及真实 Data Center 股票池→readiness same-origin 旅程。Community
硬编码股票池、TODO API、假进度和旧 provider/runtime 路径全部 DROP。

## Phase 63 — DSH Plugin Registry + Qualification Framework (`COMPLETE`)

- **目标/范围**：依据 ADR-0038 建立 BYQ-owned、声明式、版本化的 Plugin Registry、
  qualification state、capability/risk metadata、独立 Agent assignment、exact manifest/lock
  validation、deterministic Composition Builder、profile/hash identity 和 qualification
  evidence。以 official Web Search、Guard、Compaction、Spill、Interaction 为首批真实样板。
- **边界/非目标**：不建设 Marketplace、用户上传、runtime `npm install`、hot install、
  extensions/self-modification、任意 package/URL/GitHub source、shell、terminal、filesystem
  mutation、coding/Engineering capability或数据库/provider直连。Frontend→Product API→
  Gateway→Runtime Adapter→DSH→BYQ MCP 不变；DSH plugin 不拥有 BYQ authorization/domain
  invariant。Web evidence 不成为 deterministic Factor/Strategy/Backtest input；spill 不成为
  Artifact/database；DSH interaction/approval 不替代 BYQ authorization。
- **验收/停止**：Registry schema 和 qualification runner 拒绝 duplicate/unknown/range/
  integrity/peer/rc-mixing/risk/capability/assignment 错误；Builder 稳定生成 composition、
  profile/hash/plugin/version identity，并拒绝 unqualified/prohibited/disabled escalation；
  Runtime Adapter keyless initialize、MCP/session/lifecycle、Agent Web least privilege、secret
  absence、architecture/unit/contract/security/integration tests 通过。单个 sample 因 runtime
  或 security boundary 失败时只标记 BLOCKED，不 fork/patch/upgrade/workaround。

## Post-Phase 63 development sequence

后续两个阶段固定按以下顺序推进：

```text
Phase 63  Plugin Registry + Qualification Framework（COMPLETE）
    ↓
Phase 64  Research Agent Web Search 深化（COMPLETE）
    ↓
Phase 65  DSH Plugin Center Admin UI（COMPLETE）
```

`STATUS.md` 仍是阶段授权的唯一事实来源。两个阶段不得并行，不得共用 worktree/branch/PR。Phase 64 必须
在 Phase 63 已完成且 Web Search 对当前精确 DSH baseline 保持真实 QUALIFIED 后才能获批；
Phase 65 必须等待 Phase 64 合并，并吸收其实际运行中形成的插件状态、证据和管理需求。

## Phase 64 — Research Agent Web Search 深化（`COMPLETE`）

### 目标

把 Phase 63 已 qualification 的 search-only DSH Web Search 转化为 Market Research Agent
可控、可追溯、时间安全的互联网研究能力。Market Research Agent 可以综合 BYQ MCP 的
结构化、已持久化数据与 Web research evidence；BYQ 继续拥有 evidence promotion、Artifact、
authorization、audit、point-in-time 和金融 Domain invariant。

正式实现前必须接受一份 Phase 64 ADR，确定网页 evidence schema、来源等级、冲突处理、
时间截点、Artifact promotion 与 retention。不得只靠 prompt 定义这些 invariants；若现有
Artifact 有界 JSON contract 不足以准确保存这些语义，应对既有 ResearchTask/Experiment/
Artifact contract 做版本化扩展，而不是新建第二套 Research Database。

### 范围

1. **搜索策略与预算**
   - 只在用户要求当前公开背景、新闻、政策、监管/交易所/公司公告，或 BYQ persisted data
     无法回答解释性问题时搜索；确定性计算和已由 BYQ structured data 完整回答的问题不搜索。
   - 每次 run 明确 query/result/retry/time budget、相同 tool+arguments 去重、相似查询收敛、
     domain/result 去重和停止条件；Repeat Guard 只能提供 advisory，BYQ/role policy 负责预算。
   - 中英文 query 按实体、地域和目标来源拆分；不得无条件把每个查询翻译后重复搜索。每个
     query 保存原始语言、目的及其与 evidence 的关联。
   - 搜索失败、无结果或预算耗尽时安全结束并如实说明，不循环、不扩大 capability。

2. **来源治理与 provenance**
   - 来源等级至少为：`PRIMARY`（监管、政府、交易所、公司法定公告/官方站点）、
     `SECONDARY`（可识别的专业财经媒体）和 `AUXILIARY`（论坛、自媒体及其他非权威来源）。
     未能可靠分类的来源不得伪装成官方来源。
   - 关键结论优先引用 PRIMARY；SECONDARY 用于补充报道与交叉验证；AUXILIARY 只用于线索和
     候选发现，不能单独支持确定性事实或因果结论。
   - 每条被采用 evidence 至少保留规范化 URL、标题、发布者/domain、发布时间（可缺失但必须
     显式）、检索时间、来源等级、query identity、provider/plugin provenance 和有界摘要。
     不保存 credential、raw DSH object、hidden reasoning、完整网页副本或任意 HTML。
   - 来源冲突必须并列呈现来源、时间和分歧；不能静默选择更符合模型结论的一条。

3. **时间语义与 no-look-ahead**
   - 明确区分 `published_at`、`retrieved_at`、research `as_of`、BYQ trading session 与
     persisted-data cutoff；缺失发布时间不能由检索时间或自然语言猜测补齐。
   - 历史 as-of 研究不得使用 as-of 后发布的内容支持当时可知结论。后来检索到的历史网页
     只有在其可见性与发布时间可证明时，才能作为该历史时点的辅助 evidence。
   - Web 页面、系统自然时间和模型记忆均不得推断交易日、公告生效日或数据可见性；这些语义
     继续来自 BYQ exchange calendar、announcement/effective-date 与 trusted time contract。
   - 当前 Web evidence 与 BYQ persisted-data cutoff 不一致时必须标记差异，不得写回或冒充
     Data Plane 的权威快照。

4. **Research Evidence / Artifact promotion**
   - DSH Web result 首先只是 session-scoped evidence candidate。需要持久化时，Agent 必须经
     既有 BYQ MCP、trusted owner/workspace context、authorization 和 audit 创建/关联有
     provenance 的 Research Artifact；Web plugin 本身不得直接访问 Backend 或数据库。
   - Artifact 明确区分 claim、supporting source、conflict、time context、检索失败和缺失字段，
     并保持 content hash、lineage、ResearchTask/Experiment 与 WorkflowTrace correlation。
   - Web evidence 只用于解释、研究和候选发现。未经 BYQ Data Plane 采集、规范化、PIT 校验、
     provenance 和冻结的数据，永远不得成为 Factor、Strategy calculation、signal snapshot 或
     Backtest deterministic input。

5. **Agent 融合与最小权限**
   - `market_researcher` 可读取 BYQ MCP structured data 并调用 `web_search`，在最终回答中清楚
     区分权威结构化数据、网页证据与推断。
   - `factor_researcher`、`strategy_researcher`、`backtest_analyst` 的 toolFilter 与执行限制
     均保持 Web Search DENY，不因 delegation、subagent inheritance、resume 或 profile 切换串权。
   - Phase 63 因 rc.1 root tool registry seam 显式允许 `quant_orchestrator` 看见 Web Search；
     Phase 64 必须将专业研究委派给 `market_researcher`，并验证 Coordinator 不自行扩大查询或把
     Web evidence 传成 deterministic input。若无法可靠约束 root capability，则停止并进入 DSH
     Upgrade Lane，不能创建 BYQ 第二工具运行时。
   - 搜索和 evidence promotion 不替代 `byq_agent_authorize`、owner/workspace、role、approval、
     idempotency 或 audit。

6. **防幻觉与公开回答**
   - Agent 只能基于本次实际检索结果与 BYQ structured data 陈述事实；不得用模型记忆补齐未查到
     的事件、数字、引用或因果链。
   - 无可靠来源、只有低等级来源、来源互相冲突或时点不成立时，必须明确说明“现有证据无法建立
     原因”及缺口，不得输出貌似确定的解释。
   - Product public answer/WorkflowTrace 只投影有界、用户可理解的来源卡片与结果摘要，不暴露
     query credential、raw tool arguments/results、raw DSH schema、内部 token 或 hidden reasoning。

### 非目标

- `web_fetch`、任意 URL 下载、浏览器自动化、通用爬虫/新闻平台或网页全文仓库；
- 用网页数据直接计算 Factor、Strategy、signal 或 Backtest；
- 新建第二套 Research Database、Artifact Store、search index 或通用 Agent harness；
- 让 DSH 直连 Provider、PostgreSQL、Redis、BYQ Backend，或由 Web Search 定义 Domain policy；
- 在本阶段升级 DSH、patch/fork upstream、扩大 Product filesystem/shell/code capability；
- Phase 65 Plugin Center、在线插件启停或任何 frontend 插件管理功能。

### 架构边界

```text
Frontend
  → Gateway / Product API
  → Runtime Adapter
  → DSH market_researcher
       ├─ qualified search-only web_search → bounded evidence candidate
       └─ BYQ MCP → structured data / authorized Artifact promotion
  → normalized public answer + WorkflowTrace projection
```

Browser 不接触 DSH；Web Search 不接触 BYQ domain storage；持久 evidence 只通过 BYQ MCP 与
Backend domain contract。DSH 决定 generic search/tool orchestration，BYQ 决定 capability 是否
允许、Agent assignment、证据是否可晋升、时间/数据可见性、authorization 与 audit。

### 验收标准

- Phase 64 ADR Accepted，versioned Web Research Evidence contract、source tiers、time fields、
  conflict/missing semantics、retention 和 Artifact promotion 均有 contract tests。
- Search policy 对需要/不需要搜索、中英文拆分、预算、完全重复和语义重复查询有 deterministic
  tests；重复或无结果不会形成无限 loop。
- 测试覆盖官方与媒体冲突、AUXILIARY-only、过期新闻、无发布时间、无结果、错误 trading-day
  推断、future-information rejection 和 persisted-data cutoff 冲突。
- Market Research Agent 可综合 BYQ MCP + Web evidence；Factor/Strategy/Backtest 在 visibility、
  direct invocation、delegation、resume 和 profile tests 中均无法访问 Web Search。
- Evidence/Artifact 保留 URL、title、publisher、published/retrieved time、source tier、query、
  provenance、hash/lineage/trace；确定性研究 input manifest 明确排除未晋升网页数据。
- keyless CI 验证 package/init/tool registration/policy/error contract；credentialed smoke 使用外部
  secret，真实执行 Web Search 并验证来源，不提交 secret、不把公网结果作为 golden fixture。
- 至少完成一条真实 Product Agent journey：durable login → Market Research request → BYQ
  structured data + credentialed Web Search → normalized sources/evidence → conversation resume；
  Network/WorkflowTrace/error/readiness 均无 secret 或 raw DSH schema。
- architecture、unit、contract、security、Product Agent integration、DSH compatibility、existing
  regression、`git diff --check` 全部通过；若影响现有 UI，按仓库纪律完成 Community 分类和
  desktop/mobile Chrome MCP review。

### STOP CONDITIONS

出现以下任一条件时停止对应路径，不 workaround：Web Search 不再对当前 exact baseline
QUALIFIED；需要启用 fetch/arbitrary URL、shell/filesystem/code runtime；无法可靠保留 URL/
时间/provenance 或隔离危险 capability；无法区分发布时间、研究 as-of、trading session 与
persisted-data cutoff；网页结果将进入 deterministic Factor/Strategy/Backtest；需要绕过 MCP、
authorization 或 Artifact contract；Agent assignment 可串权；需要用模型记忆补齐事实；secret、
raw DSH schema 或内部 token 可能进入 Browser/WorkflowTrace/log/error；需要混合 DSH prerelease、
fork/patch upstream 或建立第二 harness。上游变化只能触发 Upgrade Lane，不得在本阶段自动升级。

## Phase 65 — DSH Plugin Center Admin UI（`COMPLETE`）

### 目标与前置决策

将 Phase 63 稳定的 Registry/Qualification/Composition identity 以 admin-only Product surface
产品化，使管理员能查看真实插件状态、证据、风险和 Agent assignment，并通过受控变更请求
发起 enable/disable、assignment 和 qualification workflow。Plugin Center 是治理与部署状态
界面，不是 Marketplace、package installer 或 DSH runtime console。

Phase 65 已在 Phase 64 合并后完成。ADR-0040 已接受并明确新的
control-plane ADR，明确：

- Git-managed Registry/qualification evidence、期望 Product policy、generated composition 与
  当前运行 composition 各自的 authoritative source 和版本关系；
- admin change request 的 durable persistence、RBAC、idempotency、optimistic concurrency、
  approval/audit、worker ownership、失败状态与取消语义；
- 由哪个 trusted deployment/Engineering component 生成 policy snapshot、运行 qualification/
  builder/CI、构建 image、正常 deploy/restart、验证 active hash 并执行 rollback；
- 如何保证 Browser、Gateway、Backend 和 Product DSH 都不直接写 Git/source、执行 npm/shell、
  控制 Docker 或修改正在运行的 Cordis composition。

在该 ADR Accepted 前，Phase 63 的 Git-managed registry/profile 继续是唯一 deployment input；
不得先做一个看似可用、实际只改内存/数据库或直接改 runtime 的启停按钮。

### 范围

1. **Plugin Overview**
   - 展示 normalized DSH runtime version、active plugin profile、composition hash、enabled plugin
     IDs，以及 AVAILABLE/QUALIFIED/ENABLED/BLOCKED/REJECTED/DEPRECATED 计数。
   - 区分 desired、generated/validated、deploying 和 active runtime identity；仅在 Runtime Adapter
     readiness 报告匹配 hash/profile 后显示 Active。
   - update 状态只表达 verified upstream observation 与 compatibility/qualification 差异，不提供
     一键升级或自动下载；未知/过期 discovery 必须显式。

2. **Plugin Catalog 与 Detail**
   - Catalog 投影 plugin id/display name、official publisher、package、qualified/current/upstream
     observed exact version、qualification/enabled state、risk、capabilities、Agent assignments、
     credential configured boolean、compatibility/block reason。
   - Detail 展示 versioned qualification evidence summary、integrity/closure result、当前与上游版本、
     capability/risk reasons、allowed/denied agents、profile/composition membership 和最近 qualification
     request/result。证据链接/摘要有界、可审计且不泄内部路径或可执行配置。
   - 所有投影由 Gateway Product API 组合 BYQ services 的有界 contract；Browser 不解析 registry
     YAML、Cordis YAML、lockfile、raw DSH metadata/event 或 Runtime Adapter private response。

3. **Admin Actions**
   - 对已 `QUALIFIED` 且 risk/capability policy 允许的 registered plugin 发起 enable/disable change；
     对 descriptor 允许范围内的已知 Agent 发起 assignment change。请求之外的 package/version/
     capability/agent field 一律拒绝，不能通过 assignment 提升插件 capability。
   - 发起已登记 exact package/version 的 Qualification Request；请求只排队执行既有 qualification
     gates，结果不会自动 enable。unknown package、arbitrary version/source/URL/GitHub 均拒绝。
   - 所有 mutation 要求 durable admin session、expected version、idempotency key、actor、reason、
     append-only audit 和状态机；普通用户即使知道 ID 也不能读取 admin projection 或发起动作。
   - “Enable”在 UI 中必须表达为 deployment change request：

     ```text
     Product Policy request
       → validate registered/qualified/risk/assignment
       → deterministic composition generation + exact lock validation
       → normal CI/image build/deploy/restart
       → active profile/hash verification
     ```

     请求被接受不等于已 enabled；只有新 runtime 以目标 hash readiness 后才成为 active。失败保留
     旧 active composition，并展示有界失败原因和可审计 rollback 状态。

4. **Product UI**
   - 在既有 administrator System Settings/Operations 信息架构内增加 Plugin Center，而不是创建
     第二套 admin shell。实现前按 `AGENTS.md` 检查并分类 Community 对应页面/组件；没有对应物
     时记录 `REPLACE`/new BYQ surface，而不是臆造 Community parity。
   - 支持 desktop/mobile、loading/error/empty/stale/partial-unavailable、权限拒绝、长 package 名、
     状态/风险不可只靠颜色表达、危险动作确认和 deployment progress/recovery。
   - 所有 browser traffic 为 same-origin `Frontend → Gateway/Product API → BYQ services`；无
     Frontend→DSH/Runtime Adapter/Backend direct path。

### 非目标

- 开放 Marketplace、第三方开发者平台、评分/推荐/付费、用户上传或任意 package/source；
- runtime `npm install`、hot install/hot reload、GitHub URL、arbitrary Cordis YAML、DSH extensions/
  self-modification、自动 baseline/plugin upgrade；
- Browser/Gateway/Product Backend shell、terminal、Git/source write、Docker socket、code runtime、
  process control、任意 filesystem、database 或 provider access；
- 在页面读取/显示 credential value、environment secret、internal token、connection string、raw
  executable config、internal filesystem path 或 qualification command；
- 用 DSH approval 替代 BYQ admin authorization/deployment approval，或把 qualification success
  当作 enable/deploy success；
- 与 Phase 65 无关的完整 Operations/Marketplace 重构。

### 架构边界

```text
Admin Browser
  → Gateway Product API（durable admin RBAC）
  → BYQ Plugin governance projection / audited change request
  → trusted deployment control plane（ADR-defined, Product DSH 之外）
  → qualification + deterministic builder + CI/image/deploy/restart
  → Runtime Adapter readiness（active profile/hash）
```

Plugin Center 只管理 BYQ Product policy 允许的 registered generic capability。Plugin descriptor
不能定义 BYQ owner/workspace/role/domain authorization；Agent `toolFilter` 仍须镜像独立 assignment，
BYQ authorization 仍是 Domain ceiling。Credential 通过既有 encrypted store/reference 注入，只向
Browser 返回 `configured`/health boolean，不把 secret 放入 Registry、request、composition identity、
evidence、WorkflowTrace、audit、log 或 error。

### 验收标准

- Phase 65 control-plane ADR Accepted；versioned Plugin Center read/write Product API contract 明确
  desired/generated/active/request/result 状态，OpenAPI/typed client 与 secret-negative schema tests
  完成。
- Overview/Catalog/Detail 对 Phase 63/64 真实 registry、qualification evidence、runtime readiness
  和 update observation 投影准确；blocked reason、risk、assignments 与 credential configured 状态
  可解释，partial runtime failure 不伪造 healthy/active。
- duplicate/stale/idempotent admin requests deterministic；ordinary user/disabled user/cross-workspace
  被拒；audit 可关联 actor、request、old/new policy version、composition hash、deployment result，
  但不含 secret/raw config。
- AVAILABLE/BLOCKED/REJECTED/DEPRECATED、HIGH/PROHIBITED、unknown package/version/agent、invalid
  assignment 和 capability escalation 都无法进入 composition；disabled plugin 缺席，qualified +
  policy-enabled + valid assignment plugin 才出现。
- Qualification Request 执行 exact version/integrity/closure/runtime/capability/security gates；失败不
  自动升级、不自动 enable、不改变 active runtime。
- 完整 admin journey：登录 → Overview → Catalog/Detail → 发起允许的 policy/assignment change →
  观察 validation/deployment/restart → active hash 匹配；失败 journey 验证旧 composition 保持 active
  且 rollback/audit 可见。另有普通用户 403、two-user isolation 和 restart recovery。
- architecture tests 明确拒绝 online install、extensions、shell/terminal/source write、Docker/runtime
  direct control、frontend→DSH、MCP bypass、direct DB/provider 和 secret projection。
- Community feature classification、desktop/mobile Chrome MCP、loading/error/empty/stale、accessibility、
  real Product API Network review，以及 frontend/backend/unit/contract/security/integration/runtime/
  DSH compatibility/regression、`git diff --check` 全部通过。

### STOP CONDITIONS

出现以下任一条件时停止，不实现伪控制面或 workaround：Phase 63 Registry Contract 尚不稳定或
Phase 64 尚未合并；无法在 ADR 中确定 policy/qualification/deployment 的权威 owner；需要 Browser、
Gateway、Backend 或 Product DSH 直接执行 npm/shell/Git/Docker、写 source/YAML 或修改 running
runtime；enable 无法区分 requested 与 active；需要启用未 QUALIFIED、危险 capability 或越权 Agent；
需要 arbitrary package/version/source/URL；qualification metadata 无法准确验证；正常 build/deploy/
restart 或 rollback 不可审计；credential/raw config/internal path 可能泄漏；需要 DSH extension、fork/
patch、prerelease 混用、MCP/authorization bypass 或第二 generic harness。单个插件不兼容只进入
BLOCKED，不阻塞 Plugin Center 的只读治理能力。

## Stock Pool Producer Completion（Phase 66–69）

### Phase 66 — Trusted producer contract（`COMPLETE`）

接受 ADR-0041 和 `stock-pool-producer.v1`，冻结 definition/run/snapshot 分离、trusted Data Worker、
index no-look-ahead、closed dynamic rule、atomic promotion/recovery 和 Product intent boundary。完成
Community index `PORT_LOGIC`/`PORT_UX` 与 dynamic placeholder `DROP` 分类；本阶段不改 runtime。

### Phase 67 — Index stock pools（`COMPLETE`）

实现 validated canonical index catalog、owner-scoped index definition、持久化 materialization run、
trusted worker、import-trigger/manual idempotent refresh、as-of/history/diff Product API 和 responsive UI。
只开放 coverage 完整的 closed index set；不得从 Browser/股票池 service 直接访问 Provider。

### Phase 68 — Dynamic stock pools（`COMPLETE`）

实现 ADR-0041 closed rule schema、point-in-time preview、deterministic evaluator、交易日历 cadence、
waiting/stale/failure recovery、definition/run/history/diff Product API 和可访问 UI。不允许 arbitrary
Python/SQL/URL、DSH evaluator 或第二 rules harness。

### Phase 69 — Integration and product closure（`COMPLETE`）

统一 catalog/readiness/diff，验证 Research/Strategy/Backtest/Paper immutable snapshot 消费、资产导入
重新验证、监控/audit/restart/two-user isolation；完成 real Product API desktop/mobile Chrome、same-origin
Network、Community checklist 与完整 regression evidence。

### Phase 70 — Index catalogue coverage closure（`COMPLETE`）

依据 ADR-0042 将单一沪深300供给扩展为六个 canonical 候选的可信目录同步；Data Worker 以最多
62 日窗口逐指数隔离刷新。新增精确 snapshot-level completeness evidence 和旧数据 forward repair，
月度非空记录不再授权股票池。Product API/UI 展示可用与等待同步状态，只有 verified snapshot 可创建。
验收覆盖多指数、失败修复、no-look-ahead、完整 Compose、真实 Product API desktop/mobile Chrome、
same-origin Network、restart 和 Community checklist。

## Machine Learning Strategy Program（Phase 71–74）

详细合同和逐阶段 gate 位于 `MACHINE_LEARNING_STRATEGY_PLAN.md`，架构边界由 ADR-0043 固定。

### Phase 71 — Auditable ML contract baseline（`COMPLETE`）

检查并分类 Community 的 ML import、runtime probe、回测内训练与设计说明；接受 ADR-0043，冻结
ML StrategyVersion、TrainingRun、FeatureSnapshot、ModelArtifact、PredictionSnapshot 和现有
SignalSnapshot/Backtest 衔接合同。固定 Python 3.13 / LightGBM 4.7.0 CPU profile 和禁止项；
不改 runtime/schema/API/UI。

### Phase 72 — Trusted training and model artifact（`COMPLETE`）

实现 owner/workspace-scoped ML strategy validation/approval、TrainingRun、point-in-time
`price-volume-basic-v1` FeatureSnapshot、独立无凭证 LightGBM CPU Worker、native text model object、
ModelArtifact/metrics/lineage 和 restart/idempotency/tamper tests。不实现预测、信号、Backtest 或 UI。

### Phase 73 — Out-of-sample prediction and signal closure（`COMPLETE`）

实现 prediction-only inference、immutable PredictionSnapshot、确定性 ranking、approved closed top-N
policy → ADR-0017 SignalSnapshot，以及现有 Backtest approval/manifest 衔接。Backtest 不加载模型或
重新训练；验收 no-look-ahead、重复 identity、tamper 和 restart。

### Phase 74 — Product closure（`COMPLETE`）

实现 Gateway/Product API、typed client 和真实模型研究界面；完成 frozen pool → training → model →
prediction → signal → Backtest 的 PostgreSQL/Compose/two-user/restart/Chrome MCP/no-mock golden
journey。HIST 不在本阶段范围内，后续必须由新的 Accepted ADR 和明确授权启动。

## Product Agent Capability Completion（Phase 75–79）

架构边界由 ADR-0044 固定。五个阶段严格串行，每阶段使用独立 worktree、branch 和 PR。

### Phase 75 — Product capability contract baseline（`COMPLETE`）

建立 `product-capability-catalog.v1`，覆盖稳定用户路由、受众、前置条件、Agent 支持等级、MCP tool
映射和限制；CI 拒绝重复 identity、无效 route、未知 tool 与越权声明。本阶段不改 runtime/schema/API/UI。

### Phase 76 — Xiaoba product guide（`COMPLETE`）

实现精简 `byq-product-guide` skill、按领域 references、只读 `byq_product_help_query` MCP 和固定
Product route 投影。说明类请求不得产生领域 mutation；Production Product DSH 不挂载源码。

### Phase 77 — Backtest task facade（`COMPLETE`）

以 `backtest-task.v1` 聚合既有 ResearchTask、Approval、MarketReadiness、SignalProducerJob 和
BacktestJob，提供 prepare/create/execute/get/cancel MCP。不得新建第二工作流或让模型构造 raw bars/signals。

### Phase 78 — ML create and training Agent（`COMPLETE`）

增加最小权限 ML researcher role/skill/delegate 和 capability/workspace/strategy/training MCP；DSH 不训练、
不推理、不读取模型对象，策略批准保持人工边界。

### Phase 79 — ML prediction, frozen signal and Backtest conversation closure（`COMPLETE`）

增加 prediction/status MCP、封闭 WorkflowTrace 投影并接入 Phase 77 Backtest task；完成真实 PostgreSQL、
restart、two-user、no-mock Product API、desktop/mobile Chrome MCP 与说明/准备/执行行为评测。

### Phase 80 — Xiaoba data demand and automation-channel repair（`COMPLETE`）

修复 DSH delegate `toolFilter` 与实际 `mcp__byq__*` 注册名漂移；新增 `data-demand.v1`，由小巴用冻结
股票池、日期、用途和封闭数据声明向 Backend 表达按需准备需求。Backend 复用既有 repair/readiness，
Data Worker 独占 Provider 与行情写入；完成状态在下一次 Agent context 中通知小巴，并由 Product API
投影到数据中心。不得新增第二同步引擎、Provider 直连或 Backend 主动触发无用户回合的模型执行。

### Phase 81 — Durable conversation runtime rehydration（`COMPLETE`）

依据 ADR-0046 修复 Product durable conversation 在 DSH idle process release/reopen 后的首个 follow-up。
稳定 BYQ identity 与私有 DSH generation 分离；Gateway 从 durable catalog 提供 bounded completed public
messages，Runtime Adapter 在新 generation 第一次 prompt 恢复语义上下文。不得读取 raw DSH log、patch/
fork/upgrade DSH、无限保留 idle process 或重建第二 Agent harness。DSH error fail closed 为 failed，并以
Runtime/Gateway/Frontend contract、真实 release/reopen 多轮 Product journey、Chrome 与 cleanup evidence 验收。

### Phase 82 — Provider-aware scalable data tasks（`COMPLETE`）

依据 ADR-0047，将 50,000 单元明确为单个 readiness/repair 分片上限，而非 Tushare 或完整 ML
准备上限。ML 创建复用确定性分片和既有 repair/session job，单任务错误隔离且不再重启 Worker；Data
Worker 按配置的 Tushare 2,000 积分预算保守节流。新增由现有持久状态派生的 `data-task.v1` Product
投影和数据中心进度界面，展示阶段、完成/总单元、行数、失败原因与更新时间，不新增第二任务引擎。

验收必须覆盖 300 只×五年分片、单个坏任务不阻塞队列、重启恢复、额度单元测试、Gateway 安全投影、
真实 Product API/Chrome 桌面与移动端流程，以及 Community 功能清单。Browser 不得调用 Backend、MCP、
DSH、PostgreSQL 或 Tushare；Data Worker 仍是唯一 Provider caller。

## Extensible Machine Learning Program（Phase 83–86）

详细合同和逐阶段 gate 位于 `MACHINE_LEARNING_EXTENSIBILITY_PLAN.md`，架构边界由 ADR-0048 固定。

### Phase 83 — Extensibility contract baseline（`COMPLETE`）

检查并分类 Community ML 路径；接受 ADR-0048；冻结 capability registry、v2 strategy、v1 adapter、
purged walk-forward、Ridge profile、HS300 RegimeSnapshot、ModelBundle、RoutingPolicy 和 Product/Agent
边界。本阶段不改 runtime/schema/API/MCP/UI。

### Phase 84 — Capability registry, Ridge and walk-forward（`COMPLETE`）

实现代码管理与 CI qualification 的注册表、模块化 Feature/Target/Validation/Learner/Portfolio 合同、
v1 compatibility、Ridge JSON model 和 purged walk-forward Worker/Artifact；不实现 regime、routing 或 UI。

### Phase 85 — Regime snapshot, expert bundle and routing（`COMPLETE`）

实现冻结沪深300状态、专家模型包、fallback 和确定性路由；扩展 prediction/signal lineage，Backtest 继续
只消费冻结信号；不提前开放 Browser/Agent。

### Phase 86 — Product and Xiaoba closure（`AUTHORIZED`）

实现动态 capability Product API、模型研究 UI、MCP/Xiaoba 最小权限能力和真实 PostgreSQL/Compose/
Chrome/two-user/restart/performance 闭环。
