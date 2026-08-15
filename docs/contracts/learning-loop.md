# Quant Learning Loop Contract — Phase 14

## Ownership

BYQ owns bounded learning runs, ordered iteration history, evaluation signals,
experiment comparison, and lesson evidence promotion. DSH may propose generic
agent iterations, subagent work, or lesson candidates, but every budget,
stopping rule, human gate, validation check, and promotion decision is a BYQ
domain contract.

## Learning runs

A `byq_learning_run_start` request declares an owner/task-scoped run with an
explicit `max_iterations` and `max_repairs` budget plus optional deterministic
stopping rules. A run transitions
`active -> awaiting_review -> completed|failed|cancelled`.

Iterations are append-only, ordered, and idempotent. A failed iteration may
be retried only within the repair budget. Reaching the iteration budget,
repair budget, or a matching stopping rule moves the run to
`awaiting_review`; only a trusted human reviewer may approve or reject it.
The initiating actor cannot review its own run.

## Evaluation signals and comparison

An evaluation signal names one finite metric and references a validated BYQ
Artifact. It retains task/experiment lineage and provenance. Experiment
comparison is deterministic, requires signals for both experiments, and never
invents a missing value.

## Lesson promotion

A lesson proposal must cite at least one validated Artifact or EvaluationSignal
as evidence. Plain chat content is not trusted quantitative knowledge by
itself. Lesson state is `proposed -> approved|rejected|superseded`, and every
promotion decision is retained as an ordered history record with reviewer,
decision, rationale, and timestamp. The initiating actor cannot promote its
own lesson.

## Stability

Backend storage remains an implementation detail. Agent-to-domain calls use
normalized BeyondQuant MCP tools; DSH never receives direct business-storage
access or authority to bypass these invariants.
