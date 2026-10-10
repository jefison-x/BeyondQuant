# ADR-0107 — Dedicated ACP judgment turn: dispatch trigger / trusted consumer seam

- Status: **Accepted** (2026-10-08). The maintainer accepted the recommended judgment-only
  background consumer / unknown-safe dispatch scheme, recorded verbatim as: **“同意，除了这个还有其他的需求吗？”**
  Implementation, qualification, PR and release gates remain separate.
- Scope: the missing **scheduling caller** that decides *when* a task's `judgment_turn` plan
  step runs and invokes the Runtime Adapter judgment route. It does not change ADR-0097
  (dedicated judgment ACP root) or ADR-0098 (pre-result terminal settlement), which define the
  root lifecycle/settlement but not the dispatch trigger.

## Context (audited, current code)

- The judgment lifecycle is complete **in-repo**:
  - Adapter SDK route `POST /internal/runtime/research-judgment/{task}/run`
    (`services/runtime-adapter/app/research_judgment_api.py:56`) -> `run_stage_judgment`
    (`research_judgment_entry.py`) -> `run_bounded_research_judgment` ->
    `admit_research_judgment_turn` (`services/runtime-adapter/app/research_judgment.py:128`) ->
    Backend `POST /internal/research-judgment/{task}/admit` -> `admit_research_stage_call`
    (`services/backend/app/main.py:853`).
  - Adapter ACP route `.../acp-root/run` (`research_judgment_api.py:137`) -> `begin_root_once`
    -> Backend `POST .../acp-root/begin` -> `begin_acp_judgment_root`
    (`services/backend/app/research_judgment.py:363`).
  - So `/admit` **does** have an in-repo caller (the SDK bounded lifecycle, via
    `research_judgment.py:151` -> `:117` -> POST `/admit` at `:128`); the SDK bounded entry must
    not be described as caller-less.
- **What is missing:** no in-repo component decides *when* to call either judgment route.
  `ResearchPlanContinuationMixin.plan_continuation_dispatch`
  (`services/backend/app/research_plan_continuation.py:158`) is READ-ONLY and returns the next
  step, including `{"kind": "judgment_turn", "model_call_limit", "allowed_tools",
  "bounded_projection_only": true}`; it has **no in-repo non-test caller** (only tests call it).
- **There is NO unified research Job/worker scheduler in the repo.** The workers are
  **per-domain** and their loops are **not uniform**: `workers/backtest/worker.py:45-52` uses
  `requeue_stale(...)` -> `next_queued_id()` -> `run_once(job_id)`; `workers/signal/worker.py`
  uses `promote_waiting_signal_jobs` + `coordinator.run_next()`; `workers/factor/worker.py`
  uses `FactorJobStore.claim_next(worker_id)`; `workers/ml/worker.py` uses
  `reconcile_receipt_watches` + coordinators; `workers/optimization/worker.py` uses
  `worker.run_once()`; `workers/data/worker.py` is cycle-based. The backtest Job pattern is a
  durable row with an atomic `claim`/lease/attempts (`services/backend/app/backtest.py:1821-1906`,
  a fixed `BACKTEST_CLAIM_LEASE_SECONDS` window measured from `updated_at`; no heartbeat-renewal
  method) plus a `next_queued_id` selector — it is **backtest-specific**, not a shared scheduler.
- **Unknown-safety contrast (critical):** `BacktestJobStore.requeue_stale`
  (`services/backend/app/backtest.py:1974`) resets stale **running** Jobs back to `queued` so the
  worker re-executes them. That auto-re-execution semantics is correct for deterministic,
  idempotent backtest Jobs but **MUST NOT** be inherited by the judgment consumer: a model
  judgment that may have been dispatched and whose outcome is unknown must never be auto
  re-executed.

## Decision (proposed)

Add **one** judgment consumer that reuses the existing per-domain Job **durable-admission/claim
pattern** (claim/lease/attempts/heartbeat + a `next_queued_id` selector), for this business
only. Do not claim or introduce a general scheduler.

**Options compared**
- **Option A — a per-domain judgment worker reusing the Job claim pattern (recommended).**
  A `workers/judgment`-style consumer (or a bounded Backend consumer with the same claim
  pattern) selects a task at a `judgment_turn` stage, admits exactly one durable stage call
  (existing attempt binding), invokes the Adapter judgment route, and reconciles the result. It
  reuses the existing claim/lease/attempt machinery but with **unknown-safe** recovery (below).
- **Option B — synchronous Product explicit action.** A user command calls the Adapter judgment
  route directly. Rejected as the primary trigger: it couples a long bounded model turn to a
  browser request; the human gate is already provided by the existing `approval_wait` stages /
  `agent_approvals`.

**Recommendation: Option A**, scoped to a judgment-only consumer, with unknown-safe recovery.

## Minimal touchpoints (Option A)

- **Trigger/selection:** a judgment consumer reads `plan_continuation_dispatch(task_id)` for
  tasks whose current plan stage is a `judgment_turn`; no new public route and no model input.
- **Durable admission / idempotency:** reuse `admit_research_stage_call` /
  `begin_acp_judgment_root`; one durable call per `<plan_version>:<stage>:<iteration>` (the
  attempt binding). A retry of the *same* attempt reuses the same admission; it never consumes a
  second model-call slot.
- **Claim/lease:** reuse the existing claim/lease/attempt/heartbeat pattern so two consumers
  never run the same stage concurrently.
- **Unknown-safe recovery (differs from `requeue_stale`):**
  - A judgment that may have dispatched must never be auto-re-executed. Per ADR-0098, recovery
    requires an **affirmative durable journal** state (the persisted phase / settlement / root
    receipts); the **absence** of a local marker does **not** prove non-dispatch, and an unknown
    outcome is never resolved by a new boot or by a requeue.
  - **Affirmative no-dispatch** (a durable journal state that proves no prompt was dispatched and
    no provider attempt started): the consumer may **reconcile** the existing admission; it does
    not create a new admission.
  - **Post-dispatch or unknown** (the durable `prompt_may_have_dispatched` marker, or any
    uncertain cleanup): recovery is **read-only reconcile** of the persisted settlement/root
    receipts; no re-execution, no auto-requeue, outcome stays `needs_attention`.
  - Per ADR-0098, all three settlement kinds permanently consume the admitted slot; the same
    attempt cannot be re-admitted or automatically replayed. The consumer must not create a new
    admission for the same `<plan_version>:<stage>:<iteration>`.
- **No second harness:** the consumer is a Backend-domain consumer calling the existing Adapter
  judgment route; no second session store, no generic agent loop, no DSH fork.
- **Schema / migration (precise):**
  - The existing tables already carry the needed durable state: `research_execution_plans`
    (current stage/version/iteration), `research_judgment_stage_calls` (per-attempt admission,
    unique by `(task_id, call_identity)`), `research_judgment_acp_roots` (root/native/AgentRun
    binding), and `agent_runtime_turns` (terminal ACK). The judgment consumer needs no new
    business table.
  - If a consumer claim/lease is required (to bound concurrency), add **only additive** columns
    to `research_judgment_stage_calls` (e.g. `claim_owner`, `claim_lease_until`, `claim_attempt`)
    or a dedicated additive `research_judgment_consumer_claims` table keyed by
    `(task_id, call_identity)`. **No destructive migration, no change to existing columns.**
    This ADR does not choose the exact form until accepted; either is additive and reversible.
- **Plan CAS (single advance, no duplicate write):** the plan is advanced by the **existing
  result transaction** (`record_acp_judgment_root_result` / the SDK result commit), not by the
  consumer. The consumer must only **read** the exact stage and confirm the exact Backend
  terminal ACK; it must not perform a second plan CAS write. If a post-result bookkeeping step
  is ever needed, it must be idempotent and keyed on the already-committed result identity, not
  a new plan transition.

## Boundary

- This ADR is **Accepted** (2026-10-08). Implementation is bounded to the minimal judgment-only
  consumer described here: no second harness, no generic scheduler, no unknown replay, and the
  existing result transaction remains the only plan advance.
- Implement contracts/tests first, one writer, then Tester -> independent Reviewer -> Root, with
  real acceptance bound to the exact candidate image; unknown outcomes preserved and never
  auto-replayed.
- ADR-0097/0098 remain the authority for the root lifecycle/settlement and are not amended here.

## Implementation status (2026-10-08, isolated worktree; not promoted)

Minimal judgment-only consumer wiring implemented (contracts/tests first, single writer):

- **Contract:** `validate_judgment_stage_claim_request` +
  `JUDGMENT_STAGE_CLAIM_SCHEMA_VERSION` (`packages/contracts/research_judgment.py`).
- **Schema (additive, reversible):** new table `research_judgment_consumer_claims`
  keyed by `(task_id, call_identity)` with `claim_owner`/`claim_lease_until`/`claim_attempt`/
  `claimed_at`/`updated_at` + `dispatch_intent_at`/`dispatch_intent_owner`. No existing
  column/row is changed. **Rollback:** disable the new consumer and roll back to the previous
  image/config; **preserve** the additive `research_judgment_consumer_claims` table, its
  `dispatch_intent_*` columns and all unknown evidence — do not delete business records.
  Dropping the table is a separate destructive-cleanup action requiring its own explicit
  authorization (not granted).
- **Backend:** `claim_judgment_stage_call` (atomic single-owner lease, keyed before the
  begin on the current plan attempt) and `record_judgment_dispatch_intent` (persists the
  intent before the HTTP run; only the live lease owner is accepted) and
  `list_judgment_turn_tasks` (READ-ONLY selection). Routes: `POST
  /internal/research-judgment/{task}/stage-claim`, `POST .../stage-dispatch-intent`, `GET
  /internal/research-judgment/stages`.
- **Unknown-safety (Root review):** ANY existing `research_judgment_acp_roots` row
  (`root_created` OR `agent_bound`) is **not** affirmative no-dispatch evidence — the begin
  response may have been lost and a runner may have started. The claim then returns
  `{"claimed": false, "reconcile_only": true, "reason": "root_exists"}` and the consumer only
  reconciles, never re-runs. Only a durable journal + cleanup proof could assert no-dispatch.
- **Worker:** `workers/judgment/worker.py` selects, claims, persists the dispatch-intent, then
  calls the Adapter `/acp-root/run`. It never writes the plan (the Backend result transaction
  is the only plan advance) and never auto-replays. BYQ keeps only attribution/authorization/
  idempotency/unknown-reconciliation/exact ACK; generic Agent cancel/context/recovery and
  container/process management stay with DSH/container management.
- **Tests:** `test_judgment_consumer.py` (3) + `test_research_judgment_acp_root.py` claim/
  intent/selection cases (root_created reconcile-only, lease expiry, dispatch-intent owner
  check). Full affected set: 63 passed (test DB asserted strictly `byq_domain_test`).
