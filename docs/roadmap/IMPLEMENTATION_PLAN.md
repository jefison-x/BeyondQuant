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
