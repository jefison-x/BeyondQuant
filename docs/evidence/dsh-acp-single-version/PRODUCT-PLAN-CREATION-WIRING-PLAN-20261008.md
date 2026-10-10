# Product research-plan creation — minimal reviewable wiring plan (2026-10-08)

Status: **Accepted + implemented (2026-10-08, ADR-0108).** The maintainer accepted the foreground
Product research-plan creation entry, recorded verbatim as **“好的，接受，继续。”** The minimal
foreground wiring is implemented (Backend + Gateway routes, reference binding/validation, tests);
it is **not merged, deployed or promoted**. No new MCP write tool, no generalized task system, no
DSH fixed-version/permission change, no Phase advance.

## The gap (proven)
No wired Product/MCP/Backend path creates a research **execution plan**. `byq_research_task_create`
(MCP, `services/mcp/src/server.ts:1787`) -> Backend `POST /v1/research/tasks`
(`services/backend/app/main.py:2642`) -> `research.create_task` creates the task + conversation
but **no plan**. `ResearchExecutionPlanMixin.create_execution_plan`
(`services/backend/app/research_execution_plan.py:190`) has **no non-test caller**. The ACP
judgment fixtures insert `research_execution_plans` directly. Product/Gateway expose research
**reads** only.

## Existing contract to reuse (no rebuild)
- `create_execution_plan(task_id, payload, *, trusted_context, require_active_grant=False,
  bind_grant_references=False)` (`:190`):
  - **owner/workspace**: from `trusted_context` via `_plan_task` (`:197`); the caller cannot
    choose them.
  - **conversation**: `_require_conversation(task)` (`:204`); the task's bound conversation.
  - **idempotency**: the closed `_create_request(payload)` supplies `idempotency_key` (+ optional
    `iteration`, `last_progress_identity`, `references`); replay with the same key+hash returns the
    same projected plan, else `IdempotencyConflict` (`:209-214`).
  - **grant**: `require_active_grant`/`bind_grant_references` are explicitly **rejected**
    (`:198-203`) — a continuation permission can never authorize plan creation; only a foreground
    caller with explicit domain references may create the plan (ADR-0085 P4).
  - The plan stage comes from the references; a `judgment_turn` stage is where the ADR-0107
    consumer then acts.
- The plan contract is `packages/contracts/research_execution_plan.py` (`new_plan` /
  `plan_at_stage` / `validate_plan`).

## Minimal wiring options (choose one; no task-system rebuild)
1. **New foreground Backend route + Gateway/Product command** `POST /v1/research/tasks/{id}/
   execution-plan` -> `research_store.create_execution_plan(task_id, payload, trusted_context=
   <Gateway-derived owner/workspace>)`. The browser/Product sends explicit references + an
   idempotency key; the Backend derives owner/workspace/conversation.
2. **New MCP tool** `byq_research_plan_create` (Agent Plane) that calls the same store method.
   Reuses the existing MCP->Backend proof/admission contract; a foreground Agent action.

Recommended: option 1 for the browser/Product end-to-end chain (option 2 is complementary for
Agent-driven plans). Both call the existing `create_execution_plan`; neither creates a new
task/plan system.

## Can this be wired within the Accepted scope?
- **Code fact (not an authority claim):** `create_execution_plan` currently **rejects** a
  continuation grant — `require_active_grant`/`bind_grant_references` raise
  `InvalidTransition` (`research_execution_plan.py:198-203`), so a background continuation
  permission cannot authorize plan creation; only a caller supplying explicit domain references
  may. This is the current behavior, not a permission grant.
- **Historical note:** the old `ADR-0085 P4` text ("foreground callers create plans") is
  **historical/superseded** by the Clean Break baseline (ADR-0088 + Clean Break ADRs 001–006) and
  is **not** cited here as current authority. Do not read the code's foreground-only guard as an
  already-accepted authorization for a new Product entry point.
- **What genuinely needs acceptance (current authority):** the current Accepted ADRs —
  ADR-0088/Clean Break 001–006, ADR-0097 (dedicated judgment root), ADR-0107 (judgment dispatch
  trigger) — define the judgment lifecycle/dispatch and the Clean Break boundaries; none of them
  authorizes a **new Product/Gateway (or MCP) entry that creates a research execution plan**. The
  business-permission contract governs approvals/actions, not plan creation. So the new entry is a
  **Product feature addition** requiring a maintainer product decision (and, if it changes an
  Accepted Product/business-permission boundary, a small ADR). The plan stays **unimplemented**.

## Implemented (ADR-0108)
- **Backend**: `POST /v1/research/tasks/{task_id}/execution-plan` (`services/backend/app/main.py`) ->
  `create_execution_plan` with owner/workspace from the trusted context.
- **Gateway/Product**: `POST /api/product/research/tasks/{task_id}/execution-plan`
  (`services/gateway/app/product_api.py`) deriving owner/workspace from the durable user identity
  (`_trusted_agent_headers`); documented in `docs/contracts/product-api.openapi.yaml`.
- **Reference binding/validation** (`_validate_create_references`): binds `research_task` exactly to
  the task and `conversation` exactly to the task's conversation (a same-owner sibling is refused),
  then resolves every other reference to a real owner/workspace/task-scoped row inside the create
  transaction; foreign, nonexistent and unverifiable references fail closed.
- **Idempotency**: an exact key+body replay returns the **current** plan projection and writes no
  second plan (even after the task is terminal); a different key with an existing plan is
  `IdempotencyConflict`; a new create on a terminal task with no plan is `InvalidTransition`.
- **Foreground-only at the HTTP entry**: the Backend route uses `_required_agent_context`, so a
  continuation-consumer identity (owner+actor+workspace only) is rejected (401) and creates no plan.
- **Tests** (isolated `byq_domain_test`): plan store/api/contract + grant-binding + continuation = 61
  passed; Gateway execution-plan projection = 5 passed (`python -m pytest`, the canonical Makefile
  invocation); architecture governance suite = 72 passed.
- **Not done**: not merged, deployed, default-promoted or Phase-advanced; no real-browser Product
  acceptance yet; child tool-hook coverage remains NOT_PROVEN.

## Boundary
- Implemented, but not merged/deployed/promoted; no Phase advance.
- The formal Gateway/Product -> task/plan -> consumer -> ACP chain is wired in code, but the
  end-to-end real-browser acceptance is **NOT_RUN**; `no_durable_progress`/`proposal=null` proves
  only bounded closure.
