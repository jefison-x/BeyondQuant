# Authoritative step-safety + budget binding + safe rescheduling (inventory + minimal design)

This slice is **design/evidence only**. It produces an inventory of the existing
BYQ components that bear on authoritative server-side step-safety metadata,
budget binding and safe rescheduling, and a minimal, *implementable* design for
the next implementation slice. It contains **no runtime code**, does **not** start
or claim a D15 superseding assessment, and does **not** complete the ADR-0084
business-recovery gate (which stays `IN_PROGRESS / BLOCKED_INTERNAL`).

Authority: ADR-0084 migration step 3/4, ADR-0081/0082/0083, ADR-0079,
ADR-0077, ADR-0066, ADR-0062, and the merged containment slice
(`docs/evidence/v090-session-containment/`).

> Rectification note (P1-A..P1-E): this revision replaces the earlier
> "new continuation reservation" semantics, the "3 attempts with one fixed event
> key" contradiction, the inaccurate advisory-lock/unique-constraint claim, the
> registry-only step lookup, and the `token_limit − charged_tokens` budget
> formula. Every corrected claim is tied to real committed code below.

## Code facts the design must respect (verified against the committed tree)

- `services/backend/app/research_continuation.py:107-109` — `_continuation_task`
  reads the `research_tasks` row with **`SELECT ... FOR UPDATE`**. Every reserve,
  claim and receipt transaction starts here, so the task row is the lock that
  serializes continuation-budget mutations.
- `services/backend/app/research_continuation.py:309-310` — a new reservation is
  rejected while **any** existing row is non-settled
  (`"previous continuation result is unconfirmed"`).
- `services/backend/app/research_continuation.py:563-567` —
  `claim_continuation_dispatch` sets the dispatched row's `status` to
  **`outcome_unknown`** *before* the process boundary is crossed.
- `services/backend/app/research_continuation.py:631-636` — settling requires
  `charged_tokens` and `settlement_sha256`; a settlement larger than the original
  reservation is rejected (`"settlement exceeds original reservation"`).
- `services/backend/app/research_continuation.py:186-193` —
  `_continuation_view` computes `reserved_tokens` (all non-settled rows),
  `charged_tokens` (settled rows), `available_tokens` and
  `unconfirmed_reservations`.
- `research_tasks.continuation_budget` is a **JSONB column on the task row**. It
  has **no per-`event_key` database unique constraint** and there is **no
  `pg_advisory_xact_lock` on the continuation path** (that advisory lock exists
  only for `research_receipt_watches` in
  `services/backend/app/research_receipts.py:86-87`). Its concurrency guarantee
  is the task-row `FOR UPDATE` plus in-transaction event-key scan/dedup.
- `services/backend/app/domain_call_admission.py:29-42` —
  `agent_domain_call_evidence` with **primary key
  `(owner_principal, workspace_id, session_id, sequence)`**, columns
  `root_run_id`, `generation`, `agent_run_id`, `task_id`, `action`,
  `idempotency_key`, `request_sha256`, `input_sha256`, `evidence_json`,
  `receipt_json`.
- `services/backend/app/domain_call_admission.py:50-59` —
  `agent_domain_call_claims` with **unique
  `(root_run_id, task_id, action, idempotency_key)`** and closed status
  `claimed|executing|succeeded|correctable_failure`.
- `services/backend/app/domain_call_admission.py:116-160` — `claim_domain_call`
  binds an exact proof by owner/workspace/session/trace/root/task/action/
  idempotency/request/input/generation/agent-run and refuses unknown outcomes
  (`prior_call_outcome_unknown`).
- `services/runtime-adapter/app/runtime.py:1855-1858` — the adapter journal
  records `domain-call-observed.v1` rows with a **monotonic `sequence`**;
  `runtime.py:1122-1133` reads them as a bounded page.
- `services/runtime-adapter/app/lifecycle_journal.py:552-559` — `observe_call`
  validates the closed evidence schema and enforces
  `sequence == len(calls) + 1` (no gaps).

## Inventory

Machine-readable: `inventory.v1.json`.

### Step-safety and the occurred-call set

| Component | Exists | Authoritative? | Missing |
|---|---|---|---|
| `agent_domain_call_evidence` (ADR-0066) | ordered, PK'd occurred-call rows bound to trace/root-run/generation/agent-run with `action`/`idempotency_key`/`request_sha256`/`input_sha256` | **yes** — the authoritative occurred-call set for domain actions (no execution without a proof row) | no recovery consumer closes it by sequence |
| `agent_domain_call_claims` | unique `(root_run_id,task_id,action,idempotency_key)`, closed status | **yes** — exact per-call receipt (`succeeded`/`correctable_failure`/unknown) | not wired into recovery classification |
| `domain_call_admission.ACTIONS` (ADR-0066) | closed action set + idempotency identity | the idempotency identity; **not** a safety class | no closed per-action `idempotent`/`result_verifiable` declaration |
| `services/backend/app/research_receipts.py` (ADR-0062) | exact idempotency-keyed receipt presence/conflict for research/experiment/artifact | yes, for those entity creations | no read path into recovery |
| `lifecycle_journal` / `reconcile_prompt` | durable prompt idempotency receipt | yes, at prompt level | no per-turn multi-tool classification |
| MCP tool description strings | display text only | **no** | not a machine authority |

**Missing:** a closed per-step safety registry **and** the rule that the step
actually being recovered is the sequence-ordered occurred-call set in
`agent_domain_call_evidence`; a registry lookup alone cannot tell which step ran.

### Budget binding

| Component | Exists | Authoritative? | Missing |
|---|---|---|---|
| `research_tasks.continuation_permission` + `continuation_budget` (ADR-0077) | immutable grant (`token_limit`, `max_turns`, `expires_at`, `grant_version`, revoke) + per-turn JSONB rows (`reservation_id`, `event_key`, `input_sha256`, `token_limit`, `status`, `run_id`, `charged_tokens`, `settlement_sha256`, `dispatch_attempts`) | **yes** — task-row `FOR UPDATE` serializes all mutations | no in-row recovery attempt allocation and no unknown-liability judgment |
| adapter `continuation_budget.read_guard`/`persist_settlement`/`recovered_settlement` | bounded guard-journal receipt with actual per-call charges | yes for the charged amount of a dispatched attempt | not consumed for recovery |
| adapter `reconcile_prompt` + `lifecycle_journal.receipt` | exact prompt receipt by `idempotency_key` + `content_sha256` | yes | not consumed for recovery |
| Gateway `_recovery_authority` | owner/workspace/auth from existing catalog + Backend session | yes for identity | `budget_available` hardcoded `None` |

**Missing:** binding a lost run to its exact original reservation and judging the
**unresolved liability** of its `outcome_unknown` attempt (whose
`charged_tokens` is `None`), instead of assuming `token_limit − charged_tokens`.

### Safe rescheduling

| Component | Exists | Authoritative? | Missing |
|---|---|---|---|
| `classify_recovery` + fence (`session_failure_containment.py`) | tri-state fail-closed decision, `RECOVERY_ATTEMPT_MAX=3`, generation/epoch/attempt fence | yes | no consumer |
| `containment.py` + `executor_identity.py` | fenced bounded loss evidence | yes | no recovery-attempt record |
| `claim_continuation_dispatch` / `record_continuation_receipt` | transport dispatch retry (`dispatch_attempts` ≤ 8) and settlement | yes | **transport retry is not a business recovery attempt** |
| Gateway read-only recovery endpoint | `submission: not_performed`, never submits | yes | no bounded exactly-once rearm |

## Minimal design

Machine-readable: `design.v1.json`.

### Contract mapping

- Keep `packages/contracts/session_failure_containment.py` closed and unchanged:
  `classify_recovery`, loss causes, terminal kinds, recovery statuses/reasons,
  the generation/epoch/attempt fence and `RECOVERY_ATTEMPT_MAX = 3`.
- Add a **closed, provider-independent step-safety registry** derived from the
  existing `domain_call_admission.ACTIONS`, declaring exactly
  `{idempotent, result_verifiable}` per action. Any action/step not in the
  registry is `unknown`.
- Reuse the existing per-call receipts (`agent_domain_call_claims`,
  `research_receipts`, prompt receipts) for reconciliation and the existing
  `continuation_budget` row for budget. Add **no** second store.

### Authoritative step-safety: bind by ordered call evidence (P1-D)

A recovery judgment MUST use the occurred-call set persisted for the exact lost
root run, not a registry lookup by itself:

1. Read `agent_domain_call_evidence` for the **same**
   `(owner_principal, workspace_id, session_id, trace_id, root_run_id,
   generation, agent_run_id)` `ORDER BY sequence`.
2. **Sequence closure:** the set must start at `1` and be strictly contiguous
   (PK uniqueness forbids duplicates; a gap, an out-of-range sequence, or an
   unreadable/conflicting row is not evidence).
3. For each observed call **in order**, bind the persisted
   `(action, task_id, idempotency_key, request_sha256, input_sha256)` and
   reconcile it against the exact per-call receipt
   (`agent_domain_call_claims` keyed by `(root_run_id, task_id, action,
   idempotency_key)`):
   - `succeeded` with matching `request_sha256` → that side effect is **settled**
     (never replayed);
   - `claimed`/`executing` → `prior_call_outcome_unknown` → `paused`/`blocked`;
   - `correctable_failure` with unchanged `input_sha256` → `blocked`
     (`unchanged_failed_input`); `repair_used` → `blocked`
     (`correction_budget_exhausted`);
   - `request_sha256` reuse mismatch → `blocked`;
   - action absent from the closed registry, or any receipt absent/unqueryable
     → `paused` (`non_idempotent_step` / `unknown_side_effect`).
4. **Zero evidence for a dispatched run → `paused`** (cannot prove the work is
   idempotent and result-verifiable). A sequence gap or any unknown/conflict/
   unqueryable item among multiple calls → `paused`/`blocked`.
5. `eligible` only when **all** occurred side effects are settled **and** every
   action in the work to replay is declared idempotent + result-verifiable in
   the closed registry.
6. FORBIDDEN inference sources: the prompt text, MCP display strings, client
   fields, or "the last call". An ordinary prompt-only turn with **no task
   reservation stays `paused`** regardless of registry contents.

A `reserved` row that was never accepted (no run started) has no occurred calls;
it is a re-dispatch of the original authorized instruction, governed by budget
and authority, and its eventual domain calls are re-admitted through the same
closed registry on the new run.

### Budget binding: rearm **within the original reservation row** (P1-A, P1-E)

The earlier "create a new continuation reservation" design is **withdrawn**: it
is impossible because `research_continuation.py:309-310` rejects a new
reservation while any old row is non-settled, and a lost dispatch leaves the
original row `outcome_unknown` (`563-567`). Recovery therefore re-arms the
**same** row (same `reservation_id`, same `event_key`, same `token_limit`) and
never resets or duplicates budget.

Identity and allocation (P1-B):

- The persisted location is the existing `research_tasks.continuation_budget`
  row `R`. The design adds a bounded in-row recovery sub-record
  `recovery_attempts: [{attempt: k, status, run_id, charged_tokens?}]` and a
  `recovery_attempt` counter on `R`.
- `RECOVERY_ATTEMPT_MAX = 3` **business recovery attempts**, distinct from
  `dispatch_attempts` (transport/dispatch retry, cap 8, unchanged).
- Atomic allocation: under `_continuation_task`'s `SELECT ... FOR UPDATE` on the
  `research_tasks` row, a caller reads `recovery_attempt = k-1` and increments it
  to `k`; the serialized second caller then sees `k` and cannot allocate the same
  ordinal. Concurrent calls for the **same ordinal** are therefore exactly-once.
- The deterministic audit identity of ordinal `k` is
  `recovery-v1:<sha256(event_key + interrupted_run_id + ":" + k)>`. This is a
  reconciliation/audit identity, **not** a uniqueness key — there is no
  per-`event_key` unique index (P1-C); uniqueness comes from the locked ordinal.
  If the cap is set to 1, all criteria and constants unify to one.

Concurrency mechanism (P1-C, real):

- `continuation_budget` is in-row JSONB on `research_tasks`. Safety is the
  task-row `SELECT ... FOR UPDATE` (`_continuation_task`) plus in-transaction
  scan/dedup. There is no per-`event_key` unique constraint and no advisory lock
  on this path. Database-level uniqueness is **not** required by this design; a
  future slice that wants it would add a schema/migration and could no longer
  claim "existing components as-is" (and would require the ADR review below).

Budget formula (P1-E): unknown cost is never `0` and is never refunded.

```text
# Permission P: token_limit, max_turns, expires_at, grant_version, revoked
committed   = Σ charged_tokens over rows with status == settled
unresolved  = Σ token_limit     over rows with status in {reserved, accepted, outcome_unknown}
permission_remaining = P.token_limit - committed - unresolved        # R is included in unresolved

# R = the original reservation row for the lost event
known_charge = 0                              if R.status == reserved   (no dispatch accepted)
             = c                              if the adapter guard receipt for the exact
                                              reservation_id reconciles to R and the run
             = None                           otherwise                 (unknown liability)

reservation_remaining = None if known_charge is None else R.token_limit - known_charge
available             = None if reservation_remaining is None
                              else min(permission_remaining, reservation_remaining)

budget_available = blocked  if revoked/expired/turns_remaining<=0/available<single_call_floor
                 = None     if known_charge is None or any input unreadable   -> paused
                 = True     otherwise (bounded rearm), subject to recovery_attempt < 3
```

Budget state table:

| `R.status` | exact adapter guard receipt | consumed | `reservation_remaining` | `budget_available` |
|---|---|---|---|---|
| `reserved` | absent / never dispatched | 0 | `R.token_limit` | `min(P_remaining, R.token_limit)` |
| `rejected` | absent | 0 | `R.token_limit` | `min(P_remaining, R.token_limit)` |
| `accepted` / `outcome_unknown` | present, identity matches `R` and run | `c` (known) | `R.token_limit − c` | `min(P_remaining, R.token_limit−c)` if ≥ floor, else `blocked` |
| `accepted` / `outcome_unknown` | absent / unreadable / identity mismatch | **unknown** | `None` | `None` → `paused` |
| `settled` | — | `c` | terminal | no rearm (terminal) |
| any | — | — | — | `blocked` if `P` revoked/expired/turn cap/ordinal cap |

### Safe-rescheduling semantics

- **Receipt-first:** query the exact prompt receipt and the adapter guard receipt
  for `R.reservation_id` before any decision. A success receipt → `settled` and
  never replay; a conflict → `blocked`; an unresolved charge → `paused`.
- **Bounded:** `recovery_attempt < RECOVERY_ATTEMPT_MAX` and
  `available ≥ single_call_floor`; the sum of attempt charges never exceeds
  `R.token_limit`; permission `max_turns`/`expires_at`/revocation still apply.
- **Exactly-once per ordinal:** the locked `recovery_attempt` increment makes a
  concurrent duplicate a no-op; the deterministic `recovery-v1:` key is used for
  audit/reconciliation only.
- **Auditable and fenced:** loss evidence stays in the fenced adapter containment
  ledger; attempt charges/run ids stay in `R`; stale epoch/generation/attempt and
  terminal reopen fail closed (`FencedWrite`). No second store and no `/tmp`
  authority.

### Failure semantics (unknown/unavailable → fail closed)

- Tri-state authority `None` (owner, workspace, authorization, budget) →
  `paused`, never allowed.
- Missing/ambiguous step-safety or call evidence → `paused`; any conflict → `blocked`.
- Unknown cost (`outcome_unknown` with no reconciled guard receipt) → `paused`,
  never refunded and never settled as `0`.
- Zero evidence for a dispatched run, sequence gaps, or unreadable/corrupt
  evidence → `paused`/`blocked`.
- `failed`/`cancelled`/`discarded`/`closed` keep ordinary semantics;
  `interrupted` is projected only from the fenced containment record matching the
  same session/trace and exact run.

### Next implementation-slice acceptance criteria

1. Closed step-safety registry derived from `domain_call_admission.ACTIONS`;
   unlisted actions are `unknown`.
2. Recovery reads the exact owned call-evidence rows by sequence, enforces
   contiguity, and reconciles each call against its exact per-call receipt.
3. Original-row rearm only: no new `continuation_budget` row, no budget reset;
   `outcome_unknown` liability is resolved from the adapter guard receipt or the
   judgement stays `paused`.
4. `recovery_attempt` ordinal allocated atomically under the task-row
   `FOR UPDATE`, bounded by `RECOVERY_ATTEMPT_MAX=3`; concurrent same-ordinal
   calls are exactly-once; transport `dispatch_attempts` is separate.
5. Receipt-first: success receipt → `settled` (no prompt); conflict → `blocked`;
   non-idempotent/unknown/zero-evidence → `paused`.
6. Fenced: stale epoch/generation/attempt and terminal reopen fail closed.
7. Fail-able observer plus negative controls (including unknown-liability,
   previous-unconfirmed rejection, zero/gap call evidence, concurrent ordinal)
   that a result-trusting gate would misreport.
8. No runtime code change in this design slice; no production selector change,
   deploy, release/tag, Phase 100 resume or D15 superseding assessment.

### ADR decision: no new ADR (proven by the mapping)

The design only extends already-authorized BYQ components:

- the existing `research_tasks.continuation_budget` row (same authority, same
  row, in-row bounded recovery sub-record) — not an independent recovery store;
- the existing closed contract surface (`session_failure_containment` plus a
  closed step-safety registry module) — not a new persistence authority;
- the existing per-call receipts and ordered call evidence — not a new trust
  subject;
- the existing Gateway→Backend `/internal/task-continuation/...` seam (an added
  operation on it) and the existing adapter dispatch path — not a new Plane
  boundary or cross-Plane interface;
- the ADR-0084 gate classification is unchanged.

**Therefore no new ADR is required.** A **Proposed** ADR (never Accepted in this
slice) is required before implementation if a later slice introduces any of: an
independent recovery-attempt store, a new public/internal cross-Plane authority
interface, a database schema/migration (e.g. a per-`event_key` unique index), a
new trust subject, or a change to the ADR-0084 gate classification.

## Boundary facts (unchanged)

- B1 `subagent-child-crash` and B2 `subagent-byq-adapter-restart` remain
  `BLOCKED_EXTERNAL`.
- Historical D15-G remains `NO_GO`; historical verdicts are not rewritten.
- `R3_RESUME = NO`; 0.9 is not closed.
- Full business-recovery gate remains `IN_PROGRESS / BLOCKED_INTERNAL`.
- No production selector switch, deploy, release/tag, Phase 100 resume or
  `#338` change. Native child resume is not implemented; unknown side effects
  pause. This PR creates no D15 superseding assessment.
