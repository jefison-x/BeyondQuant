# BeyondQuant Implementation Plan

This is the repository roadmap for autonomous development. Only the current
phase may be implemented in a normal phase branch. Later phases are planning
constraints, not permission to pre-build product scope.

For Phase 9 and later, the permanent migration source of truth is
`docs/migration/COMMUNITY_MIGRATION_INVENTORY.md`. Before a phase is
implemented, its Community candidates MUST be inspected and classified there.
Provider-independent or engine-independent semantics may be reimplemented in
BYQ-owned contracts; Community runtime, storage, provider, and engine
architecture MUST NOT be copied. BaoStock, AKShare, VectorBT, PydanticAI, and
Hermes remain excluded unless a future Accepted ADR explicitly reverses that
decision.

## Phase 6 — Runtime seam, ADR-0003, and development framework

### Goal

Establish and verify the formal Gateway → Runtime Adapter → official DSH SDK
→ explicit DSH runtime seam, and make the Codex development workflow
repository-readable.

### Scope

- official npm/PyPI rc.6 metadata and artifact/closure research;
- Options A/B/C evaluation and ADR-0003;
- Python/FastAPI Runtime Adapter with keyless initialize, MCP startup,
  lifecycle, normalization, and internal SSE prototype;
- minimal `WorkflowTraceEvent` envelope;
- architecture/unit/contract/smoke tests and CI;
- STATUS, roadmap, workflow, and agent instructions.

### Non-goals

No public chat API, frontend, real model turn, prompt-cancel protocol patch,
DSH fork/rebuild, Web proxy, domain feature, or Phase 7 implementation.

### Dependencies

Phase 5 Gateway, DSH rc.6, `byq-product` MCP composition, Backend/MCP health
contracts, and the official DSH Python SDK/npm artifacts.

### Architecture constraints

Use a dedicated Runtime Adapter; keep Gateway free of DSH imports/raw events;
use BeyondQuant MCP for domain access; keep Product DSH coding capability at
NONE; keep DSH persistence in the Agent Plane; pin rc.6 exactly.

### Acceptance criteria

ADR-0003 is Accepted; keyless initialize/MCP startup/hard cleanup pass; all
Phase 5 and Phase 6 tests and CI pass; STATUS says Phase 6 complete and Phase 7
next; no main merge occurs in the phase branch.

### Stop conditions

Insufficient official SDK evidence, a capability-boundary violation, an
unreliable cancellation mapping, a required DSH fork, or any workflow stop
condition in `docs/DEVELOPMENT_WORKFLOW.md`.

## Phase 7 — First Product Agent Turn + WorkflowTrace

### Goal

Deliver the first authenticated Product Agent turn through the accepted
runtime seam and a BYQ-owned end-to-end WorkflowTrace stream.

### Scope

Model/provider secret handling, one product prompt flow, resume/interrupted
semantics, trace persistence/ordering, and Gateway internal streaming contracts.

### Non-goals

No quant domain tools beyond the minimum health/vertical contract, no frontend
workflow UI, and no multi-agent research workflow.

### Dependencies

Accepted ADR-0003, Phase 6 adapter, BYQ authentication policy, model/provider
credentials, and a reviewed WorkflowTrace contract.

### Architecture constraints

Gateway sees BYQ envelopes only; domain calls go through MCP; Product DSH has
no coding/source-write capability; business state remains BYQ-owned.

### Acceptance criteria

A real model-keyed Product Agent turn is traceable from Gateway to adapter to
MCP and back as normalized events; cancellation/resume tests and secret
boundary tests pass; CI can run keyless tests without embedding secrets.

### Stop conditions

Model secret leakage, raw DSH schema crossing the Gateway boundary, unclear
resume ownership, or a need to widen Product DSH capabilities.

## Phase 8 — Data Provider Abstraction + Tushare

### Goal

Introduce a BYQ-owned data-provider contract and a safe Tushare integration.

### Scope

Provider interfaces, authentication/configuration, symbol/date semantics,
rate limits, caching policy, and contract-tested Tushare access.

### Non-goals

No factor engine, strategy validation, backtest worker, or agent autonomy over
provider credentials.

### Dependencies

Phase 7 product turn, BYQ domain contracts, Tushare account/access, and data
quality requirements.

### Architecture constraints

Providers belong to the Data/Domain planes; DSH accesses data only through
MCP; PostgreSQL business data remains inaccessible to DSH directly.

### Acceptance criteria

Provider contract tests, Tushare integration tests with redacted fixtures,
retry/rate-limit behavior, and provenance/audit metadata pass.

### Stop conditions

Ambiguous A-share semantics, unbounded provider cost, secret exposure, or
provider behavior that cannot be contract-tested.

## Phase 9 — ResearchTask + Experiment + Artifact

### Goal

Define durable BYQ research entities and lineage for agent-assisted research.

### Scope

ResearchTask, Experiment, Artifact, provenance, state transitions,
idempotency, validation, and MCP contracts.

### Non-goals

No factor library, strategy runtime, backtest worker, or generic DSH workflow
state machine replacement.

### Dependencies

Phase 8 data contracts and Phase 7 trace identity/authentication.

### Architecture constraints

Domain invariants and business state belong to BYQ; DSH workflow state and BYQ
artifact state remain separate; artifacts are auditable domain data.

### Acceptance criteria

State and lineage contracts are versioned, idempotent, persisted by Backend,
and exercised through MCP and contract tests.

### Stop conditions

Unclear artifact ownership/provenance, conflated DSH and domain state, or
missing idempotency rules.

## Phase 10 — Factor Research

### Goal

Build a reproducible factor research capability on the data/provider and
artifact foundations.

### Scope

Factor definitions, canonical security identity, lifecycle-aware input
coverage, trading-session calendars, deterministic input normalization,
computation metadata, evaluation, results as artifacts, and leakage/look-ahead
checks.

Phase 10 MUST establish the BYQ-owned input boundary for the provider-neutral
semantics identified by the Community audit:

- canonical A-share symbol, exchange, and asset-type semantics;
- listing/delisting and suspension/resumption lifecycle snapshots;
- a distinction between a missing bar and not-listed, delisted, suspended,
  boundary, or non-trading coverage states;
- trading-session windows and lag rules rather than naive calendar-day offsets;
- one deterministic bar per `(symbol, trade_date)`, an explicit duplicate-key
  policy, stable ordering, finite-value checks, and OHLC relationship checks;
- dataset identity, request provenance, reproducibility status, and effective
  date/announcement date/`as_of` semantics for revised or non-price data; and
- point-in-time universe or index membership using the latest snapshot visible
  on the research date.

If duplicate handling, deterministic ordering, or finite/OHLC validation is
implemented in a small Phase 8 Data Contract hardening PR, it MUST remain
limited to that contract. Otherwise the Phase 10 input boundary MUST enforce
the same rules before any factor is accepted. This is not permission to rewrite
the Phase 8 Tushare adapter.

### Non-goals

No strategy execution or portfolio/backtest job orchestration.

### Dependencies

Phases 8–9, the Community migration inventory, and reviewed quant methodology
contracts. The Phase 8 retrospective entry gates MUST be satisfied by the
Phase 10 input contract before factor implementation begins.

### Architecture constraints

Computation runs in BYQ workers/services; DSH proposes or invokes domain
operations through MCP and cannot bypass validation. Factor inputs and
provenance are BYQ-owned immutable snapshots. Tushare remains behind the BYQ
Data Provider Contract; no BaoStock, AKShare, or provider-specific Community
implementation may be introduced.

### Acceptance criteria

Deterministic fixture runs, canonical security/lifecycle semantics, trading
calendar and coverage classification, duplicate/order/OHLC validation,
point-in-time/as-of checks, provenance and reproducibility status, no-lookahead
checks, and artifact lineage are tested and reproducible. A factor cannot be
accepted when its input identity, effective visibility, or coverage status is
ambiguous.

### Stop conditions

Look-ahead leakage, undefined as-of visibility, missing lifecycle/calendar
semantics, ambiguous coverage, duplicate or malformed bars, non-reproducible
inputs, or factor invariants enforced only by prompts.

## Phase 11 — Strategy Artifact + Validation

### Goal

Represent strategy code/configuration as a validated, auditable domain
artifact.

### Scope

StrategyDraft/StrategyArtifact schema, immutable content-addressed
StrategyVersion snapshots, validation evidence, approval gates, provenance,
versioning, export hygiene, and MCP operations.

Strategy version identity MUST be derived from a deterministic semantic
snapshot and source/content fingerprint, excluding mutable timestamps. Exported
artifacts MUST omit credentials, runtime settings, and Agent internals.
Validation, approval, and execution outcome remain separate state and audit
concepts: approval authorizes an attempt and does not prove successful business
mutation.

### Non-goals

No direct Product DSH source writes, unrestricted code execution, or live
trading.

### Dependencies

Phases 9–10 and the BYQ strategy safety/invariant policy.

### Architecture constraints

Strategy code is domain data, not application source; Product DSH cannot write
the repository; validation is BYQ-owned and explicit.

### Acceptance criteria

Invalid strategies are rejected with contract errors, approved artifacts are
immutable/versioned, historical replay resolves the stored version, exports
are deterministic and secret-free, validation evidence is retained, approval
records are auditable, and approval is not conflated with execution success.

### Stop conditions

Application-source access, mutable or non-reproducible strategy versions,
secret-bearing exports, missing approval or execution-failure semantics, or an
unsafe execution boundary.

## Phase 12 — Backtest Job + Worker

### Goal

Execute validated strategy artifacts through durable, isolated backtest jobs.

### Scope

BYQ-owned native deterministic backtest execution, A-share execution rules,
frozen universe and strategy-version authorization, content-addressed input
and result manifests, job state machine, worker queue, resource/time limits,
result artifacts, retries/idempotency, object references/lifecycle, and
audit/observability.

The native engine MUST encode and test T+1, limit-up/limit-down, suspension,
lot-size, fees, stamp tax, cash, corporate-action, and stable blocked-trade
reason semantics. Input manifests MUST freeze signal/execution prices, status,
corporate actions, universe membership, strategy version, environment/engine
contract version, and reproducibility status. Result objects MUST retain
namespace/object identity, media type, size, and SHA-256 rather than embedding
unbounded result data in business rows.

### Non-goals

No live trading, distributed optimization, or Engineering Plane code mutation.

### Dependencies

Phases 8–11, worker deployment design, and artifact storage.

### Architecture constraints

Workers are independently deployable; BYQ owns business job state; DSH cannot
directly access business storage or worker internals. The engine is BYQ-owned
and deterministic; VectorBT and Community provider/runtime boundaries are not
backtest dependencies or compatibility paths. Universe authorization and
object deletion are enforced by BYQ using owner and live-reference checks.

### Acceptance criteria

Jobs are isolated, restartable, idempotent, resource-bounded, and produce
traceable result artifacts under contract tests. Golden regression fixtures
cover the A-share execution rules, authorized frozen universes, deterministic
input/result manifests, bounded retries, immutable result references, and
fail-closed deletion of referenced or tampered objects.

### Stop conditions

Unbounded execution, non-idempotent retries, mutable input identity, missing
A-share execution constraints, universe escape, non-reproducible manifests,
untrusted artifact execution, or deletion that ignores ownership/live
references.

## Phase 13 — Quant Research Agents

### Goal

Add specialized quant research roles using DSH presets/skills/subagents while
keeping domain authority in BYQ.

### Scope

Researcher roles, prompt/skill contracts, tool permissions, delegation policy,
traceable multi-agent orchestration, owner/actor authorization, human approval
integration, audit views, and DSH-run correlation.

### Non-goals

No second generic agent harness, no direct database tools, and no Engineering
Plane privileges in Product agents.

### Dependencies

Phases 7–12 and reviewed domain MCP contracts.

### Architecture constraints

Roles are DSH configuration where generic; domain invariants remain BYQ;
workflow trace and artifact state remain separate. Authorization, approval,
audit, and evidence-promotion decisions remain BYQ domain capabilities reached
through MCP; DSH supplies generic role and orchestration capability only.

### Acceptance criteria

Role capabilities are explicit, least-privileged, observable, and covered by
capability-isolation and end-to-end contract tests. Audit records correlate the
owner, actor, DSH run/session, domain action, result, and failure; approval
failures remain distinct from successful execution; and no role can bypass BYQ
invariants or promote unreviewed evidence.

### Stop conditions

Privilege escalation, role duplication of BYQ invariants, or a new generic
harness.

## Phase 14 — Quant Learning Loop

### Goal

Close the research → experiment → artifact → validation → backtest learning
loop with measurable feedback.

### Scope

Evaluation signals, experiment comparison, feedback lineage, repair/retry
policy, evidence promotion, and bounded agent iteration.

### Non-goals

No autonomous production trading, unbounded self-modification, or silent
strategy deployment.

### Dependencies

Phases 9–13, audit/approval policy, and reliable backtest results.

### Architecture constraints

Every loop step is bounded, reproducible, auditable, and mediated by BYQ
contracts; approvals cannot be replaced by prompts.

### Acceptance criteria

Learning runs have explicit budgets, lineage, stopping rules, human gates, and
replayable results. Promoted lessons retain evidence, validation, review,
provenance, and a controlled promotion history; ordinary chat output cannot
become trusted Quant knowledge directly.

### Stop conditions

Unbounded autonomy, missing rollback/approval, or feedback that cannot be
reproduced.

## Phase 15 — Engineering Plane / Code Improvement

### Goal

Enable controlled Engineering Plane assistance for repository changes without
weakening Product Plane isolation.

### Scope

EngineeringTask contracts, diagnostics, isolated worktrees, tests, draft PRs,
CI evidence, and human merge workflow.

### Non-goals

No direct main push/merge, production deploy, destructive migration, or
Product DSH source-write capability.

### Dependencies

All prior architectural boundaries, the development workflow, and GitHub/CI
permissions.

### Architecture constraints

Engineering changes use isolated worktrees and branches; Product and
Engineering privileges remain separate; humans retain the merge gate.

### Acceptance criteria

An EngineeringTask can produce a tested draft PR with architecture evidence,
CI results, self-review, and no automatic merge.

### Stop conditions

Missing isolation, unreviewed privilege expansion, CI bypass, or a request to
push/merge directly to `main`.

## BeyondQuant Productization Program

Phase 15 completion is not product completion. Phases 6–15 establish the
Headless Quant Research Platform Core: BYQ-owned quantitative contracts,
deterministic research and backtest capabilities, DSH-based quant roles,
WorkflowTrace, the Quant Learning Loop, and the Engineering Plane. Phases
16–23 productize that core for ordinary browser users while preserving the
Product/Agent/Quant/Data/Engineering plane boundaries.

The productization sequence is:

```text
Product API + durable data foundation
  → browser shell and visual parity
  → agent research workbench
  → quant workspace
  → user/platform settings
  → stock pool and paper trading
  → operations/deployment/observability
  → parity matrix and release candidate
```

Only the current phase named by `docs/roadmap/STATUS.md` may be implemented.
Phases 16–23 are future planning constraints and are not implementation
permission. Phase 16 may start only after Phase 15 is formally accepted. The
Community repository remains a read-only behavioral and visual reference;
existing code is evidence, not authorization to copy architecture.

## Phase 16 — Product API / BFF + Durable Data Migration Foundation

### Goal

Establish the browser-facing Product API boundary and the authoritative BYQ
Data Plane target needed for a safe, logical migration of validated Community
market cache data.

### Scope

- Gateway Product API / BFF with browser-oriented resource contracts;
- product authentication and session contract, including owner/actor scope;
- one product error envelope and safe diagnostic fields;
- pagination, filtering, sorting, cursor/offset policy, and bounded request
  cost contracts;
- versioned OpenAPI source and generated TypeScript client types;
- dashboard aggregation API;
- research-task, experiment, artifact, factor, strategy, and backtest APIs;
- approval, audit, Agent UI, and BYQ WorkflowTrace projection APIs;
- explicit `/api/product/data/status`-style data health and migration status
  projection;
- a BYQ Durable Market Data Storage ADR covering canonical storage, schema
  ownership, indexes, retention, refresh strategy, provenance, backup, and
  restore;
- a logical Community market-cache migration design, mapping, manifest, and
  validation plan;
- a complete Community frontend migration inventory.

The eventual resource paths are a design output, not a requirement to copy
these examples mechanically:

```text
/api/product/dashboard
/api/product/agents
/api/product/agents/{id}
/api/product/research/tasks
/api/product/research/tasks/{id}
/api/product/experiments
/api/product/artifacts
/api/product/factors
/api/product/strategies
/api/product/strategies/{id}
/api/product/backtests
/api/product/backtests/{id}
/api/product/approvals
/api/product/audit
/api/product/data/status
```

Community PostgreSQL is a read-only source. Migration must use logical
`SELECT`/`COPY OUT`/data-only export, validation and normalization, a
manifest, an idempotent import into the new BYQ Data Plane, and post-import
verification. A PostgreSQL physical data directory must never be copied,
mounted into BYQ, or used as BYQ authoritative storage. Only `data_source =
tushare` rows, or rows proven to be provider-independent canonical data, are
eligible; BaoStock and AKShare rows are excluded.

The migration contract must validate canonical symbols (`NNNNNN.SH`,
`NNNNNN.SZ`, `NNNNNN.BJ`), `YYYYMMDD` trade dates, units, numeric finiteness,
OHLC relationships, non-negative volume/amount, adjustment type, asset type,
source provenance, duplicate keys, stable ordering, lifecycle coverage, and
point-in-time semantics. Invalid data is quarantined and reported, never
silently repaired into canonical storage.

### Non-goals

- no complete browser UI;
- no Product API implementation beyond the contracts required by this phase;
- no live trading;
- no bulk or destructive migration;
- no physical PostgreSQL directory copy or mount;
- no Community database write, schema change, update, delete, or truncate;
- no reintroduction of BaoStock, AKShare, VectorBT, PydanticAI, or Hermes.

### Dependencies

Phase 15 acceptance, the current BYQ Gateway/Runtime Adapter/MCP boundary,
Phases 9–14 domain and learning contracts, ADR-0003 through ADR-0009, the
Community frontend and market-cache audit, and a reviewed durable-storage
ADR before any formal bulk import.

### Architecture constraints

Frontend calls Product API only. Product API calls BYQ domain services and the
Runtime Adapter through explicit contracts; it does not expose MCP, DSH,
internal Backend APIs, raw DSH events, provider credentials, or database
schemas. WorkflowTrace remains a framework-neutral BYQ projection. Business
state remains BYQ-owned; DSH does not access PostgreSQL or Redis directly.

The target data store is a new BYQ-owned authoritative store. Community
PostgreSQL is an evidence source only. Imports must be repeatable, idempotent,
auditable, conflict deterministic, and secret-free. Existing BYQ records must
not be overwritten by last-write-wins; the initial conflict policy is
`KEEP_NEW`, `VERIFY_EQUAL`, and `REPORT_MISMATCH`.

### Acceptance criteria

- Browser-oriented Product API contracts and auth boundary are complete;
- no MCP, DSH, raw DSH event, provider-token, or internal-storage exposure is
  present in the product contract;
- OpenAPI-generated types are possible from the versioned contract;
- dashboard, research, factor, strategy, backtest, approval, audit, Agent,
  and WorkflowTrace product projections are mapped;
- `COMMUNITY_FRONTEND_MIGRATION.md` and
  `COMMUNITY_MARKET_DATA_MIGRATION.md` are complete;
- the Durable Market Data Storage ADR is Accepted;
- a read-only migration dry-run can produce a manifest and quarantine report;
- the Community repository and database remain unchanged;
- no production bulk import is performed as part of this acceptance.

### Stop conditions

Unclear ownership/authentication, raw DSH schema leakage, an unaccepted
durable-storage decision, inability to prove source/provenance/units,
non-deterministic conflict behavior, a request to write Community data, or a
request to widen Product DSH capabilities.

## Phase 17 — Frontend Foundation

### Goal

Deliver the first browser-visible BeyondQuant application with a familiar,
clean, responsive shell based on the inspected Community UX.

### Scope

Create `apps/frontend` as a formal Vue 3 + Vite + TypeScript application using
the existing preferred direction: Vue Router, Pinia, Element Plus, ECharts,
Axios or a typed fetch client, OpenAPI-generated types, and Playwright. Build
the App Shell, Header, Sidebar, mobile bottom navigation, Router, auth
bootstrap, Product API client, design tokens/theme, responsive layout, error
boundary, loading skeletons, empty/error states, toasts, dialogs, and chart
foundation.

The first pages are Login, Home/Dashboard, System Status, and the user menu.
Community `App.vue`, router, store, auth flow, layout components, styles,
HomeView, and LoginView must be inspected first and classified in the frontend
migration inventory. Reuse visual language, spacing, cards, tables, icons,
loading states, and interaction patterns where they remain architecture
neutral. Rewrite auth and API bindings against Product API.

### Non-goals

No complete research workbench, agent workflow UI, paper trading, live
trading, operations control plane, or direct Community frontend copy.

### Dependencies

Phase 16 Product API/OpenAPI/auth contracts and the Community frontend
migration inventory.

### Architecture constraints

The frontend has no direct MCP, DSH, raw Backend-internal, Provider, or
database integration. It consumes only normalized BYQ Product API responses
and BYQ WorkflowTrace projections. The frontend must not depend on raw DSH
event schemas. Core frontend stack changes require an ADR.

### Acceptance criteria

- `apps/frontend` boots through the Product API boundary;
- Login, Dashboard, system status, user menu, loading, error, empty, and
  responsive states are covered;
- Playwright smoke tests run in CI;
- Community visual/UX parity is reviewed at layout and workflow level, not
  pixel-perfectly cloned;
- desktop, tablet, and mobile navigation have tested behavior;
- no Community source tree is copied wholesale.

### Stop conditions

Direct internal API/DSH/MCP coupling, raw DSH events in components, missing
auth ownership, a need to replace the selected frontend stack without an ADR,
or a wholesale frontend copy.

## Phase 18 — Agent Research Workbench

### Goal

Make the DSH-powered quant research experience the central, traceable browser
workflow while keeping all business authority in BYQ.

### Scope

Reference Community `AgentView.vue`, its session history, thinking/progress
components, approval cards, and assistant drawer, then redesign them around
DSH, `WorkflowTrace`, `ResearchTask`, `Experiment`, `Artifact`, and `Approval`.
Provide session create/resume, conversation, streaming answer, cancellation,
resume, error recovery, current task, subagent activity, tool/domain-action
visualization, WorkflowTrace, artifacts, evidence, approvals, and audit trail.
The layout should preserve the familiar conversation/context/result workbench:

```text
Research navigation | conversation | WorkflowTrace
                  artifact / evidence / chart / result
```

The browser receives normalized BYQ product events only. It must never show
raw DSH JSON, bearer tokens, provider keys, or internal runtime credentials.

### Non-goals

No second generic agent harness, DSH Web transport, direct database tool,
Engineering Plane capability, raw event-schema UI, or autonomous approval.

### Dependencies

Phases 13, 16, and 17; ADR-0003/0009; the BYQ WorkflowTrace contract; Product
API streaming/resume/cancel contracts; and the Quant Learning Loop evidence
and approval semantics.

### Architecture constraints

Frontend → Product API → Gateway/Runtime Adapter → DSH/MCP remains the only
product path. BYQ owns ResearchTask, Experiment, Artifact, Approval, audit,
authorization, and business idempotency. DSH owns generic session,
subagent, skill, and orchestration behavior.

### Acceptance criteria

- a browser user can create/resume a research session and send a prompt;
- streaming answers and cancellation/resume states are visible;
- current ResearchTask, subagents, tools, artifacts, evidence, approvals,
  errors, and audit are rendered through normalized product contracts;
- WorkflowTrace replay and ordering are stable;
- secret-safe and raw-DSH-schema contract tests pass;
- Playwright covers the core conversation and approval journey.

### Stop conditions

Raw DSH events in the frontend, browser access to MCP/DSH, model-supplied
identity/approval, unbounded streaming payloads, missing cancellation/replay
semantics, or Product DSH capability escalation.

## Phase 19 — Quant Workspace

### Goal

Expose the completed BYQ quant core as a coherent Research Workspace for
Factor, Strategy, and Backtest work.

### Scope

Reference Community `BacktestView.vue`, `StrategyView.vue`, `DemoChartView.vue`,
and related research UI. Build Product API-backed workflows for ResearchTask,
Experiment, Factor, Strategy, and Backtest.

Factor UI must cover definition, input universe, date range, compute state,
coverage, distribution, metrics, evaluation, and artifact lineage. Strategy UI
must cover draft editing, validation, immutable StrategyVersion, approval,
version history, and provenance. Backtest UI must cover submission,
progress/state, equity curve, benchmark, drawdown, annual return, Sharpe,
volatility, win rate, trade list, position history, blocked trade reasons,
fees/tax, artifacts, input manifest, and reproducibility. ECharts is the
default chart foundation and Community chart interaction is reference UX.

### Non-goals

No Community Strategy runtime, VectorBT, generated application-source write,
live trading, or direct provider/API binding from the browser.

### Dependencies

Phases 10–12 and 16–18, Strategy Artifact/Backtest ADRs, Product API contracts,
and the frontend migration classifications.

### Architecture constraints

Factor, strategy, approval, and backtest invariants remain BYQ-owned. Strategy
code remains a domain artifact. Backtest results are immutable references with
manifests; the UI displays normalized summaries and authorized result objects.

### Acceptance criteria

- Factor, Strategy, and Backtest flows are usable from one workspace;
- immutable versions, approvals, manifests, lineage, and reproducibility are
  visible and linkable;
- all requested result charts/tables/blocked reasons are available through
  Product API contracts;
- ECharts loading/empty/error/large-result states are tested;
- a browser flow can move from research to approved backtest without raw
  internal APIs.

### Stop conditions

Missing input identity, look-ahead/coverage ambiguity, execution-rule leakage
into the UI, mutable historical strategy state, raw result unboundedness, or
any attempt to restore excluded engines/providers.

## Phase 20 — User & Platform Settings

### Goal

Provide safe user, model, data, approval, artifact, and platform settings
without exposing credentials or collapsing Product and Operations privileges.

### Scope

Reference Community `UserProfileView.vue`, `UserModelsView.vue`,
`UserAssetsView.vue`, `UserAgentPolicyView.vue`, model settings components,
and approval center UX. Build Product API-backed pages for User Profile, Model
Settings, Data Provider Status, Tushare capability/permission status, Agent
Preferences, Approval Inbox, Artifacts/Assets, Storage Status, and System
Preferences.

All secret-bearing fields are write-only or masked. The browser may receive
only `configured: true/false`, provider status, capability, permission, and
masked metadata. It must never receive `DEEPSEEK_API_KEY`, `TUSHARE_TOKEN`,
`BYQ_PRODUCT_TOKEN`, MCP tokens, bearer tokens, or a decrypted credential.

### Non-goals

No browser-side secret management, direct provider credential calls, global
operations control from a normal user page, or automatic approval bypass.

### Dependencies

Phases 16–19, ADR-0004/0005/0009, Product auth/authorization contracts, and
the BYQ secret-safe error envelope.

### Architecture constraints

Backend/Gateway owns secret storage and capability evaluation. BYQ owns
RBAC/approval/audit and user asset ownership. Product settings cannot grant
Operations or Engineering privileges.

### Acceptance criteria

- users can manage profile, preferences, model profile, approval preferences,
  and owned assets;
- Tushare status is capability-based and secret-free;
- approval inbox and asset/storage status are auditable;
- unauthorized cross-owner reads/writes fail closed;
- browser/network/contract tests prove forbidden secret names and values do
  not appear in responses, traces, logs, or errors.

### Stop conditions

Secret exposure, user/operations privilege confusion, cross-owner access,
model-supplied approval authority, or frontend dependence on internal storage
schemas.

## Phase 21 — Stock Pool & Paper Trading

### Goal

Make stock-universe research and deterministic paper trading usable from the
browser while defining a new BYQ-owned paper-trading domain boundary.

### Scope

Reference Community `StockPoolView.vue`, `StockPoolDialog.vue`, and
`PaperTradingView.vue`, but inspect and classify their domain semantics before
implementation. Stock Pool covers user watchlists, research universes,
candidate pools, tags/groups, factor rankings, Agent recommendations,
provenance, snapshot versions, and historical membership. Reuse only
provider-independent semantics such as normalized membership, immutable
snapshots, and lineage; rewrite storage/API ownership in BYQ.

Paper Trading is simulation only and is not Backtest. Define BYQ-owned
contracts for portfolio, cash, positions, orders, fills, fees/tax, T+1,
limit rules, suspension, lot size, audit, strategy version, and decision
provenance. There is no live broker integration in this phase.

### Non-goals

No live broker, live order, broker credential, Community Agent Service paper
runtime, direct PostgreSQL access, or VectorBT/legacy provider path.

### Dependencies

Phases 10–12, 16–20, stock-pool/backtest invariants in the migration inventory,
and a future paper-trading domain ADR before implementation.

### Architecture constraints

Paper trading is a BYQ domain state machine with explicit idempotency,
approval, ownership, and audit. It cannot reuse Backtest as a hidden order
engine. Product DSH may propose actions through MCP but cannot mutate paper
state outside BYQ contracts.

### Acceptance criteria

- users can create and inspect versioned pools/watchlists and provenance;
- historical membership and snapshot identity are visible;
- a user can create a simulation account, inspect portfolio/cash/positions,
  submit approved simulated orders, see fills/fees/blocked reasons, and audit
  decision provenance;
- T+1, limit, suspension, lot, and conflict semantics have BYQ contract/golden
  tests;
- no live broker or external execution call exists.

### Stop conditions

Paper/Backtest state conflation, missing owner/idempotency/audit semantics,
unbounded or non-deterministic fills, broker credential exposure, or unclear
stock-pool domain invariants.

## Phase 22 — Operations and Deployment

### Goal

Operate BeyondQuant Next safely in production with secret-safe, role-protected
observability and tested backup/restore/deployment procedures.

### Scope

Reference Community operations pages: `AccessControlOperationsView`,
`GraphOperationsView`, `ModelOperationsView`, `RuntimeOperationsView`, and
`SystemMaintenanceWorkbench`. Redesign them for the BYQ topology and Product
API operations projection, covering Gateway, Runtime Adapter, DSH sessions,
MCP, Backend, worker, data provider, queues, object store, database, Redis,
WorkflowTrace, audit, disk/storage, and migration status.

The Operations UI is read-mostly, secret-safe, and role protected. Deployment
work includes production Compose/topology, persistent-volume strategy,
database/object-store backup, restore, migration, health/readiness checks,
resource limits, log rotation, upgrade procedure, and rollback. Community
market-data migration must be production-safe, backup-tested, and
restore-tested before release.

### Non-goals

No restoration of the Community old runtime, direct Product DSH operations,
unprotected destructive controls, live trading, or automatic main/deployment
mutation.

### Dependencies

Phases 16–21, accepted durable storage and paper-trading decisions, current
BYQ topology, and the Engineering Plane human gate.

### Architecture constraints

Operations endpoints are separate from normal user Product API permissions.
Secrets are never rendered or returned. Database and migration controls are
explicitly authorized, audited, and fail closed. DSH remains unable to access
business storage directly. Deployments preserve independent service upgrade
and fault-isolation boundaries.

### Acceptance criteria

- role-protected operations views show all required service/data/trace health;
- readiness/health, backup, restore, migration, resource, and log procedures
  are executable and documented;
- Community cache migration dry-run/import/verification is repeatable and
  rollback-safe after the Data Storage ADR;
- observability correlates Product request, BYQ trace, DSH session/run, domain
  action, job, artifact, and audit without raw DSH leakage;
- production deployment tests pass with no secret rendered in UI/logs.

### Stop conditions

Unprotected operations, destructive defaults, untested restore, secret-bearing
diagnostics, topology drift that violates the architecture, or a migration
that cannot be rolled back or verified.

## Phase 23 — Community Feature Parity and BeyondQuant Next Release

### Goal

Deliver BeyondQuant Next as a product-level release candidate: familiar to
Community users, architecturally BYQ/DSH-native, traceable, reproducible,
auditable, and secret-safe.

### Scope

Create and maintain `COMMUNITY_FEATURE_PARITY_MATRIX.md`. Every Community page,
capability, component, dialog, chart, setting, and operations surface must be
marked `PORTED`, `REDESIGNED`, `REPLACED`, `DROP`, or `DEFERRED`, with a reason
for every `DROP` and a target/acceptance reference for every non-drop item.

The matrix must cover Home, Login, Agent, Research, Strategy, Backtest, Stock
Pool, Paper Trading, Profile, Models, Assets, Agent Policy, Operations, and
their shared components/dialogs/charts/settings. It must explicitly record
that Community PydanticAI/Hermes, raw Agent schema/API coupling, BaoStock,
AKShare, and VectorBT are dropped or replaced.

### Product acceptance

An ordinary browser user can log in, view Dashboard, talk to 小巴, create a
ResearchTask, observe multiple quant agents, view WorkflowTrace, obtain
Tushare data, use validated Community historical cache data, perform factor
research, generate and validate a Strategy Draft, inspect Strategy Versions,
complete human Approval, submit a Backtest, inspect charts/trades/metrics,
open Artifact/Evidence/Lineage, use Stock Pool and Paper Trading, manage
Model/Data/User settings, and view Operations status.

The complete flow is traceable, reproducible, auditable, and secret-safe.

### Golden journey and acceptance tests

Add a Playwright golden journey:

```text
Login → Dashboard → ask 小巴 → ResearchTask → Factor → Strategy
  → Approval → Backtest → Result → Artifact → Stock Pool / Paper Trading
```

CI must execute the core smoke journey, API contract checks, secret-boundary
checks, migration verification checks, responsive smoke coverage, and the
required architecture tests. The release candidate is not complete until
these checks pass and the human review gate is reached.

### Non-goals

No direct main merge, no automatic release promotion, no live broker trading,
no raw Community architecture migration, no excluded provider/engine/runtime,
and no claim that Phase 15 alone is a product release.

### Dependencies

Accepted Phase 16–22 contracts/ADRs, completed migration verification,
production backup/restore evidence, parity matrix, and passing CI golden
journey.

### Architecture constraints

BeyondQuant Next preserves Product Plane, Agent Plane, Quant Domain Plane,
Data Plane, and Engineering Plane ownership. Frontend depends only on Product
API and WorkflowTrace projections. Generic agent capabilities remain in DSH;
domain invariants remain in BYQ; Community is not the new architecture.

### Stop conditions

Any missing core product journey, unresolved parity classification, failed
secret/trace/reproducibility/restore check, raw DSH coupling, live-trading
scope creep, or an attempt to bypass the human release gate.

## BeyondQuant Product Completion Program

Phases 5-15 established the Core Platform. Phases 16-23 established a Product
Skeleton, not a final release. Phase 23 produced a baseline parity matrix and
browser smoke, but did not complete durable user identity, full Community UX
depth, complete quant workspace workflows, approval/artifact/lineage product
surfaces, historical market-data migration, or production operations.

Phases 24-30 are the Product Completion Program. Each phase is implemented in
one isolated worktree/branch, with independent tests, one Draft PR, one human
review gate, and a Chrome MCP browser gate where UI is affected. A phase must
not be marked complete merely because a Vue file, endpoint, or page exists.
Required features must be demonstrably working through Product API, real
browser flows, persistence where required, error/loading/empty states, and
feature checklist evidence.

## Phase 24 — Durable User Identity & Authentication

### Goal

Replace Product Token browser login with a durable BYQ-owned user identity,
password authentication, secure session, and owner isolation.

### Key acceptance

BYQ-owned User domain with password hashing; username/password login through
Gateway Product API; secure HTTP-only session cookie or equivalent ADR-
approved session boundary; logout/session revoke/expiration; change password;
bootstrap admin; admin/user authorization; disabled users cannot login; owner
isolation across research, strategy, backtest, stock pool, paper account,
agent session, approval, and audit. Browser login shows username/password, not
Product Token. Product Token remains internal/service bootstrap only.

## Phase 25 — Community Frontend Full UX Restoration

### Goal

Restore Community core information architecture, responsive shell, shared
components, and real-data dashboard depth.

### Key acceptance

App shell/sidebar/header/navigation match Community familiarity while using
BYQ contracts; dashboard uses real BYQ data for market/data status, recent
research, recent agent runs, recent strategies/backtests, pending approvals,
stock pools, and paper summary; shared cards/tables/pagination/dialogs/forms/
status badges/empty/loading/error/chart wrappers are reusable; Chrome MCP
visual comparison against Community is performed and recorded.

## Phase 26 — Full Quant Workspace

### Goal

Turn the Phase 19 skeleton into a real Factor, Strategy, and Backtest
workspace.

### Key acceptance

Factor list/create/definition/universe/date range/compute/status/coverage/
results/history/artifact linkage; strategy list/draft/editor/validation/
version/history/approval status/backtest linkage; backtest create/status/
retry where allowed, metrics, ECharts equity/drawdown/trades/positions/blocked
reasons/fees/tax/manifest/lineage; no fake metrics or fake charts.

## Phase 27 — Research, Artifact and Approval Center

### Goal

Productize the new BYQ Research/Artifact/Lineage/Approval domain capabilities.

### Key acceptance

ResearchTasks, Experiments, Artifacts, Evidence, Lineage, and Approvals are
visible and manageable; artifact browser shows real metadata/hash/lineage/
provenance without embedding large objects; lineage view is based on real
BYQ lineage; Approval Inbox supports pending/approved/rejected and human
approve/reject while keeping execution outcome separate.

## Phase 28 — Historical Market Data Migration & Data Center

### Goal

Complete logical migration of validated Community Tushare historical cache and
expose a real Data Center.

### Key acceptance

Read-only Community audit with real table/row/date/symbol/source statistics;
validation/normalization/quarantine/manifest/import/verification are executed
and idempotent; no physical PostgreSQL directory copy; BaoStock/AKShare/
VectorBT remain DROP; deterministic conflict policy; incremental Tushare
refresh; Data Center shows datasets/coverage/sync/provider/row counts/quality/
migration/quarantine/refresh status without secrets.

## Phase 29 — Platform Administration & Operations Completion

### Goal

Turn Settings/Operations into an actual administration and operations surface.

### Key acceptance

User administration, model management, data management, agent management,
runtime operations, backup/restore with a real restore test, safe logging/
WorkflowTrace/audit/job-failure lookup without leaking credentials.

## Phase 30 — True Community Feature Parity & BeyondQuant Next v1.0 RC

### Goal

Final product release candidate with real Community feature parity and
multi-user golden journeys.

### Key acceptance

New `COMMUNITY_FEATURE_PARITY_MATRIX_V2.md` with per-feature
PASS/REDESIGNED_PASS/INTENTIONAL_DROP/FAIL; no DEFERRED items remain in the
release conclusion; Chrome MCP browser comparison against Community; complete
golden journey through real Product API with no mocks/direct Backend/MCP/DSH;
multi-user isolation E2E; Phase 30 cannot complete while required items are
missing.

## Phase 31 — PostgreSQL Single Domain Store (ADR-0016)

### Goal

Replace SQLite with PostgreSQL as the single BYQ domain-store engine so
production concurrency, role isolation, backup/restore, and the ADR-0013
durable market-data target are supported, and later feature phases have one
connection/dialect path.

### Scope

- Add a PostgreSQL service and bootstrap databases/roles
  (`byq_domain`, `byq_domain_test`, `byq_bootstrap`).
- Introduce `services/backend/app/db.py` (SQLAlchemy Core + psycopg) as the
  single shared SQL layer and migrate ResearchStore as the reference pattern.
- Migrate remaining stores (UserAuth, UserPolicy, PaperTrading, Backtest,
  AgentResearch, LearningLoop, Engineering) to the same layer; remove SQLite
  code paths and `BYQ_DOMAIN_DB_PATH`.
- Add idempotent logical SQLite -> PostgreSQL data migration with
  `KEEP_NEW`/`VERIFY_EQUAL`/`REPORT_MISMATCH`, plus verification.
- Add `pg_dump`/`pg_restore` backup/restore drill as a gate before ADR-0013
  bulk market-data import.
- Keep LocalObjectStore (filesystem) unchanged; never store large blobs in
  PostgreSQL.

### Architecture constraints

DSH/MCP/Gateway/Product boundaries are unchanged; DSH never accesses
PostgreSQL directly. Community PostgreSQL remains read-only evidence.
Detailed plan: `docs/architecture/POSTGRESQL_MIGRATION_PLAN.md`.

### Acceptance criteria

All backend tests run against the PostgreSQL test database; no SQLite code
path remains; public store method shapes are unchanged; data migration is
idempotent and verified; backup/restore drill passes; compose/docs are
updated.

## Phase 32–40 — Community Product-Depth Completion

These phases are the active continuation of the Product Completion Program.
`STATUS.md` selects exactly one next phase. The per-surface checklist in
`COMMUNITY_FULL_PARITY_PHASE_DETAILS.md` and the dependencies in
`COMMUNITY_FULL_PARITY_PLAN.md` refine this normative scope but do not replace
this plan or authorize work past the current phase.

Every phase uses one isolated worktree/branch/PR, real Product API flows,
contract and owner-isolation tests, Chrome DevTools MCP evidence, and a
Community feature checklist. Mock-only Playwright navigation is useful UI
regression coverage but is not product acceptance evidence.

### Phase 32 — Backtest workspace depth (`COMPLETE`)

Delivered the immutable `signal_snapshot` submit path, create wizard, result
workspace depth, compare/delete/mobile flows, and browser evidence. The
strategy-source → `signal_snapshot` producer was deliberately excluded by
ADR-0017 and transferred to D-0002 / Phase 40 pending a dedicated ADR.

### Phase 33 — Strategy workspace depth (`COMPLETE`)

Delivered durable strategy drafts, soft-supersede delete, immutable versions,
version history, backtest counts, read-only version detail, Product API/MCP
contracts, and browser evidence. D-0009–D-0012 are explicitly assigned to
Phase 40 and do not remain attached to the completed phase.

### Phase 34 — Stock Pool depth (`COMPLETE`)

ADR-0020 accepts the BYQ Stock Pool contract for
mutable pool identity, immutable membership snapshots, version/fingerprint,
custom/index/dynamic provenance, weight validation, activation/deactivation,
delete semantics, and references from Paper Trading/research/backtest.

Delivered owner-scoped catalog/detail, member and weight editing through new
snapshots, index constituents, filter conditions, historical snapshots,
lifecycle actions, mobile cards, Product API routes, and MCP `byq_pool_*`
capabilities. All five detail tabs use persisted data. Real Product API Chrome
MCP evidence and the Community checklist are recorded under
`docs/evidence/phase-34/`.

### Phase 35 — Paper Trading depth (`COMPLETE`)

Add persisted snapshots, manual settlement, order detail, BYQ asset-bundle
import/export, explicit risk controls, and complete ledger wiring without live
broker integration or conflating Paper Trading with Backtest.

Delivered all six persisted tabs, exact T+1 and cash/ledger semantics,
immutable manual settlement, frozen Stock Pool binding, versioned controls,
auditable immediate order results, portable digested bundles, Product API and
bounded read-only MCP projections, real-browser E2E, and Chrome MCP evidence.

### Phase 36 — Agent workbench depth (`COMPLETE`)

Implement curated WorkflowTrace cards, assistant drawer, thinking and
approval panels, and actionable strategy/stock/optimization projections under
Accepted ADR-0018. Phase 36 owns the Agent-specific components required for
its exit criteria; Phase 40 may generalize proven components later and is not
a prerequisite.

Delivered the closed ADR-0018 card/activity contract end to end, owner-scoped
Gateway hydration for domain-backed cards, bounded public activity and answer
projections, actionable workbench cards, local/global approval surfaces,
conversation starters, and a responsive Xiaoba assistant drawer. Real Product
API Chrome MCP evidence and the Community-derived checklist are stored under
`docs/evidence/phase-36/`.

### Phase 37 — My Space depth (`COMPLETE`)

Implement audited model credential CRUD/binding, asset re-import, and Agent
Policy preset/rule CRUD under Accepted ADR-0019. Secrets remain write-only/
masked and never enter browser responses or traces. Phase 37 owns the specific
model-settings component required for acceptance; Phase 40 may generalize it
later and is not a prerequisite.

Delivered owner-scoped encrypted credential lifecycle, model profiles and
Product Agent binding with private runtime resolution; canonical digested
workspace asset re-import with new owner-safe identities and honest backtest
archives; and effective Agent Policy presets/rule CRUD with audit and platform
approval precedence. Real Product API Chrome MCP evidence and the
Community-derived checklist are stored under `docs/evidence/phase-37/`.

### Phase 38 — Operations workbenches (`COMPLETE`)

Replace placeholder operations routes with real RBAC/audit-protected
projections and bounded actions under Accepted ADR-0019 and ADR-0022.
Phase 38 owns its operations-specific components; Phase 40 may generalize
proven components later and is not a prerequisite. PostgreSQL market-cache
status replaces Community Redis assumptions.

Delivered nine responsive administrator workbenches backed by a bounded
`operations.v1` Product API projection, normalized Runtime Adapter session and
DSH usage accounting, and an admin-only versioned/idempotent/audited monitoring
threshold write. The browser sees no secrets, raw DSH events, SQL/runtime
control surface, Redis assumption, or direct internal-service endpoint. Real
Product API desktop/mobile Chrome evidence and the Community checklist are
stored under `docs/evidence/phase-38/`.

### Phase 39 — Data Center / Data Sync depth (`COMPLETE`)

Implement Tushare-only source configuration, connection test, sync jobs, and
coverage audit after ADR-0019. BaoStock and AKShare remain DROP.

Delivered admin-only write-only Tushare credential lifecycle, bounded
connection testing, durable/idempotent asynchronous daily-bar jobs with
per-symbol outcomes, canonical PostgreSQL import, and honest observed coverage
and quality audit. All browser calls use Product API; real desktop/mobile Chrome
MCP evidence and the Community checklist are stored under
`docs/evidence/phase-39/`.

### Phase 40 — Shared components and final parity closure (`COMPLETE`)

Finish reusable product components and resolve every transferred D-item,
including the signal producer decision. Re-run the parity matrix with no
unexplained PARTIAL/MISSING item and execute a real-Product-API, no-mock,
multi-user golden journey before reopening the v1.0 RC gate.

Delivered the ADR-0023 two-tier isolated signal producer, closed D-0002 and
D-0009–D-0012, and explicitly dropped observation-triggered D-0003 after a
zero-orphan audit. Direct paginated strategy projections, shared state and
pagination components, deep immutable strategy fields and owner approval are
covered by scale/component/contract tests. A fresh Compose deployment passed
the no-mock two-user Product API journey and Chrome desktop/mobile review under
`docs/evidence/phase-40/`; the v1.0 RC review gate is reopened.

### Post-Phase 40 maintenance — DSH Upgrade Lane (`SCHEDULED`)

Build the repeatable compatibility, dependency-evidence, and isolated upgrade
workflow defined in `DSH_UPGRADE_LANE.md`. This task does not block Product
Completion phases. A critical upstream security advisory may promote it into a
dedicated earlier maintenance change under ADR-0003.

## Post-parity Product Experience Program

The maintainer postponed the v1.0 RC review on 2026-08-23 and selected the
conversation-first direction recorded in ADR-0024. The detailed source of
truth is `FRONTEND_EXPERIENCE_PLAN.md`; every phase remains independently
reviewable, testable, rollback-capable, and previewed from merged `main`.

### Phase 41 — Product experience baseline (`COMPLETE`)

Accept ADR-0024; inspect and classify the current BYQ and read-only Community
shell/session/theme/settings evidence; fix the single-level information
architecture, durable conversation ownership, semantic appearance contract,
Phases 42-48 acceptance sequence, and post-merge preview requirement. No
runtime or UI implementation is claimed in this decision phase.

### Phase 42 — Conversation-first Product shell (`NEXT`)

Implement the single-level sidebar, compact toolbar, default Xiaoba route,
recent-conversation section, bottom user entry and mobile drawer while
preserving every existing capability through routes or explicit relocation.
Use global semantic tokens and current Product API only.

### Phase 43 — Durable conversations and Xiaoba workspace (`PLANNED`)

Implement the owner-scoped BYQ conversation catalog, titles/lifecycle/search,
restart-safe normalized replay, and centered chat workspace with bounded
activity/context disclosures.

### Phase 44 — User center and durable appearance (`PLANNED`)

Consolidate Profile, Assets, Models, Agent Policy and Paper Trading access.
Implement `ui-preferences.v1`, system/light/dark modes, the closed accent
palette, global theme application and cross-device persistence.

### Phase 45 — System Settings dialog (`PLANNED`)

Embed the existing bounded administrator operations and Data Center surfaces
in a route-backed two-column large dialog/full-screen mobile surface without
weakening Product API RBAC or audit.

### Phase 46 — Core management workspace redesign (`PLANNED`)

Unify Stock Pool, Strategy and Backtest catalog/detail interactions, visual
hierarchy, Workflow-card deep links, charts and responsive behavior while
preserving every completed domain invariant and deep result surface.

### Phase 47 — Interaction, responsive and accessibility closure (`PLANNED`)

Standardize global states and controls, unsaved-change behavior, keyboard/focus,
responsive content and the complete theme/chart accessibility matrix.

### Phase 48 — Product coherence golden journey (`PLANNED`)

Run a fresh no-mock, two-user desktop/tablet/mobile Product journey across
conversation, pool, strategy, approval, signal, backtest, history, assets,
models, appearance and administrator settings. Reconcile relocated Community
capabilities and reopen, but do not automatically pass, the human v1.0 RC
review.
