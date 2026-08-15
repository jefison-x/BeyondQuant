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
