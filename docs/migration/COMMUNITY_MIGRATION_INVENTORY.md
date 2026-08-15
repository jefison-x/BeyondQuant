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
| Approval policy and audit records | `agent-service/app/services/approval_policy.py`, `agent-service/app/services/approval_executor.py`, `agent-service/app/services/history.py`, approval tests | Policy evaluation, manual approval, actor/run/session correlation | `REFERENCE_ONLY` / `PORT_LOGIC` | Manual policy cannot be bypassed by a user rule; budgets and failure circuit breakers are bounded; approval is distinct from execution success; audit records correlate owner, run, session, action, result, and error. | `agent-service/tests/test_approval_policy.py`, `test_approval_executor.py`, `test_approval_workflow_recovery.py` | Phase 11 / Phase 13+ | Current Phase 9 records `trace_id`, timestamps, versions, and transition idempotency results but deliberately has no business approval. A richer audit/authorization surface requires a later ADR. |
| Old Agent workflow state and persistence | `agent-service/app/workflows/contracts.py`, `agent-service/app/workflows/repository.py`, `agent-service/app/harness/*` | Graph checkpoints, leases, DSH run state, workflow recovery | `REFERENCE_ONLY` | DSH workflow state may correlate to BYQ entities but cannot own domain lifecycle, artifact state, or business idempotency. | Agent graph/workflow tests | Phase 13+ | Keep DSH WorkflowTrace and BYQ state machines separate. Do not migrate Agent Service SQL or graph schema into Backend domain storage. |
| Old MCP gateway and server | `agent-service/app/tools/mcp_gateway.py`, `beyondquant-mcp/src/server.js`, MCP tests | Tool effects, normalized outcomes, timeouts, bounded diagnostics, trusted context | `REFACTOR` | Agent-to-domain calls go through MCP; tools should expose normalized capability contracts, bounded errors, stable idempotency context, and no storage details. | `beyondquant-mcp/test/tools.test.js`, MCP gateway tests | Phase 9 / Phase 13+ | Current `services/mcp` is the target implementation. Old Agent Gateway/runtime coupling, direct internal endpoints, and raw schemas are not copied. |
| PydanticAI/Hermes and old runtime coupling | `agent-service/app/runtime/pydantic_ai.py`, runtime factory, Hermes migration docs, old gateway wiring | Legacy agent runtime/orchestration | `REPLACE` | None of the runtime implementation is a BYQ domain asset. Generic runtime belongs to DSH; BYQ owns only domain contracts and MCP capabilities. | Runtime tests are migration evidence only | None | Explicitly do not reintroduce PydanticAI, Hermes, old model gateway coupling, SSE coupling, or Agent direct database access. |
| Old frontend/Agent schema coupling | `frontend/*`, old Agent event and API contracts | UI integration with runtime-specific state | `REFERENCE_ONLY` | Frontend should consume BYQ Gateway/WorkflowTrace contracts, not raw Agent event schemas or Agent persistence models. | Frontend contract tests are evidence only | Phase 13+ | Current architecture boundary supersedes the old coupling. |

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
  validation evidence, artifact export hygiene, and approval as a separate
  state machine.
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
