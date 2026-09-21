# Authoritative step-safety + budget binding + safe rescheduling (inventory + minimal design)

This slice is **design/evidence only**. It produces an inventory of the existing
BYQ components that bear on authoritative server-side step-safety metadata,
budget binding and safe rescheduling, and a minimal design for the next
implementation slice. It contains **no runtime code**, does **not** start or
claim a D15 superseding assessment, and does **not** complete the ADR-0084
business-recovery gate (which stays `IN_PROGRESS / BLOCKED_INTERNAL`).

Authority: ADR-0084 migration step 3/4, ADR-0081/0082/0083, ADR-0079,
ADR-0077, ADR-0066, ADR-0062, and the merged containment slice
(`docs/evidence/v090-session-containment/`).

## Inventory

Machine-readable: `inventory.v1.json`.

### Step-safety metadata (server-side authority vs client/prompt claim)

| Component | Exists | Authoritative? | Missing |
|---|---|---|---|
| `packages/contracts/domain_call_admission.py` (ADR-0066) | closed `ACTIONS` set, per-call `idempotency_key` / `request_sha256` / `input_sha256` private evidence | the idempotency **identity**, not a permission; it declares no per-step safety class | no closed `idempotent` / `result_verifiable` declaration per action |
| `services/backend/app/research_receipts.py` (ADR-0062) | `research_receipt_watches` keyed by `(owner, workspace, entity_type, parent_task_id, idempotency_key)`, request-hash match, `awaiting_receipt`/`confirmed`/`conflict`/`needs_attention` | yes, exact receipt presence/absence/conflict for research/task/experiment/artifact creation | no read surface that the recovery classifier already consumes |
| `services/runtime-adapter/app/lifecycle_journal.py` + `runtime.py` | durable prompt idempotency receipt (`idempotency_key` + `content_sha256`), `reconcile_prompt` | yes, for a prompt attempt that entered the adapter | no step-level classification for a whole multi-tool turn |
| `packages/contracts/agent_run_lifecycle.py` | run lifecycle receipt projection | yes, for run terminal identity | does not classify side effects |
| `services/mcp/src/server.ts` tool descriptions (`Read-only`, `idempotently`) | display strings only | **no** — prompt-facing text is not a closed machine authority | no programmatic side-effect class |
| `packages/contracts/session_failure_containment.py::classify_recovery` | tri-state fail-closed classifier | yes, as the single decision surface | inputs `step_declared_idempotent` / `step_result_verifiable` are always `False` today because no authoritative registry exists |

**Missing authoritative piece:** there is no server-side, provider-independent,
closed registry that declares, per step/action, whether it is idempotent and
result-verifiable. Consequently `services/gateway/app/session_containment.py`
calls `classify_recovery` with `step_declared_idempotent=False`,
`step_result_verifiable=False`, `success_receipt_present=False`,
`receipt_queryable=False`, so `eligible` is unreachable by construction and no
automatic reschedule path exists.

### Budget binding

| Component | Exists | Authoritative? | Missing |
|---|---|---|---|
| `services/backend/app/research_continuation.py` `research_tasks.continuation_permission` + `continuation_budget` | immutable grant (`token_limit`, `max_turns`, `expires_at`, `grant_version`, `revoke`), per-turn rows (`reservation_id`, `event_key`, `input_sha256`, `token_limit`, `status`, `run_id`, `charged_tokens`, `settlement_sha256`) | **yes** — the task-bound budget authority; per-`event_key` at-most-once reservation | read/binding path for a *lost* run's original reservation into recovery |
| `services/runtime-adapter/app/continuation_budget.py` | closed reservation carrier, guard-journal receipt, `CONTINUATION_*` ceilings | bounded mirror of the Backend reservation | not an authority |
| `plugins/dsh-byq/runtime/byq-continuation-budget.js` | `createBudgetGate` per-call charge, fail-closed | bounded runtime guard | not an authority |
| `services/gateway/app/main.py::_recovery_authority` | verifies owner/workspace/auth from existing catalog + Backend session | yes for identity | `budget_available` is hardcoded `None` for an arbitrary unanswered turn, so recovery pauses |

**Missing authoritative piece:** no binding from an interrupted run to its exact
authoritative reservation/event identity. For an arbitrary chat turn there is
correctly **no** budget authority, so `budget_available` stays `None` → paused.

### Safe rescheduling

| Component | Exists | Authoritative? | Missing |
|---|---|---|---|
| `packages/contracts/session_failure_containment.py` | `RecoveryDecision`, `auto_retry`, `RECOVERY_ATTEMPT_MAX = 3`, `assert_fenced` / `assert_generation_fenced` / `assert_terminal_settlement` | yes, closed contract and fence | no executor consumes an `eligible` decision |
| `services/runtime-adapter/app/containment.py` | bounded fenced containment ledger, duplicate/reopen rejection | yes, loss evidence | no recovery-attempt record (deliberately no second store) |
| `services/runtime-adapter/app/executor_identity.py` / `generation_ledger.py` | stable executor identity, monotonic epoch, bounded generation history | yes | — |
| `services/gateway/app/session_containment.py` / `main.py` | read-only classification, `submission: not_performed`, `submitted: False` | yes, no submit path | no bounded exactly-one reschedule |
| `services/backend/app/research_continuation.py` reservation dedup | per-`event_key` unique row inside a transaction with `pg_advisory_xact_lock` / `FOR UPDATE` | yes, exactly-one under concurrency | no deterministic recovery event-key namespace |

**Missing authoritative piece:** there is no bounded, exactly-one reschedule
operation keyed off the original authoritative reservation, and no receipt-first
reconciliation wired into the decision.

## Minimal design

Machine-readable: `design.v1.json`.

### Contract mapping

- Keep `session_failure_containment.py` closed: `classify_recovery`, six loss
  causes, six terminal kinds, four recovery statuses, twelve reasons, the
  generation/epoch/attempt fence and `RECOVERY_ATTEMPT_MAX`.
- Add a **closed, provider-independent step-safety registry** co-located with the
  existing domain action contract (`domain_call_admission.ACTIONS`) as an
  ordinary contract extension. Each entry declares exactly
  `{idempotent: bool, result_verifiable: bool}`. Any step/action not in the
  registry is `unknown`.
- Reuse (do not replace) `research_receipts` for exact receipt reconciliation,
  `research_continuation.continuation_budget` for budget, `lifecycle_journal`
  prompt receipts for adapter-level reconciliation, `executor_identity` /
  `containment` for fencing and loss evidence, and `RecoveryDecision` for the
  public projection.

### Authoritative source for step idempotency / result-verifiability

The BYQ domain contract, never the client and never the model prompt. A step is
safe only when **all** hold:

1. it is a member of the closed BYQ domain action set and carries a persisted
   `idempotency_key` plus `request_sha256`/`input_sha256` (ADR-0066);
2. an exact receipt reconciliation surface exists (`research_receipt_watches`,
   the domain idempotency lookup, or adapter `reconcile_prompt`) so the result
   can be queried and matched, not assumed;
3. it is not a write/order/publish/paid/irreversible action outside the closed
   registry.

If any condition cannot be answered, the server reports `unknown`; it is never
defaulted to safe.

### How budget is bound authoritatively

- A lost run that originated from a **task-bound continuation event** is bound to
  the exact persisted row in `research_tasks.continuation_budget` by
  `(reservation_id, event_key, input_sha256)`. `budget_available` is derived from
  that row: `remaining = token_limit − charged_tokens`, `max_turns`,
  `expires_at`, `continuation_blocked_reason`, `grant_version`/revocation.
  Exhausted/expired/revoked → `blocked`; a missing or ambiguous binding → `None`
  → `paused`.
- An **arbitrary chat turn** has no authoritative reservation; `budget_available`
  stays `None` → `paused` (unchanged).
- The adapter reservation carrier and the DSH guard journal remain bounded
  mirrors; they never become an authority and no budget can be reset by a
  recovery.

### Safe-rescheduling semantics

- **Bounded:** at most `RECOVERY_ATTEMPT_MAX` (3) reschedules per lost run, in
  addition to the existing reservation `max_turns`, `expires_at`,
  `turn_timeout_seconds` and DSH guard call/token bounds. A reschedule must fit
  the remaining authoritative reservation; otherwise `budget_exhausted`.
- **Idempotent and exactly-one under concurrency:** a reschedule is a new
  continuation reservation under a deterministic recovery event key
  `recovery-v1:<sha256(original_event_key + interrupted_run_id)>`. The existing
  Backend ledger enforces one row per `event_key` inside its transaction (unique
  constraint plus `pg_advisory_xact_lock` / `SELECT ... FOR UPDATE`), so a
  concurrent duplicate creates zero extra reservations. Domain writes retain
  their original idempotency keys; `record_continuation_receipt` /
  `_matched_receipt` reconcile `request_hash` instead of replaying.
- **Receipt-first:** before any reschedule, query the exact receipt. A success
  receipt → `settled` and never replay; a hash/identity conflict → `blocked`;
  absent or unqueryable receipt with a non-idempotent/unknown step → `paused`.
- **Auditable:** the loss is already recorded in the fenced adapter containment
  ledger; the reschedule is recorded in the Backend continuation ledger with
  `run_id`, `charged_tokens` and `settlement_sha256` lineage; the Gateway
  projection exposes the decision. No new store, no `/tmp` authority.
- **Fenced:** stale executor epoch, stale/duplicate generation, late settlement
  and terminal reopen fail closed (`FencedWrite`), consistent with the existing
  `containment.py` / `executor_identity` behavior.

### Failure semantics (unknown/unavailable → fail closed)

- Tri-state authority value `None` (owner, workspace, authorization, budget) →
  `paused` (`authority_unavailable`), never allowed.
- Missing or ambiguous step-safety metadata → `paused`
  (`step_safety_unavailable`) or `non_idempotent_step`.
- Unknown side effect or unqueryable/absent receipt → `paused`.
- Ordinary `session.failed` stays `failed`; `cancelled` stays `cancelled`;
  `discarded`/`closed` keep their semantics; `interrupted` is projected only
  from the fenced containment record matching the same session/trace and exact
  run.
- A containment/receipt read that is unreadable or corrupt is treated as
  unavailable → `paused`, never as proof of absence or success.

### Next implementation-slice acceptance criteria

1. A closed step-safety registry derived from the existing domain action
   contract plus receipt surfaces; every unlisted step is `unknown`.
2. `classify_recovery` invoked with real authoritative values (identity from the
   existing Backend session/catalog; budget from `continuation_budget`; success
   receipt from existing reconciliation; step safety from the registry), with
   byte-for-byte fail-closed fallback to `paused` on any read failure.
3. Exactly-one bounded reschedule under a deterministic `recovery-v1:` event
   key, accepted only within the original authoritative reservation and at most
   `RECOVERY_ATTEMPT_MAX`; concurrent duplicates create zero extra reservations;
   no second store.
4. Receipt-first: success receipt → `settled` (no prompt); conflict → `blocked`;
   non-idempotent/unknown → `paused`.
5. Fenced: stale epoch/generation/attempt and terminal reopen fail closed.
6. Fail-able observer plus negative controls that a result-trusting gate would
   misreport, with machine-readable evidence.
7. No new persistence authority, trust subject, cross-Plane call, production
   selector change, deploy, release/tag, Phase 100 resume or D15 superseding
   assessment.

### ADR decision

**No new ADR is required. Existing components suffice.** The design is an
ordinary closed-contract extension over already-authorized BYQ authorities:
(a) the step-safety registry extends the existing `domain_call_admission`
contract; (b) budget binding reuses the existing Backend
`continuation_budget` ledger; (c) receipt reconciliation reuses existing
`research_receipts` / prompt-receipt surfaces; (d) the Gateway→Backend
`_catalog_request` internal seam already exists and is already used for task
continuation and receipt reconciliation; (e) no new trust subject, persistence
authority, production topology or external write permission is introduced.

A **Proposed** ADR must precede implementation if a later slice introduces any
of: a dedicated recovery-attempt persistence store, a new trust subject, a new
cross-Plane surface, or a change to the ADR-0084 gate classification. None is
present in this design.

## Boundary facts (unchanged)

- B1 `subagent-child-crash` and B2 `subagent-byq-adapter-restart` remain
  `BLOCKED_EXTERNAL`.
- Historical D15-G remains `NO_GO`; historical verdicts are not rewritten.
- `R3_RESUME = NO`; 0.9 is not closed.
- Full business-recovery gate remains `IN_PROGRESS / BLOCKED_INTERNAL`.
- No production selector switch, deploy, release/tag, Phase 100 resume or
  `#338` change. Native child resume is not implemented; unknown side effects
  pause. This PR creates no D15 superseding assessment.
