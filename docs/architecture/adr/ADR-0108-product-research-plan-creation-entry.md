# ADR-0108 — Foreground Product research-plan creation entry

- Status: **Accepted** (2026-10-08). The maintainer accepted the foreground Product research-plan
  creation entry, recorded verbatim as: **“好的，接受，继续。”** Implementation, qualification,
  PR and release gates remain separate.
- Scope: for an **existing** research task, create a research **execution plan** through the
  Gateway/Product API, reusing the existing `create_execution_plan` contract (owner+workspace,
  the task's conversation, explicit business references, idempotency). The already-Accepted
  ADR-0107 consumer then auto-continues the judgment turn.
- Explicitly **not**: no new MCP write tool, no generalized task system, no change to the fixed
  DSH version/permissions, no Phase advance, no default promotion.

## Current authority (not historical)
The current authority is the Clean Break baseline (ADR-0088 + Clean Break ADRs 001–006, which
supersede the pre-Clean-Break product ADRs including the historical **ADR-0085**) and the
Accepted ADR-0097/0098/0107. The historical ADR-0085 is **not** cited as current authority.

## Reused contract (no rebuild)
`ResearchExecutionPlanMixin.create_execution_plan(task_id, payload, *, trusted_context,
require_active_grant=False, bind_grant_references=False)` (`research_execution_plan.py:190`):
- owner/workspace from the trusted context via `_plan_task`; the caller cannot choose them;
- the task's bound conversation via `_require_conversation`; a caller-forged conversation is
  rejected;
- the closed `_create_request` supplies the idempotency key (+ optional iteration/references);
  an exact key+body replay returns the **current** plan projection and writes no second plan (the
  projection may already reflect later advances; it is not an immutable creation receipt), while a
  conflicting body raises `IdempotencyConflict`;
- every create reference is resolved to a real, owner/workspace/task-scoped domain row inside the
  create transaction; the `research_task` reference is bound exactly to this task and the
  `conversation` reference exactly to this task's bound conversation (a same-owner sibling is
  refused); a foreign, nonexistent or unverifiable reference fails closed;
- a continuation grant is rejected (`require_active_grant`/`bind_grant_references`); only a
  foreground caller with explicit domain references may create the plan.

## New foreground entry (minimal)
- **Backend**: `POST /v1/research/tasks/{task_id}/execution-plan` -> `create_execution_plan`
  with the Gateway-derived trusted owner/workspace context.
- **Gateway/Product**: a route that derives owner/workspace from the **durable user identity**
  (not a caller-supplied value) and calls the Backend.
- **Rejections**: cross-user; foreign/unknown references; a background continuation grant;
  caller-forged conversation; idempotency conflict.
- Only the existing domain model references and approval rules; the research-plan **result
  transaction** remains the unique plan advance (the ADR-0107 consumer never writes the plan).

## Boundary
- Minimal foreground wiring only. Any UI entry reuses the current research-task page norms; no new
  wizard or arbitrary feature.
- Real browser acceptance goes through the Gateway/Product API only; a legal task with real
  references -> plan -> consumer -> ACP judgment -> result/exact ACK -> page readback. A
  `proposal=null` closure is not claimed as an effective plan advance.
- Missing concrete domain prerequisites must be reported with evidence; no fabricated business
  results. Rollback = disable the new entry and restore the previous image/config, preserving the
  ADR-0107 additive tables/evidence.
- No push/merge/deploy/default/Phase/tag. Generic Agent recovery belongs to DSH; process stop to
  the container layer; BYQ keeps business safety only. Draft A (lost-runner) remains paused.
