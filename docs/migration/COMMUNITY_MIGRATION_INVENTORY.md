# Community Migration Inventory

This document is the permanent migration source of truth for Phase 9 and
later domain work. It records what was inspected in
`BeyondQuant-Community`, what can be harvested, and what must not return to
the new BeyondQuant architecture.

## Audit scope and evidence

- Local reference: `/home/jefison/projects/BeyondQuant-community`.
- Local reference revision: `58dd99d` on `agent/workspace-community`; the
  working tree was clean during this audit.
- GitHub reference: `jefison-x/BeyondQuant-Community`, private repository,
  default branch `master`. GitHub repository metadata and representative files
  were verified through the connected GitHub app; the local checkout supplied
  the complete read-only source for semantic inspection.
- No file, branch, or history in the Community repository was modified.
- This audit is part of Phase 9 implementation discipline. It is not a new
  roadmap phase and does not authorize reverting the current Phase 9 work.

## Classification legend

- `REUSE_AS_IS`: safe, architecture-neutral asset that can be used without a
  semantic or ownership change. No Community production component qualified
  for this classification in this audit.
- `PORT_LOGIC`: port a proven invariant or algorithm into a BYQ-owned,
  framework-neutral implementation.
- `PORT_TESTS`: port the regression idea or fixture after adapting it to the
  current contracts and dependencies.
- `REFACTOR`: retain the domain meaning, but redesign storage, ownership, or
  integration boundaries before implementation.
- `REFERENCE_ONLY`: use to understand behavior or edge cases; do not port the
  implementation.
- `REPLACE`: the old component is superseded by the current BYQ/DSH boundary
  and must not be revived.
- `DROP`: explicitly excluded technology or implementation; no adapter,
  compatibility layer, dependency, or fallback may be added.
- `MIGRATE_WHERE_VALID`: data-only migration policy for a logical source
  dataset. It is not blanket acceptance: provenance, units, schema, coverage,
  point-in-time semantics, quality, conflicts, and manifest evidence must all
  pass before import.

## Global exclusions

The following classifications are permanent unless a future Accepted ADR
explicitly reverses them:

| Technology | Classification | Rule |
|---|---|---|
| BaoStock | `DROP` | Do not migrate its provider, adapter, dependency, fallback, or plugin. Provider-independent symbol, calendar, quality, and provenance semantics may be reimplemented against the BYQ Data Provider Contract and Tushare. |
| AKShare | `DROP` | Do not migrate its provider, adapter, dependency, fallback, or plugin. Provider-independent semantics and regression ideas may be adapted to Tushare. |
| VectorBT | `DROP` | Do not migrate the engine, adapter, registry entry, optional dependency, or fallback. Engine-independent result and metric semantics may be reimplemented in the BYQ-owned deterministic engine. |
| PydanticAI runtime | `REPLACE` | Generic runtime responsibility belongs to DSH and the current Runtime Adapter. Old runtime code is not a BYQ domain implementation. |
| Hermes runtime | `REPLACE` | Do not restore the old runtime or its coupling. Preserve only framework-neutral behavioral requirements. |

## Phase mapping

| Phase | Migration focus |
|---|---|
| Phase 8 | Provider-independent data contracts, symbol normalization, calendar, quality, provenance; Tushare is the current adapter. |
| Phase 9 | ResearchTask, Experiment, Artifact, provenance, state transitions, idempotency, validation, MCP contracts, and bounded audit metadata. |
| Phase 10 | Factor research, deterministic inputs, temporal/missing-data checks, and reproducible factor artifacts. |
| Phase 11 | Strategy Artifact, immutable strategy versions, validation, approval boundary, and strategy provenance. |
| Phase 12 | Native deterministic backtest job/worker, A-share execution rules, input/result manifests, object lifecycle, retries, and result artifacts. |
| Phase 13+ | Agent/learning/engineering workflows, audit views, approval policy, and DSH capability integration. |
| Phase 16 | Product API/BFF, durable market-data storage ADR, Community frontend mapping, and logical historical-cache migration design. |
| Phase 17 | Browser shell, auth UX, Product API client, Community visual/UX port, responsive and Playwright foundation. |
| Phase 18 | Agent Research Workbench, normalized WorkflowTrace/product events, ResearchTask/Experiment/Artifact/Approval UX. |
| Phase 19 | Quant Workspace for Factor, Strategy, StrategyVersion, Approval, Backtest, charts, metrics, manifests, and lineage. |
| Phase 20 | User Profile, Model/Data/Agent settings, Approval Inbox, Assets, Storage Status, and secret-safe capabilities. |
| Phase 21 | BYQ-owned Stock Pool and simulation-only Paper Trading product contracts and UX. |
| Phase 22 | Operations, deployment, observability, backup/restore, and production-safe migration operations. |
| Phase 23 | Community feature parity matrix, golden journey, release candidate, and explicit DROP/DEFER decisions. |
| Phase 31 | PostgreSQL single domain store: SQLite -> PostgreSQL logical migration, backup/restore, then ADR-0013 durable market-data import. |
| Phase 34 | Stock Pool identity/snapshot/lifecycle contract, historical membership, typed provenance, trusted index as-of behavior, and frozen consumer references. |
| Phase 37 | My Space model credentials/profiles/bindings, asset re-import, and Agent policy preset/rule UX under BYQ ownership and secret boundaries. |
| Phase 49 | Personal-workspace tenancy principles, trusted context, resource classification, owner-to-workspace migration and future team seam. |

## Productization frontend audit

The Community frontend was inspected before planning Phase 17+. The detailed
page/component mapping, observed layout and workflow behavior, API replacement
policy, and test obligations are in
[`docs/migration/COMMUNITY_FRONTEND_MIGRATION.md`](COMMUNITY_FRONTEND_MIGRATION.md).

| Area | Community evidence | Decision |
|---|---|---|
| Stack | Vue 3, Vite, Vue Router, Pinia, Element Plus, ECharts, Axios, Playwright, OpenAPI type generation | Keep the technical direction unless an ADR identifies a blocker. |
| App shell | `App.vue`, `AppLayout`, header, collapsible sidebar, mobile bottom navigation, separate operations shell | Port layout/style/UX; rewrite state/API/auth. |
| Agent | `AgentView.vue`, thinking/progress, assistant drawer, approval center, session history | Port conversation/result UX; replace old Agent API/SSE/event schema with BYQ Product API and WorkflowTrace. |
| Research | `HomeView.vue`, `StrategyView.vue`, `BacktestView.vue`, `DemoChartView.vue` | Port information architecture and chart/table interaction; rewrite domain/API bindings. |
| Stock pool | `StockPoolView.vue`, `StockPoolDialog.vue` | Port UX after domain invariant inspection; reimplement BYQ-owned snapshots/provenance. |
| Paper trading | `PaperTradingView.vue` | Port UX only; redesign separate BYQ simulation domain. |
| User/settings | profile, models, assets, Agent policy, model settings | Port forms/tables and safe states; replace auth/secret/approval APIs. |
| Operations | `frontend/src/views/operations/` | Port read-mostly information architecture; redesign topology, RBAC, secret safety, and controls. |
| Old coupling | `/agent-api`, raw/legacy Agent payloads, direct internal `/api/v1` calls | `REPLACE`; frontend must call Product API only. |

## Phase 34 Stock Pool decision audit

The mandatory Phase 34 sequence was completed before implementation:

1. **Inspect**: reviewed the read-only Community `StockPoolView.vue`,
   `StockPoolDialog.vue`, stock-pool model/service/routes, version service,
   backtest universe guard, manifest migration, and their contract tests.
2. **Classify**: retained only the provider/framework-independent invariants
   below; Community ORM, API, ownership, provider queries, and UI-to-old-API
   coupling remain refactor/reference evidence.
3. **Extract invariants/tests**: canonical membership, deterministic
   fingerprinting, immutable history, no-look-ahead index resolution, frozen
   universe authorization, and signal containment are required test intent.
4. **Decide**: ADR-0020 separates mutable identity from immutable snapshots,
   establishes typed provenance and tombstone lifecycle, and freezes all
   consumer references by snapshot ID.
5. **Implement**: permitted only in the next isolated Phase 34 worktree after
   ADR-0020 is merged.

| Community evidence | Classification | Phase 34 disposition |
|---|---|---|
| `frontend/src/views/StockPoolView.vue` | `PORT_LAYOUT` + `PORT_UX` | Use catalog/detail information hierarchy, type filtering, index history, lifecycle affordances, and responsive cards; bind only to BYQ Product API persisted projections. |
| `frontend/src/components/stocks/StockPoolDialog.vue` | `PORT_COMPONENT` + `PORT_UX` | Rebuild candidate/filter/member workflow on the BYQ snapshot write contract; do not copy old API/state architecture. |
| `backend/app/services/stock_pool_version_service.py` | `PORT_LOGIC` + `PORT_TESTS` | Preserve symbol normalization, dedupe/sort, deterministic fingerprints, no-op reuse, and append-only history. Exclude mutable name/description/activation from snapshot identity. |
| `backend/app/services/backtest_universe_guard.py` | `PORT_LOGIC` + `PORT_TESTS` | Freeze an immutable snapshot, reject competing universe selectors, and contain requested/signal symbols. Integrate with ADR-0008/0017 rather than copying the old service. |
| `backend/app/api/v1/stock_pools.py` | `REFACTOR` | Preserve typed catalog and index as-of UX semantics. Replace optional/legacy ownership, sample data, direct ORM/provider queries, and frontend-authored provenance. |
| `backend/app/models/stock_pool.py` and Alembic stock-pool migrations | `REFERENCE_ONLY` | Do not copy the detached-version schema or delete behavior; use ADR-0020 PostgreSQL identity/snapshot/member records and tombstones. |
| Community Tushare index cache | `REFERENCE_ONLY` / `MIGRATE_WHERE_VALID` | Read-only evidence. Phase 34 consumes only BYQ-validated Data Plane records; unproven rows are quarantined. BaoStock/AKShare remain `DROP`. |

Visual interaction evidence is indexed at
`docs/evidence/phase-34/community-stock-pool/README.md`. It is reference-only
and does not satisfy the Phase 34 real Product API Chrome MCP exit gate.

## Historical market-cache audit and migration policy

Community schema/model evidence identifies `market_data_daily`,
`market_adjustment_factors`, `market_trading_status`,
`market_corporate_actions`, `stock_universe`, `index_master`,
`index_constituent_weights`, and `security_name_history`, plus related
Tushare-derived research tables and sync state. The live cluster was not
available during this roadmap audit, so actual table existence, row counts,
source distributions, date ranges, and checksums remain Phase 16 work.

The detailed logical process and schema mapping are in
[`docs/migration/COMMUNITY_MARKET_DATA_MIGRATION.md`](COMMUNITY_MARKET_DATA_MIGRATION.md).

| Data/capability | Classification | Rule |
|---|---|---|
| Tushare historical daily bars and validated Tushare-derived canonical market data | `MIGRATE_WHERE_VALID` | Read-only logical export, source/unit/schema/quality/coverage validation, manifest, idempotent BYQ import, verification, and deterministic conflict policy. |
| Proven provider-independent canonical rows | `MIGRATE_WHERE_VALID` | Accept only with evidence of canonical symbols, units, dates, semantics, and integrity; otherwise quarantine. |
| Rows marked AKShare or BaoStock | `DROP` | Never migrate, adapt, or use as fallback. |
| VectorBT results/engine metadata | `DROP` | Engine-independent metric semantics may be reimplemented, but no engine or compatibility path returns. |
| Physical `Community/data/postgres` directory | `DROP` | Never copy, mount, open as BYQ storage, or use as authoritative data. |
| Community PostgreSQL | `REFERENCE_ONLY` source | `SELECT`/`COPY OUT`/data-only export only; never update/delete/alter/drop/truncate. |
| Community Redis (cache/agent runtime state) | `DROP` | No cache or runtime state is migrated; BYQ uses in-process TTL caching and PostgreSQL domain state, and DSH must not access Redis. |
| Community sync-state rows | `REFERENCE_ONLY` | Rebuild BYQ migration/refresh state; old flags do not prove canonical data validity. |

The target is a new BYQ Data Plane. Before any formal import, Phase 16 must
Accepted the Durable Market Data Storage ADR and complete a live read-only
audit. No data was migrated by the current roadmap change.

## Detailed inventory

### Research entities and lifecycle

| Component | Community source | Capability | Classification | Reusable invariants / algorithms | Reusable tests | Target | Migration status / notes |
|---|---|---|---|---|---|---|---|
| Research task and experiment contracts | `agent-service/app/research/contracts.py` | ResearchTask/Experiment schemas and state graph | `PORT_LOGIC` | A task is the root; experiments belong to a task; bounded text/JSON fields; completed experiments require metrics; terminal completion cannot be reopened; explicit retry is different from a normal transition. | `agent-service/tests/test_research_contracts.py` | Phase 9, then Phase 13+ recovery | Reimplemented in `services/backend/app/research.py` with BYQ-owned contracts. The richer evidence/review stages and Agent-run recovery are recorded for later adaptation, not copied into the Phase 9 state machine. |
| Research lineage repository | `agent-service/app/research/repository.py` | Persistence, owner-scoped lookup, task retry, experiment idempotency | `REFACTOR` | Task root lookup, parent ownership checks, explicit retry path, and durable timestamps are useful. The old repository's Agent Service ownership, direct SQL, `ON CONFLICT DO NOTHING`, and incomplete request-hash semantics are not reusable. | `agent-service/tests/test_research_contracts.py` | Phase 9 | BYQ Backend now owns persistence and stronger same-key/different-request conflict behavior. No old SQL or Agent Service repository code was copied. |
| Research contract tests | `agent-service/tests/test_research_contracts.py` | Transition and completed-result validation | `PORT_TESTS` | Preserve tests for illegal terminal transitions, required result metrics, evidence references, and explicit failed-run recovery. Adapt only tests compatible with ADR-0006. | Same file | Phase 9 / Phase 13+ | Applicable Phase 9 tests are already represented; review/approval and Agent-run recovery remain future candidates because Phase 9 does not implement approval. |
| Generic artifact workflow | `agent-service/app/services/artifact_workflow.py` | Draft/review/confirm/apply/approve/execute states and payload validation | `REFACTOR` | State transitions must be explicit and adjacent; target/page binding, date bounds, execution scope exclusivity, strategy fingerprint binding, and complete preflight coverage are proven semantics. | `agent-service/tests/test_artifact_workflow.py`, `agent-service/tests/test_artifact_adoption.py` | Phase 11 / Phase 12 | The old workflow is coupled to Agent artifacts, UI targets, approvals, and old backtest choices. Current Phase 9 keeps the smaller BYQ `draft → validated → superseded` artifact lifecycle. |
| Artifact adoption and approval recovery | `agent-service/tests/test_artifact_adoption.py`, `agent-service/app/services/approval_executor.py` | Human/agent approval and technical-failure recovery | `REFERENCE_ONLY` | Approval authorizes an attempted action, not successful business mutation; failures must remain auditable and retryable; child artifacts may remain under review until adoption. | Same test modules | Phase 11 / Phase 13+ | Not imported into Phase 9. Approval is explicitly outside ADR-0006 and requires a later domain decision. |

### Artifact identity, provenance, and storage

| Component | Community source | Capability | Classification | Reusable invariants / algorithms | Reusable tests | Target | Migration status / notes |
|---|---|---|---|---|---|---|---|
| Deterministic asset bundle | `backend/app/services/asset_bundle.py` | Export, manifest, object references, tamper verification | `PORT_LOGIC` | Canonical JSON; stable sorting; fixed ZIP timestamps; per-file SHA-256 and size; bundle identity hash; safe path validation; omit market data, credentials, runtime settings, and Agent artifacts. | `backend/app/tests/test_asset_bundle.py` | Phase 11 / Phase 12 | Valuable artifact/export logic, but it is not needed for the current Phase 9 entity CRUD contract. Reimplement behind BYQ artifact/object contracts. |
| Asset bundle regression tests | `backend/app/tests/test_asset_bundle.py` | Determinism, secret exclusion, missing-object and tamper rejection | `PORT_TESTS` | Same input produces byte-identical output; tampering or missing object references fail closed; secret values never enter an export. | Same file | Phase 11 / Phase 12 | Port test intent only; do not import the Community ZIP implementation wholesale. |
| Object lifecycle guard | `backend/app/services/object_lifecycle.py` | Ownership and live-reference deletion checks | `PORT_LOGIC` | Deletion requires matching owner scope and an authoritative live-reference query; a referenced object is retained; ownership must not be inferred from a path. | `backend/app/tests/test_object_lifecycle.py` | Phase 12 / Phase 13+ | Current Phase 9 has no delete/retention operation. Record for the future Artifact object lifecycle. |
| Research asset lineage | `docs/research_asset_lineage.md` | Strategy/stock-pool/dataset lineage and reproducibility status | `REFACTOR` | Lineage references immutable IDs and fingerprints; complete vs incomplete reproducibility is explicit; missing identity is recorded, never invented; provider secrets and prompts are excluded. | `backend/app/tests/test_backtest_input_manifest.py` | Phase 10–12 | Current Phase 9 already requires provider, endpoint, and request fingerprint in each input source and computes artifact content hashes. Future manifests must add typed fingerprints without importing Community storage. |
| Backtest input manifest | `backend/app/services/backtest_input_manifest_service.py` | Content-addressed input snapshot and missing-input reporting | `PORT_LOGIC` | Sort-independent dataset identity; stable canonical manifest ID; secret-free request/execution snapshots; explicit `reproducible`/`incomplete` status; environment and engine contract version metadata. | `backend/app/tests/test_backtest_input_manifest.py` | Phase 12 | Engine/provider-neutral semantics are reusable. VectorBT-specific fields and implementation are not. |
| Strategy version snapshots | `backend/app/services/strategy_version_service.py` | Immutable content-addressed strategy versions | `PORT_LOGIC` | Semantic snapshot excludes mutable timestamps; version ID is content-addressed; source fingerprint is deterministic; historical replay resolves the stored version, not the mutable current record. | `backend/app/tests/test_strategy_versions.py` | Phase 11 / Phase 12 | Future strategy artifact contract candidate. No strategy runtime or source-write capability is migrated. |
| Stock-pool version snapshots | `backend/app/services/stock_pool_version_service.py` | Immutable universe versions and membership fingerprint | `PORT_LOGIC` | Normalize symbols, deduplicate, sort, hash membership, append/reuse versions, preserve old versions after deletion. | `backend/app/tests/test_stock_pool_versions.py` | Phase 12 | Provider-independent universe semantics; must be integrated with the new BYQ data and strategy contracts. |

### Data and A-share semantics

| Component | Community source | Capability | Classification | Reusable invariants / algorithms | Reusable tests | Target | Migration status / notes |
|---|---|---|---|---|---|---|---|
| Provider-neutral data adapter behavior | `backend/app/core/data/provider_adapter.py`, `backend/app/tests/test_data_provider_adapter.py` | Symbol normalization, dataset manifests, order-independent fingerprints, empty-quality states | `PORT_LOGIC` / `PORT_TESTS` | Normalize `000001` to a qualified symbol; preserve provider/contract metadata; stable dataset IDs independent of input row order; distinguish empty from successful data; normalize calendar, status, names, corporate actions, and adjustment factors. | `backend/app/tests/test_data_provider_adapter.py`, `backend/app/tests/test_market_data_integrity.py` | Phase 8 / Phase 10–12 | Phase 8 already reimplemented the contract with Tushare. Community provider code is reference material only. |
| AKShare/BaoStock provider registry and adapters | `backend/app/core/data/provider_registry.py`, `backend/app/plugins/data/akshare.py`, `backend/app/plugins/data/baostock.py`, related requirements/docs | Legacy provider implementation | `DROP` | None of the provider implementation, dependency, fallback chain, or API-specific behavior is migratable. Only provider-independent semantics listed above may be reimplemented against Tushare. | Adapt normalization/quality tests only | None; semantic ideas go to Phase 8/10–12 | Explicit exclusion. No compatibility layer or plugin is allowed. |
| Native A-share execution rules | `backend/app/core/backtest/trade_simulator.py`, `backend/app/core/backtest_engines/native.py`, `backend/app/tests/test_backtest_golden_regression.py` | T+1, limit-up/down, suspension, lots, fees, stamp tax, cash and corporate-action behavior | `PORT_LOGIC` / `PORT_TESTS` | Trading constraints are domain invariants; blocked trades need stable reason codes; benchmark is not tradable; execution inputs must be frozen and reproducible. | `backend/app/tests/test_backtest_golden_regression.py`, `backend/app/tests/test_market_data_integrity.py` | Phase 12 | Harvest the rules and golden cases into the future BYQ-owned deterministic engine. Do not copy the old engine boundary or optional runtime. |
| Universe authorization guard | `backend/app/services/backtest_universe_guard.py` | Frozen pool scope and signal containment | `PORT_LOGIC` / `PORT_TESTS` | A backtest cannot mix a stock pool with a historical index universe; the active pool version is frozen; requested symbols must be a subset; strategy signals may not escape the authorized universe. | `backend/app/tests/test_backtest_universe_guard.py`, stock-pool version tests | Phase 12 | Future BYQ worker/domain contract. Not a Phase 9 artifact validation rule. |
| VectorBT engine and compatibility paths | `backend/app/core/backtest_engines/registry.py`, `backend/app/plugins/backtest/vectorbt.py`, `backend/app/core/vectorbt_engine.py`, VectorBT requirements and engine docs | Optional/legacy backtest engine | `DROP` | No engine code, registry entry, dependency, adapter, fallback, or comparison path may be migrated. | VectorBT tests are historical evidence only | None | The future engine is BYQ-owned Native/deterministic. Engine-independent metrics, schemas, and golden cases can be ported separately. |

### Jobs, results, audit, and integration boundaries

| Component | Community source | Capability | Classification | Reusable invariants / algorithms | Reusable tests | Target | Migration status / notes |
|---|---|---|---|---|---|---|---|
| Backtest job and retry semantics | `backend/app/services/backtest_job_service.py`, `backend/app/tests/test_backtest_jobs.py`, `backend/app/tests/test_backtest_job_worker.py` | Durable job state, resource limits, retry/idempotency | `REFACTOR` | Same idempotency key must not create duplicate work; owner scope matters; worker state and business result state are separate; retries need bounded resources and deterministic result references. | Backtest job, resource, worker, and result-object tests | Phase 12 | Reuse semantics only. The Phase 9 request-hash conflict rule is stricter than the old job behavior and should be retained. |
| Backtest result object storage | `backend/app/services/backtest_result_storage.py`, `backend/app/tests/test_backtest_result_object_storage.py` | Immutable result object reference and integrity metadata | `PORT_LOGIC` / `PORT_TESTS` | Store namespace/object ID, media type, size, and SHA-256; business records reference immutable objects rather than embedding unbounded result data. | Result-object storage/migration tests | Phase 12 | Future Artifact/result implementation; current Phase 9 remains bounded JSON only. |
| Approval policy and audit records | `agent-service/app/services/approval_policy.py`, `agent-service/app/services/approval_executor.py`, `agent-service/app/services/history.py`, approval tests | Policy evaluation, manual approval, actor/run/session correlation | `REFERENCE_ONLY` / `PORT_LOGIC` | Manual policy cannot be bypassed by a user rule; budgets and failure circuit breakers are bounded; approval is distinct from execution success; audit records correlate owner, run, session, action, result, and error. | `agent-service/tests/test_approval_policy.py`, `test_approval_executor.py`, `test_approval_workflow_recovery.py` | Phase 11 / Phase 13 | Implemented as a BYQ-owned, bounded agent approval/audit contract under ADR-0009. Community persistence and executor code were not copied. |
| Old Agent workflow state and persistence | `agent-service/app/workflows/contracts.py`, `agent-service/app/workflows/repository.py`, `agent-service/app/harness/*` | Graph checkpoints, leases, DSH run state, workflow recovery | `REFERENCE_ONLY` | DSH workflow state may correlate to BYQ entities but cannot own domain lifecycle, artifact state, or business idempotency. | Agent graph/workflow tests | Phase 13 | DSH native presets/skills/subagents are used for generic orchestration; BYQ stores only its own run, audit, approval, and domain records. Agent Service SQL/graph state was not migrated. |
| Old MCP gateway and server | `agent-service/app/tools/mcp_gateway.py`, `beyondquant-mcp/src/server.js`, MCP tests | Tool effects, normalized outcomes, timeouts, bounded diagnostics, trusted context | `REFACTOR` | Agent-to-domain calls go through MCP; tools should expose normalized capability contracts, bounded errors, stable idempotency context, and no storage details. | `beyondquant-mcp/test/tools.test.js`, MCP gateway tests | Phase 9 / Phase 13 | `services/mcp` now carries the Phase 13 agent boundary and trusted context forwarding. Old Agent Gateway/runtime coupling, direct internal endpoints, and raw schemas are not copied. |
| PydanticAI/Hermes and old runtime coupling | `agent-service/app/runtime/pydantic_ai.py`, runtime factory, Hermes migration docs, old gateway wiring | Legacy agent runtime/orchestration | `REPLACE` | None of the runtime implementation is a BYQ domain asset. Generic runtime belongs to DSH; BYQ owns only domain contracts and MCP capabilities. | Runtime tests are migration evidence only | None | Explicitly do not reintroduce PydanticAI, Hermes, old model gateway coupling, SSE coupling, or Agent direct database access. |
| Old frontend/Agent schema coupling | `frontend/*`, old Agent event and API contracts | UI integration with runtime-specific state | `REFERENCE_ONLY` | Frontend should consume BYQ Product API/WorkflowTrace contracts, not raw Agent event schemas or Agent persistence models. | Frontend contract tests are evidence only | Phase 17–23 | Current architecture boundary supersedes the old coupling; Community visual/UX behavior is mapped for port/redesign, while API/event/state ownership is replaced. |

## Phase 13 migration audit

The mandatory Phase 13 sequence was completed as: inspect the Community role,
approval, workflow, and MCP implementations; classify them as reference or
refactor material; extract bounded authorization, delegation, approval, and
audit invariants; then implement those invariants in BYQ contracts and DSH
configuration. No Community runtime, repository, or SQL schema was copied.

| Capability | Community evidence | BYQ/DSH implementation | Decision |
|---|---|---|---|
| Least-privileged quant roles | `agent-service/app/harness/roles.py`, `tool_policy.py`, `skills.py` | `services/backend/app/agent_research.py`, `plugins/dsh-byq/skills/`, and official DSH child tool filters | Reimplement the role contract; use DSH primitives for generic composition. |
| Delegation and bounded recursion | `agent-service/app/harness/workflow.py`, workflow tests | BYQ parent/child allowlist plus official in-process spawn provider with `maxDepth: 1` | Preserve the invariant; drop old workflow persistence. |
| Owner/actor authorization | `agent-service/tests/test_actor_context.py` and gateway tests | Gateway → Runtime Adapter → MCP trusted context headers; BYQ owner-scoped run checks | Reimplement at the integration boundary; never trust model identity fields. |
| Human approval and execution outcome | `approval_policy.py`, `approval_executor.py`, approval tests | `agent_approvals`, normalized MCP approval tools, self-approval rejection, separate outcome | Port semantics only; do not port Community executor/runtime. |
| Audit correlation | `history.py`, recovery tests | `agent_audit` with owner, actor, trace/session/DSH run correlation and bounded details | Reimplement as a BYQ view; DSH events remain outside domain storage. |

## Phase 14 migration audit

The mandatory Phase 14 sequence was completed as: inspect the Community
evidence compaction, bounded execution profiles, retryable error
classification, and deterministic trajectory evaluation contracts; classify
them as reference or port material; extract bounded iteration, feedback
lineage, and evidence-promotion invariants; then implement those invariants
in BYQ-owned learning contracts.

| Capability | Community evidence | BYQ implementation | Decision |
|---|---|---|---|
| Bounded agent budgets and repair/retry policy | `agent-service/app/harness/limits.py`, `agent-service/app/harness/errors.py` | `services/backend/app/learning_loop.py` budgets and ordered retryable iterations | Port semantics only; no Community runtime or prompt execution is copied. |
| Deterministic evaluation and replay evidence | `agent-service/app/evals/research_replay.py`, eval fixtures | `evaluation_signals`, deterministic `compare_experiments`, ordered iteration history | Reimplement as a BYQ contract; never trust model output as a signal without a validated artifact. |
| Evidence compaction and secret redaction | `agent-service/app/harness/output.py` | bounded JSON validation and recursive secret-key rejection in learning payloads | Port the invariant; old Agent Service persistence is not copied. |
| Promotion/review provenance | `agent-service/app/services/approval_policy.py`, history tests | `lessons` state machine and ordered `learning_history` records | Port semantics only; BYQ owns promotion state and human review. |

## Phase 15 migration audit

The mandatory Phase 15 sequence was completed as: search the Community
repository for EngineeringTask or Engineering Plane task implementations and
find none. Phase 15 is therefore a new BYQ-owned contract, not a migration.
The BYQ implementation records isolated worktree, branch, Draft PR, CI,
self-review, and architecture evidence gates; Community has no reusable
EngineeringTask asset and none was copied.

## Current Phase 9 comparison

### A. Correctly reimplemented

- BYQ-owned ResearchTask, Experiment, and Artifact persistence is in the
  Backend, not Agent Service.
- Current IDs, bounded JSON, canonical content SHA-256, typed lineage roots,
  owner metadata, versions, and trace correlation are enforced by BYQ.
- Create and transition retries use canonical request hashes and return the
  original result; a changed request with the same key conflicts.
- The Phase 9 state machines intentionally exclude Community's approval and
  UI workflow states.
- MCP exposes normalized capabilities and hides SQLite, SQL, internal rows,
  DSH event schemas, and secrets.

### B. Duplicate implementation assessment

No current Phase 9 implementation was rolled back. The old research repository
looks superficially similar, but its Agent Service ownership and direct SQL
make it a different architecture. Current BYQ code is a deliberate
reimplementation with stronger request-hash conflict semantics and a durable
transition result ledger.

### C. Community invariants checked for omission

- immutable snapshots must be content-addressed and must not use runtime time
  or manually invented fingerprints;
- reproducibility must be explicitly `incomplete` when an input identity is
  missing;
- sensitive keys must be rejected recursively, including key-name variants;
- artifact/object exports must omit credentials, runtime settings, and Agent
  internals;
- object deletion must require owner equality and no live references;
- a frozen universe and strategy version must be used for future backtests;
- A-share execution constraints need stable reason codes and golden fixtures;
- approval authorizes an attempt but does not prove successful execution.

The first three items are relevant to the current Phase 9 boundary. The
recursive sensitive-key rule is ported in the current Phase 9 change and has
a regression test. The remaining items are future-phase contracts, not reasons
to widen or reset Phase 9.

### D. Reusable tests

The inventory above identifies the source tests. The current Phase 9 test suite
retains the applicable ideas for persistence/reopen, lineage, content hashes,
idempotent replay, request conflicts, secret rejection, invalid transitions,
MCP normalization, and storage-boundary architecture checks. Future tests must
be adapted to the Tushare contract and BYQ-owned Native engine; Community test
files are not copied verbatim.

### E. Architecture-conflicting components

Agent Service direct business SQL, old runtime state, PydanticAI/Hermes,
provider plugins, VectorBT, frontend dependence on Agent schemas, and Agent
direct database access are `REPLACE`, `REFERENCE_ONLY`, or `DROP` as marked
above. None is required for Phase 9. No Accepted ADR must be broken to harvest
the recorded domain semantics.

## Newly discovered invariants and future candidates

- Phase 10: deterministic factor-input identity, missing/temporal-data status,
  no look-ahead, and reproducible factor artifacts.
- Phase 11: immutable StrategyVersion snapshots, script/content fingerprints,
  validation evidence including static strategy-safety checks, artifact export
  hygiene, and approval as a separate state machine. The static checks include
  synchronous output methods, no historical-loop model fitting, and the
  supported PortfolioState field contract; execution-output validation remains
  a future BYQ-owned worker concern.
- Phase 12: A-share T+1/limit/suspension/lot/fee/tax rules, frozen universe
  authorization, content-addressed input/result manifests, bounded worker
  retries, object references, and unreferenced-object deletion.
- Phase 13+: owner/actor authorization, human approval, audit views, DSH run
  correlation, and learning/evidence promotion.

No Community finding requires a Phase 9 reset, a new phase, a new worktree, a
main-branch change, or reintroduction of an excluded technology.

## Audit status

- `REUSE_AS_IS`: no qualifying Community production component found.
- `PORT_LOGIC`: recorded above; the recursive sensitive-key rule was ported in
  Phase 9, while domain-specific future logic remains mapped to its target.
- `PORT_TESTS`: recorded above; applicable current tests were adapted, future
  tests remain candidates.
- `REFACTOR`: old persistence, workflow, job, and MCP boundaries require
  redesign before reuse.
- `REFERENCE_ONLY`: old runtime/workflow/approval/frontend behavior is context,
  not implementation source.
- `REPLACE`: old PydanticAI/Hermes/runtime coupling is superseded by DSH and the
  current Runtime Adapter.
- `DROP`: BaoStock, AKShare, VectorBT and all associated compatibility paths.

## Phase 8 retrospective Community reuse audit

This retrospective was performed after the Phase 8 merge. It does not change
the Phase 8 architecture, roll back PR #5, or reimplement the Tushare
provider. The comparison baseline is the current BYQ adapter at
`services/backend/app/data_provider.py` and the Community reference at commit
`58dd99d`.

The requested Community path
`backend/app/core/data/market_coverage_service.py` does not exist. The actual
reference is `backend/app/services/market_coverage_service.py`; that path is
used below. The other requested paths were inspected as provided.

### No-change decisions

| Phase 8 capability | Current evidence | Decision |
|---|---|---|
| BYQ-owned provider boundary and normalized JSON transport | `services/backend/app/data_provider.py`, ADR-0005 | Keep. The Community `tushare` SDK adapter and SQLAlchemy/Pandas service boundary are not copied. |
| Canonical request shape and bounded request cost | `DailyRequest.normalized()`, `docs/contracts/data-provider.md` | Keep. Canonical `NNNNNN.SH/SZ/BJ`, exact date or bounded symbol range, bounded rows, retries, and cache are deliberate Phase 8 decisions. |
| Raw unadjusted daily bars | `DAILY_FIELDS`, `DailyBar`, ADR-0005 | Keep. Adjustment and execution-specific inputs remain later contracts. |
| Secret boundary and request-level provenance | `TushareConfig`, `Provenance`, `TushareProvider` | Keep. Token redaction, request fingerprint, retrieval time, cache state, and row count are correct foundations; Phase 10 must add dataset/input identity without exposing secrets. |

Community's short-symbol heuristic (`000001`, `sh000001`, and
`sz000001`) is evidence for a future BYQ canonicalizer, not a reason to relax
the accepted Phase 8 boundary. The heuristic's prefix fallback can silently
misclassify symbols and must not be copied as-is.

### Provider-independent semantics and migration classification

| Community source | Domain capability | Current Phase 8 finding | Classification | Target / status |
|---|---|---|---|---|
| `backend/app/core/data/providers/tushare.py:22-58`; `backend/app/core/data/backtest_datasets.py:223-236` | A-share symbol normalization and exchange/asset semantics | Current requests accept only already-qualified symbols and do not expose provider-independent stock/index/ETF classification. | `PORT_PHASE10` | Add a BYQ-owned canonical symbol/security contract before factor universes are built. Keep the Phase 8 strict boundary until that contract is accepted; do not port prefix heuristics blindly. |
| `backend/app/core/data/providers/tushare.py:163-177`; `backend/app/services/market_coverage_service.py:69-127` | Listing/delisting lifecycle | Phase 8 daily bars have no security master, `list_date`, `delist_date`, or status-aware valid lifespan. | `PORT_PHASE10` | Required for factor-universe membership and historical eligibility. `BLOCKER_BEFORE_PHASE10` unless Phase 10 explicitly consumes an equivalent BYQ lifecycle snapshot. |
| `backend/app/core/data/providers/tushare.py:391-402`; `backend/app/core/data/market_data_repository.py:888-940` | Suspension/resumption semantics | Phase 8 does not provide daily trading-status or suspension events. Community distinguishes suspension from resumption and preserves timing/type. | `PORT_PHASE10` | Port the invariant and stable status reason codes to factor coverage first, then reuse them in the native execution engine. `BLOCKER_BEFORE_PHASE10` for any factor that treats a missing observation as a return/data failure. |
| `backend/app/services/market_coverage_service.py:34-193,199-276,336-373` | Missing bar is not automatically missing data | Phase 8 has no lifecycle- and suspension-aware coverage assessment. | `PORT_PHASE10` | Coverage must classify not-listed, delisted, suspended, boundary, and genuine missing-data cases. `BLOCKER_BEFORE_PHASE10`. |
| `backend/app/core/data/providers/tushare.py:636-650` | Trading-calendar semantics | Phase 8 validates calendar-date syntax only; it does not identify open trading sessions. | `PORT_PHASE10` | Factor windows and lag rules must operate on trading sessions, not naive calendar-day offsets. `BLOCKER_BEFORE_PHASE10`. |
| `backend/app/core/data/providers/tushare.py:590-611`; `backend/app/core/data/backtest_datasets.py:258-296` | Duplicate daily bars and deterministic ordering | Current `DailyResult` preserves provider row order and does not define a `(symbol, trade_date)` duplicate policy. Community de-duplicates paged ETF snapshots and sorts downstream frames, but only part of the rule is explicit. | `PORT_NOW` | Recommend a small Data Contract hardening PR before Phase 10: define reject-vs-last-write behavior for duplicate keys, canonicalize rows, and sort by symbol/date. No Phase 8 rewrite is needed. `BLOCKER_BEFORE_PHASE10` until the contract is enforced by the Phase 10 input boundary. |
| `backend/app/core/data/providers/tushare.py:613-634`; `backend/app/core/data/market_data_repository.py:711-819` | OHLC and data-quality validation | Current code checks fields and converts numeric values, but neither current nor Community code fully defines finite values, `high/low` relationships, or duplicate conflict handling. | `PORT_NOW` | Recommend the same small hardening PR to reject malformed bars before factor computation. This audit found a contract gap, not evidence of already-corrupt persisted Phase 8 rows. `BLOCKER_BEFORE_PHASE10` for unvalidated factor inputs. |
| `backend/app/services/market_coverage_service.py:199-334` | Coverage completeness and bounded backfill | No Phase 8 coverage service exists; Community provides gap classification, lifecycle-aware boundaries, and bounded repair. | `PORT_PHASE10` | Factor input preparation needs read-only coverage assessment; durable repair/backfill belongs with the future Phase 12 Data Worker/backtest data pipeline. |
| `backend/app/core/data/providers/tushare.py:303-342`; `backend/app/core/data/market_data_repository.py:403-446` | Provenance and point-in-time fundamental data | Current provenance identifies the request, not an effective data snapshot or announcement-visible version. Community retains `ann_date` and filters by `as_of_date`. | `PORT_PHASE10` | Factor inputs need effective-date, announcement-date, dataset identity, and reproducibility status. `BLOCKER_BEFORE_PHASE10` whenever a factor uses fundamentals or other revised data. |
| `backend/app/core/data/backtest_datasets.py:104-221,298-368`; `backend/app/core/data/market_data_repository.py:647-680` | Point-in-time index membership and look-ahead prevention | Phase 8 has no index-universe or as-of contract. Community chooses the latest membership snapshot visible on the research date and records snapshot metadata. | `PORT_PHASE10` | Port the rule into factor input snapshots first and reuse it in Phase 12 native backtest manifests. `BLOCKER_BEFORE_PHASE10`. |
| `backend/app/core/data/backtest_datasets.py:34-67,146-221,298-368` | Dataset bundle and input manifests | Phase 8 exposes one daily response; it does not assemble execution prices, signal prices, status, corporate actions, universe snapshots, and manifests as one frozen input bundle. | `PORT_PHASE12` | Preserve the provider-neutral manifest idea for the native deterministic backtest worker. Do not migrate the old backtest engine or runtime boundary. |
| `backend/app/core/data/providers/tushare.py` and `backend/app/core/data/market_data_repository.py` | Old provider SDK, ORM repository, and Pandas service architecture | These are Community implementation details, not BYQ contracts. | `REFERENCE_ONLY` | Extract field meanings and invariants only. Current BYQ remains JSON transport plus BYQ-owned contracts. |
| Community BaoStock and AKShare adapters and fallbacks | Legacy provider implementations | Incompatible with the current Tushare direction. | `DROP` | BaoStock = DROP; AKShare = DROP. No dependencies, adapters, fallbacks, or compatibility layer. |
| Community VectorBT engine and compatibility paths | Legacy optional backtest engine | Incompatible with the BYQ-owned deterministic engine direction. | `DROP` | VectorBT = DROP. Engine-independent metrics/tests may be harvested in Phase 12, but no VectorBT code or dependency returns. |

### Blockers before Phase 10

The retrospective records these as design/contract blockers for starting
Phase 10 factor implementation, not as reasons to modify or reopen Phase 8:

1. A factor input must use a trading-session calendar and distinguish genuine
   missing data from pre-listing, post-delisting, suspension, and non-trading
   boundaries.
2. Any non-price or revised dataset must carry an effective/announcement
   `as_of` rule and reject look-ahead. Index membership must be the latest
   snapshot visible on the research date, not the latest snapshot available
   today.
3. The factor input boundary must enforce one deterministic bar per
   `(symbol, trade_date)`, stable ordering, and explicit finite/OHLC quality
   validation. These are suitable for a small Data Contract hardening PR;
   they do not justify a Phase 8 rewrite.

If Phase 10 is deliberately restricted to raw daily prices, it must still
adopt the calendar, lifecycle, coverage, uniqueness, ordering, and OHLC rules
above before the first factor is accepted. If fundamentals, index membership,
or other point-in-time inputs are added, the as-of rule is mandatory.

### Phase 10 implementation reuse status (current branch)

| Community semantic | Current BYQ implementation | Classification / status |
|---|---|---|
| Explicit canonical symbol/exchange and asset identity | `services/backend/app/factor_research.py::normalize_symbol`, security snapshot | `PORT_LOGIC` — prefix heuristics intentionally excluded |
| Listing/delisting, suspension, and non-trading coverage states | `prepare_factor_input` lifecycle/status/session coverage | `PORT_LOGIC` — missing active bars fail closed; lifecycle states remain distinct |
| Trading-session lag semantics | `sessions` normalization and session-position factor windows | `PORT_LOGIC` / `PORT_TESTS` |
| Duplicate bars, stable ordering, finite/OHLC validation | BYQ factor input boundary and factor regression tests | `PORT_LOGIC` / `PORT_TESTS` — Phase 8 adapter unchanged |
| Point-in-time universe and announcement/effective visibility | latest visible `universe_snapshots`, source as-of checks | `PORT_LOGIC` / `PORT_TESTS` |
| Content-addressed input identity and factor result metadata | factor input SHA-256 manifest summary plus `factor_result` Artifact | `REFACTOR` — Community manifest semantics reimplemented behind BYQ ResearchStore |
| Community provider SDK, ORM, Pandas service, and old runtime | Not imported or copied | `REFERENCE_ONLY` / `REPLACE` |
| BaoStock, AKShare, VectorBT | Not present in the new implementation | `DROP` |

### Phase 11 implementation reuse status (current branch)

| Community semantic | Current BYQ implementation | Classification / status |
|---|---|---|
| Immutable strategy semantic snapshot and source fingerprint | `services/backend/app/strategy_artifact.py` StrategyVersion identity and source SHA-256 | `PORT_LOGIC` / `PORT_TESTS` — timestamps and Agent runtime state excluded |
| Static source safety and strategy method contract | BYQ stdlib AST validator with persisted validation evidence | `PORT_LOGIC` / `PORT_TESTS` — forbidden imports/calls, synchronous output contract, historical-loop `model.fit`, and PortfolioState field checks are ported; Community execution sandbox is not copied |
| Deterministic export hygiene | `strategy_version` export endpoint and contract | `PORT_LOGIC` / `PORT_TESTS` — JSON export only; object bundles remain a later candidate |
| Approval separate from execution outcome | `strategy_approval` Artifact linked to validated version | `REFACTOR` / `PORT_TESTS` — old Agent approval policy and SQL are not migrated |
| Community SQLAlchemy/Pandas/Agent Service strategy runtime | Not imported or copied | `REFERENCE_ONLY` / `REPLACE` |
| BaoStock, AKShare, VectorBT | Not present in the new implementation | `DROP` |

### Phase 12 implementation reuse status (current branch)

| Community semantic | Current BYQ implementation | Classification / status |
|---|---|---|
| Native A-share execution rules and golden cases | `services/backend/app/backtest.py::run_native_backtest` and `test_backtest.py` | `PORT_LOGIC` / `PORT_TESTS` — signal-snapshot engine; next-session open, T+1, limits, suspension, lots, fees, tax, corporate actions, and stable blocked reasons are BYQ-owned |
| Frozen universe authorization | `normalize_backtest_request` universe membership fingerprint and signal/bar containment | `PORT_LOGIC` / `PORT_TESTS` — no Community stock-pool ORM or index runtime is copied |
| Content-addressed input manifest | `normalize_backtest_request` and `input_manifest_id` | `REFACTOR` — canonical BYQ manifest with explicit strategy/approval, bars, signals, execution, and engine contract identity |
| Durable jobs, retries, and worker recovery | `BacktestJobStore`, `BacktestWorker`, `workers/backtest/worker.py` | `REFACTOR` — SQLite Backend state, strict task-scoped idempotency, bounded attempts, and stale requeue; old Agent workflow state is not migrated |
| Immutable result object and lifecycle guard | `LocalObjectStore`, `backtest_result` Artifact, and object integrity tests | `PORT_LOGIC` / `PORT_TESTS` — namespace/object identity, media type, size, SHA-256, owner/live-reference deletion checks |
| Community Pandas/ORM/Agent runtime and VectorBT engine | Not imported or copied | `REFERENCE_ONLY` / `DROP` |

### Phase 14 implementation reuse status (current branch)

| Community semantic | Current BYQ implementation | Classification / status |
|---|---|---|
| Bounded agent iteration and repair/retry | `LearningLoopStore` run/iteration budgets, repair attempts, stopping rules | `PORT_LOGIC` — Community execution profiles are not copied; BYQ owns domain limits |
| Deterministic trajectory evaluation | `EvaluationSignal` plus `compare_experiments` | `REFACTOR` / `PORT_TESTS` — Community eval fixtures are reference material only |
| Evidence-backed promotion | `Lesson` proposal requires validated artifacts or evaluation signals; human review and promotion history | `PORT_LOGIC` — old Agent approval/executor is not migrated |
| Secret-safe bounded evidence | Recursive secret-key rejection and bounded JSON in learning payloads | `PORT_LOGIC` / `PORT_TESTS` |
| Community Agent Service runtime and persistence | Not imported or copied | `REFERENCE_ONLY` / `REPLACE` |
| BaoStock, AKShare, VectorBT | Not present in the new implementation | `DROP` |

### Retrospective migration summary

- `PORT_NOW`: duplicate-key policy, deterministic ordering, and finite/OHLC
  validation as a small optional Data Contract hardening PR.
- `PORT_PHASE10`: symbol/security semantics, lifecycle, suspension-aware
  coverage, trading calendar, point-in-time inputs, provenance extension, and
  look-ahead prevention.
- `PORT_PHASE12`: frozen dataset bundles, execution/status inputs, durable
  coverage repair, and backtest manifests.
- `REFERENCE_ONLY`: Community Tushare SDK usage, ORM repository, Pandas
  service structure, and provider-specific implementation details.
- `DROP`: BaoStock, AKShare, VectorBT, and their dependencies/fallbacks.
- No Phase 8 source file, architecture decision, dependency, or API was
  changed by this retrospective.

## Phase 35 Paper Trading migration audit

The mandatory sequence was completed before implementation: inspect the
read-only Community page, models, execution/read/repository/tracking/transfer
services, migrations, and tests; classify each capability; extract domain
invariants and test intent; then accept ADR-0021. Community is evidence only
and is not a data or source-code migration input.

| Community capability | Reusable invariant/test intent | Decision | Phase 35 target |
|---|---|---|---|
| Account, position, order, ledger, and snapshot persistence | Owner isolation; one account aggregate; immutable settlement date; deterministic read order. | `REFACTOR` / `PORT_TESTS` | BYQ PostgreSQL records and Product projections under ADR-0021. |
| T+1 ledger settlement | Total and sellable quantity are distinct; settlement promotes locked quantity; duplicate settlement cannot rewrite history. | `PORT_LOGIC` / `PORT_TESTS` | Exact quantity state plus atomic monotonic BYQ settlement. |
| Paper order state machine and broker trace | Stable lifecycle/audit is useful, but broker attempts, cancel, partial fill, and async failure are not real in current BYQ. | `REFERENCE_ONLY` | Honest immediate `filled`/`blocked` detail and immutable BYQ events. |
| Kill switch and maximum order notional | Controls are persisted, evaluated before execution, and visible with account state. | `REFACTOR` / `PORT_UX` | Versioned, audited controls with optimistic concurrency. |
| Broker failure circuit breaker | Requires an external asynchronous failure stream that Phase 35 does not have. | `DROP` | No cosmetic control or compatibility field. |
| Manual settlement dialog and snapshot history | Complete mark input, daily performance projection, explicit manual action. | `PORT_UX` | Product API settlement with manual mark provenance and immutable history. |
| Account JSON export/import | Portability is useful; external owner/ID and permissive nested row reconstruction are unsafe. | `REPLACE` | Manifested/digested BYQ bundle, new ID, owner rebinding, validation, atomic import. |
| SQLAlchemy repository, old Agent API/runtime, and PaperBroker integration | Coupled to Community ownership and deprecated runtime boundaries. | `REFERENCE_ONLY` | No source, schema, runtime, or API copied. |
| BaoStock, AKShare, and VectorBT paths | None. | `DROP` | No dependency, adapter, fallback, row, or compatibility layer. |

## Phase 36 Agent workbench pre-implementation audit

The mandatory ADR-0018 sequence was completed against the read-only Community
baseline before Phase 36 implementation: inspect `AgentView.vue`,
`AgentThinking.vue`, `ApprovalManagementPanel.vue`,
`GlobalApprovalCenter.vue`, and `XiaobaAssistantDrawer.vue`; classify each
surface; extract presentation and interaction invariants; then define the BYQ
projection and authority boundary. Community source, APIs, runtime events, and
persistence remain reference-only and were not modified or copied.

| Community capability | Reusable UX invariant | Decision | ADR-0018 / Phase 36 boundary |
|---|---|---|---|
| Conversation plus contextual result workspace | Keep a coherent turn timeline with structured, scan-friendly results beside public assistant output. | `PORT_LAYOUT` / `PORT_UX` | Render only versioned BYQ WorkflowTrace projections. |
| `AgentThinking` progress visualization | Users need understandable operational phase/state feedback while work is running. | `PORT_COMPONENT` / `REFACTOR` | Implement bounded `agent.activity`; hidden reasoning, prompts, tool arguments/results, and chain-of-thought are `DROP`. |
| Strategy draft, stock candidate, and optimization cards | Typed summaries, stable identity, revision-aware updates, and clear follow-up affordances. | `REFACTOR` | Exact `workflow-card.v1` proposal schemas; no source code, arbitrary URLs, or executable action payloads. |
| Backtest context card | Link the conversation to an owner-visible current job/result without duplicating its full detail. | `REFACTOR` | Gateway rehydrates owner-scoped Domain state; model claims are never authoritative. |
| Approval cards, management panel, and global center | Pending state and human decision must be visible; approval and execution outcome stay distinct. | `REFACTOR` | Current BYQ Approval resource is authoritative; fixed Product API interaction after a fresh owner-scoped read. |
| Page-aware assistant drawer | Preserve compact open/close UX and bounded page context that helps the user continue work. | `PORT_COMPONENT` / `PORT_UX` | Context uses allow-listed BYQ route/resource identifiers; never raw page state, credentials, or runtime internals. |
| Community Agent API, SSE/message schema, runtime state, PydanticAI/Hermes coupling | Evidence of desired behavior only. | `REFERENCE_ONLY` / `REPLACE` | Runtime Adapter curates DSH candidates; Gateway persists/streams BYQ envelopes; frontend imports only BYQ types. |
| Model-described actions and approval/execution conflation | None; this is an unsafe authority shortcut. | `DROP` / `REPLACE` | Cards are view models, never commands. Consequential actions use fixed BYQ Product routes, validation, idempotency, concurrency, and approval contracts. |

## Phase 37 My Space pre-implementation audit

The read-only Community `UserModelsView.vue`,
`UserModelSettingsPanel.vue`, `UserAssetsView.vue`, and
`UserAgentPolicyView.vue` were inspected before accepting ADR-0019. Their UX
is evidence only; Community APIs, secret persistence, provider catalogue,
PydanticAI/Hermes runtime, and SQL models are not migration inputs.

| Community capability | Reusable invariant / UX | Decision | ADR-0019 / Phase 37 boundary |
|---|---|---|---|
| Credential create/edit/status cards | A user can name, replace, disable, and understand whether a credential is configured without rereading it. | `PORT_LAYOUT` / `PORT_UX` / `REPLACE` | BYQ write-only secret mutations, metadata-only masked reads, AES-256-GCM envelopes, optimistic versioning, revoke, and append-only audit. |
| Model profiles separate from provider credentials | Reusable model choices and generation options should not duplicate secrets. | `PORT_LOGIC` / `REFACTOR` | Owner-scoped profile references an active credential plus a reviewed provider/model catalogue entry. Arbitrary base URLs are rejected. |
| Per-Agent model binding | Users need an explicit effective model choice and system-default state for each BYQ Agent preset. | `PORT_UX` / `REFACTOR` | Owner-scoped binding is authorized by Backend and resolved privately by Runtime Adapter; Gateway/MCP/WorkflowTrace never receive the secret. |
| Strategy/backtest asset import/export | Portable assets need validation, provenance, new owner-safe identity, and honest import results. | `REFACTOR` / `PORT_UX` | Reuse BYQ canonical artifact/bundle contracts; do not reconstruct Community rows or identifiers. |
| Agent policy settings, presets, rule table/dialog, and history | Settings and ordered rule CRUD should be understandable, bounded, and visibly effective. | `PORT_UX` / `REFACTOR` | Extend BYQ owner-scoped policy state and audit; Community action/engine values are not implicitly accepted. VectorBT remains `DROP`. |
| Community credential endpoints, provider URLs, database schema, and Agent runtime | None as an implementation boundary. | `REFERENCE_ONLY` / `REPLACE` | Product API → Backend and private Backend → Runtime Adapter resolution under ADR-0019. No Community code or data is copied. |
| BaoStock, AKShare, VectorBT, PydanticAI, and Hermes paths | None. | `DROP` / `REPLACE` | Excluded technologies and compatibility paths remain absent. |

Phase 37 completed this classification on 2026-08-22. The implementation
preserves only the classified visual/interaction invariants and uses BYQ-owned
contracts, persistence, identities, Product API, and Runtime Adapter
boundaries. The Community repository remained read-only. The completed
checklist, real Product API flow, and Chrome DevTools MCP evidence are under
`docs/evidence/phase-37/`.

## Phase 43 durable-conversation pre-implementation audit

The read-only Community `AppSidebar.vue`, `AgentView.vue`, and `api/agent.js`
were inspected before Phase 43 implementation. The useful evidence is the
conversation lifecycle and switching UX; Community persistence, API paths,
message/run shapes, polling, and runtime coupling remain reference-only.

| Community capability | Reusable invariant / UX | Decision | Phase 43 disposition |
|---|---|---|---|
| Titled recent sessions with pin, rename and delete controls | Stable human-readable identity, pin ordering and explicit lifecycle actions make long-running research recoverable. | `PORT_UX` / `REFACTOR` | BYQ Backend owns owner-scoped title, pin and archive metadata; archive replaces destructive delete. |
| Session list, message restoration and active-run polling | Switching must restore one coherent timeline and stale async responses must not cross into the selected conversation. | `PORT_LOGIC` / `PORT_TESTS` | Generation guards plus abortable Product streams; replay combines durable user turns with normalized WorkflowTrace only. |
| Conversation pane and context pane | The conversation remains primary while operational context stays accessible without permanent three-column density. | `PORT_LAYOUT` / `PORT_UX` | Centered Xiaoba canvas with inline cards and bounded activity/approval drawers. |
| Community Agent endpoints, stored messages/artifacts and run schemas | None as an integration boundary. | `REFERENCE_ONLY` / `REPLACE` | Browser uses Gateway Product routes; Backend catalog and Gateway projection replace old APIs and storage. |
| Community runtime/session identity | None as a Product identity. | `DROP` / `REPLACE` | Product conversation identity is public; DSH session persistence is private correlation and never returned by replay. |

## Phase 44 user-center and appearance pre-implementation audit

The read-only Community `UserSettingsMenu.vue`, `UserProfileView.vue`,
`UserAssetsView.vue`, `UserModelSettingsPanel.vue`,
`UserAgentPolicyView.vue`, `PaperTradingView.vue`, `AppLayout.vue`, and
`store/modules/app.js` were inspected before implementation. Existing BYQ
Phase 35/37 Product capabilities remain authoritative; this phase relocates
them and adds a new ADR-0024 preference contract rather than copying
Community state or APIs.

| Community capability | Reusable invariant / UX | Decision | Phase 44 disposition |
|---|---|---|---|
| Bottom account trigger and compact account menu | Personal destinations stay reachable without expanding primary business navigation. | `PORT_UX` / `PORT_LAYOUT` | Existing BYQ user trigger points to one route-backed user center; administrator settings remain separately authorized. |
| Profile nickname, research preferences and default prompt | Explain that personal settings affect the current user's research experience. | `REUSE_AS_IS` / `PORT_UX` | Existing durable BYQ profile API and view are embedded without changing its owner boundary. |
| Assets, model credentials/profiles/bindings, Agent policy and Paper Trading surfaces | Preserve complete real workflows while consolidating navigation. | `REUSE_AS_IS` / `PORT_LAYOUT` | Existing Product API views become user-center sections; old deep links explicitly redirect. |
| Community theme toggle and Pinia app store | Avoid first-paint flash and reflect a user's chosen mode. | `REFERENCE_ONLY` / `REPLACE` | New PostgreSQL-backed `ui-preferences.v1`, closed values, optimistic concurrency, pre-mount non-authoritative cache, and global semantic tokens. |
| Arbitrary provider URLs, old credential API and local-only preference authority | None under ADR-0019/ADR-0024. | `DROP` / `REPLACE` | BYQ write-only encrypted credentials and Backend-authoritative preferences remain the only Product boundary. |
| Community Paper/Agent runtime, VectorBT option, PydanticAI/Hermes assumptions | None as an integration boundary. | `REFERENCE_ONLY` / `DROP` | No runtime, schema, Provider, Agent API, engine, or storage code is copied. |

## Phase 45 System Settings pre-implementation audit

The read-only Community `OpsLayout.vue`, `SystemMaintenanceWorkbench.vue`,
`ModelOperationsView.vue`, `RuntimeOperationsView.vue`,
`GraphOperationsView.vue`, `AccessControlOperationsView.vue`,
`DataSourceConfig.vue`, and `DataSync.vue` were inspected before
implementation. Existing BYQ Phase 38/39 operations and Data Center Product
projections remain authoritative; this phase changes their navigation and
composition, not their security or integration boundaries.

| Community capability | Reusable invariant / UX | Decision | Phase 45 disposition |
|---|---|---|---|
| Grouped operations navigation and compact status cards | Administrators need a clear hierarchy across system, data, Agent platform, access and audit capabilities. | `PORT_LAYOUT` / `PORT_UX` | One route-backed two-column System Settings dialog embeds existing BYQ Product surfaces and becomes full-screen on mobile. |
| Data-source configuration, synchronization progress and coverage status | Secret state, refresh progress, coverage and failures must be understandable without exposing credentials. | `PORT_UX` / `REFACTOR` | Reuse Phase 39 Tushare-only Product API contracts and durable jobs; no Community endpoint or state is reused. |
| Database, runtime, graph and access diagnostics | Bounded health, version, correlation and audit projections help operators diagnose Product behavior. | `PORT_UX` / `REPLACE` | Existing `operations.v1`, normalized WorkflowTrace, persistent identity and append-only audit projections remain the only browser-visible contracts. |
| Database switching, arbitrary SQL, Redis controls, deployment controls and arbitrary provider/Base URL editing | None under the accepted Product/Runtime/Data Plane boundaries. | `DROP` / `REPLACE` | System Settings is deliberately diagnostic and contract-bounded; it cannot mutate infrastructure or bypass Backend policy. |
| Raw DSH event, graph/checkpoint/runtime state and direct Backend/MCP/storage access | None as a frontend integration boundary. | `REFERENCE_ONLY` / `DROP` | Browser traffic remains same-origin Gateway/Product API only; DSH internals stay behind BYQ normalization. |

Phase 45 reuses only the classified visual and interaction evidence. The
Community repository remains read-only, and no Community component, API,
database, runtime, cache, or deployment control is copied.

## Phase 39 Data Center / Data Sync pre-implementation audit

The read-only Community `DataSourceConfig.vue`, `DataSync.vue`, data-source
schemas/models/routes, sync-task model, coverage service, scheduler tests, and
sync-job state-machine tests were inspected before implementation. Community
is interaction and invariant evidence only; no old provider registry, ORM,
scheduler, cache, database, or source code is copied.

| Community capability | Reusable invariant / UX | Decision | ADR-0019 / Phase 39 boundary |
|---|---|---|---|
| Data-source list, masked configured state, replace/disable/revoke, connection test | Operators need an understandable source lifecycle without rereading the secret. | `REFACTOR` / `PORT_UX` | Tushare-only system credential in the ADR-0019 encrypted store; metadata-only Product projection and admin RBAC. |
| Generic provider selector, arbitrary endpoint and provider registry | None under the accepted provider/security boundary. | `DROP` / `REPLACE` | Fixed BYQ Tushare contract and deployment-owned endpoint; BaoStock, AKShare, Yahoo and arbitrary URLs are absent. |
| Sync form and per-symbol progress/result table | Bounded symbol/date scope, explicit job status, per-symbol outcome, and durable history are useful. | `REFACTOR` / `PORT_UX` / `PORT_TESTS` | Idempotent BYQ PostgreSQL jobs execute through the Backend-owned adapter and import normalized daily bars into `MarketDataStore`. |
| Community static stock pools and fake 50% progress | None; they are placeholder behavior. | `DROP` | Product UI uses only real Product API job and persisted result projections. |
| Scheduler leases/retries and broad multi-dataset jobs | Useful future worker evidence, but outside the Phase 39 bounded daily-bar job. | `REFERENCE_ONLY` | No old scheduler/runtime is copied; Phase 39 keeps a bounded Backend execution seam and durable job state. |
| Market coverage table and audit UX | Report observed row/symbol/date bounds and quality issues; do not infer complete history without calendar/lifecycle evidence. | `PORT_LOGIC` / `PORT_UX` | PostgreSQL aggregate audit explicitly sets `completeness_claimed=false`; source and OHLC issues are counted. |
| Community PostgreSQL/Redis cache and physical migration paths | None as an authoritative store. | `REFERENCE_ONLY` / `DROP` | BYQ PostgreSQL is authoritative; Redis assumptions and physical Community storage reuse remain prohibited. |
| BaoStock and AKShare rows/adapters/fallbacks | None. | `DROP` | No dependency, adapter, configuration, row, fallback, or compatibility path. |

## Phase 40 final-parity pre-implementation audit

The read-only Community strategy executor/security/validation/backtest path
and all ten shared components named by the Phase 40 plan were inspected before
ADR-0023 and implementation. Community source, runtime, ORM, APIs and storage
remain evidence only and were not modified or copied.

| Community capability | Reusable invariant / UX | Decision | ADR-0023 / Phase 40 boundary |
|---|---|---|---|
| `CustomStrategy.generate_signals(data, parameters)` and `-1/0/1` outputs | A stable synchronous signal contract over a frozen universe/date index is useful. | `PORT_LOGIC` / `PORT_TESTS` | Closed `byq-signal-python-v1` profile; BYQ revalidates and content-addresses normalized output. |
| In-process Python `exec`, restricted builtins/import hook and backtest-service execution | Static checks help diagnostics but are not a sandbox; process credentials and storage must remain unreachable. | `REFERENCE_ONLY` / `REPLACE` | Trusted coordinator plus separate no-credential, bounded, non-root signal sandbox under ADR-0023. |
| Pandas/NumPy strategy input and deterministic parameter defaults | Frozen, ordered data and explicit finite parameters support reproducibility. | `REFACTOR` | Exact sandbox dependency lock and input fingerprint; no provider access or mutable Community cache. |
| Stateful target-weight strategies and broad ML imports | They require a distinct portfolio-state/output contract and much larger execution surface. | `REFERENCE_ONLY` | Fail closed as unsupported by v1; no silent fallback or Community compatibility layer. |
| `AppStateBlock` and `EntityPagination` | Consistent loading/error/empty actions and bounded responsive paging reduce repeated view logic. | `PORT_COMPONENT` / `REFACTOR` | BYQ-owned typed components; only Product projection state. |
| `GlobalApprovalCenter`, `ApprovalManagementPanel`, `XiaobaAssistantDrawer`, `AgentThinking` | Global access, explicit approval outcome, contextual assistant and public progress are useful. | `REUSE_AS_IS` / `REFACTOR` | Phase 36 already delivered BYQ-owned normalized equivalents; hidden reasoning and Community actions stay `DROP`. |
| `StockPoolDialog` | Guided pool creation and responsive candidate/final-list UX are useful. | `PORT_UX` / `REFACTOR` | Reuse proven Phase 34 Product API workflow; extract only where it reduces duplication without reviving Community filters. |
| `UserModelSettingsPanel` | Credential/profile/binding grouping and masked-secret UX are useful. | `REUSE_AS_IS` / `REFACTOR` | Phase 37 equivalent remains authoritative under ADR-0019; arbitrary Base URLs stay `DROP`. |
| `SystemAnalytics` | Compact health metrics and responsive cards are useful. | `REUSE_AS_IS` / `REFACTOR` | Phase 38 operations projections/MetricCard remain authoritative; no Redis or raw host diagnostics. |
| `ChartWrapper` | Resize, loading and empty behavior are reusable. | `REUSE_AS_IS` | Existing BYQ component already implements the accepted visual contract. |

Phase 40 closure result: every item above is implemented, reused, explicitly
replaced, or dropped at its stated BYQ boundary. The no-mock two-user Product
journey and Chrome evidence are under `docs/evidence/phase-40/`; no Community
source, runtime, database, cache or Git history was modified or imported.

## Phase 46 core-management workspace pre-implementation audit

The read-only Community `StockPoolView.vue`, `StockPoolDialog.vue`,
`StrategyView.vue`, `BacktestView.vue`, and `ChartWrapper.vue` were inspected
before implementation. Phase 34 Stock Pool, Phase 40 Strategy/signal and the
existing deterministic Backtest Product capabilities remain authoritative.
This phase re-composes those capabilities and repairs normalized Workflow-card
navigation; it does not copy Community state, APIs, execution code or storage.

| Community capability | Reusable invariant / UX | Decision | Phase 46 disposition |
|---|---|---|---|
| Searchable catalog beside persistent detail context | Users can compare resources without losing the selected detail surface. | `PORT_LAYOUT` / `PORT_UX` / `REFACTOR` | One BYQ-owned responsive workspace shell composes the three existing Product views and semantic theme tokens. |
| Guided Stock Pool creation and catalog/detail tabs | Creation should be bounded while identity, members, provenance, references and history stay legible. | `PORT_UX` / `REFACTOR` | Move the proven Phase 34 write flow into a dialog; preserve mutable catalog identity and all five immutable-snapshot projections. |
| Strategy editor, version history and operational status | Draft editing must remain visibly separate from read-only versions and approval authority. | `PORT_LAYOUT` / `REUSE_AS_IS` | Preserve Phase 40 draft/version/approval/signal lineage and Product API behavior inside the shared catalog/detail hierarchy. |
| Backtest task list, comparison, charts and deep result tabs | Result review must expose performance and execution evidence, not only a summary card. | `PORT_LAYOUT` / `PORT_STYLE` / `REUSE_AS_IS` | Preserve BYQ's complete result, comparison, manifest and ChartWrapper surfaces; apply the global theme through existing semantic tokens. |
| Route query selection and return-to-research affordance | A conversation result should open its exact current Product resource and return to the originating durable conversation. | `PORT_UX` / `REFACTOR` / `PORT_TESTS` | Fixed frontend mapping consumes normalized card kinds and validated identifiers only; destination pages rehydrate owner-scoped Product state. Cards remain data, never commands or URLs. |
| Community Agent endpoints, ORM/cache state, VectorBT engine and browser-side source execution | None under ADR-0017/0018/0020/0023/0024. | `REFERENCE_ONLY` / `DROP` / `REPLACE` | Gateway/Product API, immutable signal snapshots, isolated producer and BYQ deterministic engine remain the only accepted boundaries. |

The Community repository remained read-only throughout inspection. No
Community component, endpoint, database, cache, runtime or Git history was
modified or copied.

## Phase 47 interaction and accessibility pre-implementation audit

The read-only Community `AppStateBlock.vue`, `EntityPagination.vue`,
`useDisplay.js`, `usePagination.js`, `ChartWrapper.vue`, global theme styles,
and the form/dialog interactions in Stock Pool, Strategy, Profile and settings
were inspected before Phase 47 implementation. Existing BYQ Product routes,
durable preferences, domain resources and semantic tokens remain authoritative;
this phase standardizes interaction behavior without copying Community state,
APIs or hard-coded visual themes.

| Community capability | Reusable invariant / UX | Decision | Phase 47 disposition |
|---|---|---|---|
| Shared loading, empty and error blocks with actions | Async surfaces need one understandable state hierarchy and a reachable recovery action. | `PORT_COMPONENT` / `REFACTOR` | Extend BYQ typed state primitives with live-region semantics, retry actions and reduced-motion-safe feedback. |
| Responsive entity pagination and display breakpoints | Counts, page controls and catalog/detail content must remain operable on narrow screens. | `PORT_UX` / `REFACTOR` | Keep BYQ server-bounded pagination and CSS breakpoints; add compact mobile controls without importing Community stores. |
| Chart loading, empty and resize behavior | Charts must resize, explain empty/loading state and follow the active visual theme. | `REUSE_AS_IS` / `REFACTOR` | BYQ ChartWrapper gains semantic chart palettes, accessible names/summaries, ResizeObserver and reduced-motion behavior. |
| Form success/error feedback and disabled pending actions | Writes must disclose progress and outcome and prevent duplicate submission. | `PORT_UX` / `REFACTOR` | Use existing Product mutations with shared status semantics and explicit disabled/loading states. |
| Editable settings and catalog/detail forms | Navigating, switching resources or refreshing must not silently discard unsaved durable edits. | `PORT_UX` / `PORT_TESTS` | Add a BYQ route/browser leave guard and explicit resource-switch confirmation; no local-only persistence is introduced. |
| Community theme store, hard-coded state colors, legacy APIs and runtime-aware UI | None under ADR-0014/0018/0024. | `REFERENCE_ONLY` / `DROP` / `REPLACE` | Durable `ui-preferences.v1`, semantic tokens, Gateway/Product API and normalized WorkflowTrace remain the only accepted boundaries. |

The Community repository is evidence only and remains read-only. No Community
component, API, runtime, theme store, persistence or Git history is copied.

## Phase 48 Product coherence pre-implementation audit

The final audit re-inspected the read-only Community `AgentView.vue`,
`AppSidebar.vue`, `UserSettingsMenu.vue`, `StockPoolView.vue`,
`StrategyView.vue`, `BacktestView.vue`, `UserProfileView.vue`,
`UserAssetsView.vue`, `UserModelsView.vue`, operations routes and access
workbench. Phase 48 adds no alternate Product architecture: it verifies that
the capabilities already classified and delivered by Phases 34–47 remain
coherent when used together.

| Community capability | Reusable invariant / evidence | Decision | Phase 48 disposition |
|---|---|---|---|
| Agent timeline and historical sessions | One understandable conversation can be restored and used to reach research resources. | `PORT_UX` / `REUSE_AS_IS` | Reuse the Phase 43 durable BYQ catalog and normalized WorkflowTrace; verify rename, pin, archive/restore and owner isolation. |
| Stock Pool, Strategy and Backtest workspaces | Catalog/detail context and complete resource evidence must survive the redesigned shell. | `PORT_LAYOUT` / `REUSE_AS_IS` | Reuse Phase 34/40/46 Product APIs and domain invariants; run the approved version → signal → backtest journey. |
| Profile, appearance, models and assets | Personal state is durable, portable where safe, and never crosses owners. | `PORT_UX` / `REUSE_AS_IS` | Reuse Phase 37/44 contracts; verify encrypted write-only credential responses, binding, theme persistence and bundle validation. |
| Grouped administrator operations | Operators need bounded diagnostics without raw infrastructure or runtime authority. | `PORT_LAYOUT` / `REUSE_AS_IS` | Reuse Phase 38/39/45 `operations.v1` and Data Center projections; verify admin RBAC and raw-DSH exclusion. |
| Desktop, tablet and mobile composition | Relocated capabilities must remain reachable, readable and theme-consistent. | `PORT_TESTS` / `REFACTOR` | Add a repeatable no-mock two-user CI journey and Chrome MCP/Lighthouse evidence; fix the discovered mobile dark-select contrast defect. |
| Community API/runtime/storage schemas and direct service access | None as a BYQ browser or domain boundary. | `REFERENCE_ONLY` / `DROP` / `REPLACE` | Browser remains same-origin Gateway/Product API only; Community stays read-only evidence. |
| BaoStock, AKShare, VectorBT, PydanticAI and Hermes | None. | `DROP` | No dependency, adapter, fallback or compatibility path is introduced. |

The inspection → classification → invariant extraction → disposition →
implementation sequence is complete. No Community source, database, cache,
runtime, credential or Git history was changed or imported.

## Phase 49 personal-workspace pre-implementation audit

Before accepting ADR-0025, the read-only Community
`docs/future_architecture_plan.md`, `docs/workspace_ownership_migration.md`,
`docs/model_gateway_cloud_contract.md`, and
`docs/open_source_architecture_plan.md` were inspected. Those documents are
planning and historical migration evidence, not proof of an implemented or
compatible tenant runtime.

The mandatory sequence produced these decisions:

1. **Inspect**: reviewed the proposed tenant objects, trusted context,
   owner/actor split, public market-data boundary, legacy ownership rules, and
   Community-to-Cloud seams.
2. **Classify**: retained only architecture-neutral security and migration
   invariants. Old runtime, ORM, API, database layout, roles, Cloud topology,
   and technology assumptions remain reference-only, replaced, or dropped.
3. **Extract invariants/tests**: personal users need a stable resource
   boundary; client/model identity is untrusted; shared data is not user-owned;
   historical rows require exact mapping and mismatch reporting; cross-scope
   access and parent-child references fail closed.
4. **Decide**: ADR-0025 uses one BYQ personal `workspace` plus an owner
   membership, keeps personal secrets/preferences user-scoped, and preserves a
   later team seam without implementing a commercial control plane.
5. **Implement**: Phase 49 changes documents only. Schema/backfill begins in an
   isolated Phase 50 worktree after this phase is merged.

| Community evidence | Classification | Phase 49 disposition |
|---|---|---|
| `future_architecture_plan.md` personal tenant, `TenantContext`, public-data and migration principles | `REFERENCE_ONLY` / `REFACTOR` | Keep the personal boundary, server-derived context, resource classification, and no-silent-assignment invariants. Replace the old `tenant_id`-everywhere shape with ADR-0025's user/workspace/platform split. |
| `workspace_ownership_migration.md` owner inventory, legacy handling and workspace asset rules | `PORT_TESTS` / `REFACTOR` | Adapt exact-owner, cross-user denial, parent propagation, bundle rebinding and migration-report test intent. Do not copy old nullable-owner compatibility or storage code. |
| `model_gateway_cloud_contract.md` null-tenant seam and server-provided actor | `REFERENCE_ONLY` / `REPLACE` | Preserve server-derived actor/workspace and write-only secret rules through current Gateway → Backend → Runtime Adapter/Model Gateway boundaries. Do not restore its Community runtime chain. |
| `open_source_architecture_plan.md` local tenant-provider abstraction and future commercial split | `REFERENCE_ONLY` | Retain modular future extension only. No parallel tenant harness, Cloud service topology, billing, entitlement, or team control plane is added. |
| Community PydanticAI/Hermes runtime, direct service APIs, ORM schemas, Redis/cache and VectorBT references | `REPLACE` / `DROP` | Current DSH Runtime Adapter, BeyondQuant MCP, Product API, PostgreSQL domain store and deterministic BYQ engine remain authoritative. BaoStock, AKShare, VectorBT, PydanticAI-as-main-runtime and Hermes remain excluded. |

No Community file, database, runtime, credential, Git history, or source
component was modified or copied.

## Phase 53 security-master and data-sync pre-implementation audit

The read-only Community `backend/app/core/data/providers/tushare.py`, its
market-data synchronization service/tests, and the Data Center maintenance
workbench were inspected before Phase 53 implementation. The mandatory
inspect → classify → extract invariants/tests → decide → implement sequence
produced the following disposition.

| Community evidence | Reusable invariant / UX | Decision | Phase 53 disposition |
|---|---|---|---|
| `fetch_security_master` requests Tushare `stock_basic` for `L`, `D`, and `P` | A usable A-share catalogue includes listed, delisted, and paused lifecycle states with canonical identity and dates. | `PORT_TESTS` / `REFACTOR` | Add a closed BYQ `security-master.v1` adapter and reject incomplete/conflicting results atomically. |
| Mutable universe table and synchronization service | Basic data must be synchronized before a fresh installation can select daily-bar targets. | `REFERENCE_ONLY` / `REPLACE` | PostgreSQL stores immutable content-addressed snapshots plus a current catalogue; no Community ORM, registry, scheduler, cache, or physical database is copied. |
| System maintenance Data Center catalogue and sync controls | Operators need visible basic-data status, search/filter/selection and durable progress. | `PORT_UX` / `PORT_LAYOUT` / `REFACTOR` | Build a BYQ-owned responsive Data Center over same-origin Gateway/Product API and normalized job/catalogue projections. |
| Daily-basic, ETF, index and broad provider orchestration | These require separate contracts, lifecycle and quality semantics. | `REFERENCE_ONLY` / `DROP` | Phase 53 synchronizes stock basic identity and stock daily bars only. No arbitrary Tushare endpoint, BaoStock, AKShare, ETF/index/fundamental compatibility path is introduced. |
| Community frontend internal APIs, Tushare SDK/Pandas, SQLAlchemy, threads and direct cache/database assumptions | None at current BYQ boundaries. | `REPLACE` / `DROP` | Keep raw provider translation in Backend, browser traffic on Product API, and BYQ PostgreSQL domain stores; DSH receives no database or provider access. |

No Community source, database, cache, runtime, credential, or Git history is
modified or imported. Community data remains eligible only for a future
read-only logical migration after ADR-0013 provenance validation.
