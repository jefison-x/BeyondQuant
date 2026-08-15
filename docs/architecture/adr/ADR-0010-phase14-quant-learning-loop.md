# ADR-0010: Phase 14 Quant Learning Loop

- Status: Accepted
- Date: 2026-08-16
- Decision scope: Phase 14 Quant Domain learning and evidence promotion

## Context

Phases 9-13 established durable BYQ ResearchTask, Experiment, Artifact,
Factor, StrategyVersion, Approval, deterministic Backtest, and quant Agent
role state. The repository still lacks a controlled path by which evaluated
evidence can become trusted quantitative knowledge. Community implementations
provide evidence compaction, bounded agent execution profiles, retryable
error classification, and deterministic trajectory eval fixtures, but no BYQ
learning-loop or lesson-promotion state machine.

The learning loop must be bounded and auditable: ordinary chat output must not
become trusted quant knowledge directly, and agent iteration must not become
unbounded or prompt-driven.

## Decision

1. BYQ owns a `LearningRun` state machine. A run is owner/task-scoped, stores
   an explicit `max_iterations` and `max_repairs` budget plus optional
   deterministic stopping rules, and transitions
   `active -> awaiting_review -> completed|failed|cancelled`.
2. Each run iteration is an append-only, ordered, idempotent BYQ event. Failed
   iterations may be retried within the explicit repair budget. When the
   iteration budget, repair budget, or a matching stopping rule is reached, the
   run becomes `awaiting_review`; only a trusted human reviewer can approve or
   reject it. A terminal run is immutable and replayable through its ordered
   iteration history.
3. BYQ owns `EvaluationSignal` records. Each signal references one validated
   Artifact, names one finite metric, and retains task/experiment lineage and
   provenance. `compare_experiments` returns a deterministic metric comparison
   for two experiments and never invents missing values.
4. BYQ owns `Lesson` evidence promotion. A proposed lesson must cite at least
   one validated Artifact or EvaluationSignal as evidence; plain chat content
   cannot be promoted by itself. Lesson state is
   `proposed -> approved|rejected|superseded`, and every promotion decision is
   retained as an ordered history record with reviewer, decision, rationale,
   and timestamp.
5. Backend owns all learning-loop persistence and invariants. Agent-to-domain
   calls use normalized BeyondQuant MCP tools. DSH generic orchestration may
   propose iterations or lessons, but cannot bypass budgets, stopping rules,
   human review, provenance, or BYQ storage boundaries.

## Consequences

- Agent iteration is bounded and has explicit human gates and stopping rules.
- Promoted lessons retain evidence, validation, review, provenance, and
  promotion history.
- CI can exercise budgets, idempotency, deterministic comparison, promotion
  gates, and secret rejection without a model credential.
- No new generic agent harness, DSH runtime fork, or direct business-storage
  access is introduced.
