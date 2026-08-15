# BeyondQuant Implementation Plan

This is the repository roadmap for autonomous development. Only the current
phase may be implemented in a normal phase branch. Later phases are planning
constraints, not permission to pre-build product scope.

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

Factor definitions, input snapshots, computation metadata, evaluation,
results as artifacts, and leakage/look-ahead checks.

### Non-goals

No strategy execution or portfolio/backtest job orchestration.

### Dependencies

Phases 8–9 and reviewed quant methodology contracts.

### Architecture constraints

Computation runs in BYQ workers/services; DSH proposes or invokes domain
operations through MCP and cannot bypass validation.

### Acceptance criteria

Deterministic fixture runs, provenance, missing-data/temporal checks, and
artifact lineage are tested and reproducible.

### Stop conditions

Look-ahead leakage, non-reproducible inputs, or factor invariants enforced only
by prompts.

## Phase 11 — Strategy Artifact + Validation

### Goal

Represent strategy code/configuration as a validated, auditable domain
artifact.

### Scope

StrategyDraft/StrategyArtifact schema, validation, approval gates, provenance,
versioning, and MCP operations.

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
immutable/versioned, and execution permissions are auditable.

### Stop conditions

Application-source access, missing approval semantics, or an unsafe execution
boundary.

## Phase 12 — Backtest Job + Worker

### Goal

Execute validated strategy artifacts through durable, isolated backtest jobs.

### Scope

Job state machine, worker queue, resource/time limits, result artifacts,
retries/idempotency, and audit/observability.

### Non-goals

No live trading, distributed optimization, or Engineering Plane code mutation.

### Dependencies

Phases 8–11, worker deployment design, and artifact storage.

### Architecture constraints

Workers are independently deployable; BYQ owns business job state; DSH cannot
directly access business storage or worker internals.

### Acceptance criteria

Jobs are isolated, restartable, idempotent, resource-bounded, and produce
traceable result artifacts under contract tests.

### Stop conditions

Unbounded execution, non-idempotent retries, or untrusted artifact execution.

## Phase 13 — Quant Research Agents

### Goal

Add specialized quant research roles using DSH presets/skills/subagents while
keeping domain authority in BYQ.

### Scope

Researcher roles, prompt/skill contracts, tool permissions, delegation policy,
and traceable multi-agent orchestration.

### Non-goals

No second generic agent harness, no direct database tools, and no Engineering
Plane privileges in Product agents.

### Dependencies

Phases 7–12 and reviewed domain MCP contracts.

### Architecture constraints

Roles are DSH configuration where generic; domain invariants remain BYQ;
workflow trace and artifact state remain separate.

### Acceptance criteria

Role capabilities are explicit, least-privileged, observable, and covered by
capability-isolation and end-to-end contract tests.

### Stop conditions

Privilege escalation, role duplication of BYQ invariants, or a new generic
harness.

## Phase 14 — Quant Learning Loop

### Goal

Close the research → experiment → artifact → validation → backtest learning
loop with measurable feedback.

### Scope

Evaluation signals, experiment comparison, feedback lineage, repair/retry
policy, and bounded agent iteration.

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
replayable results.

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
