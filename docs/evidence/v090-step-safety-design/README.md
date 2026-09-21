# Authoritative step-safety + budget binding + safe rescheduling (inventory + minimal design)

This slice is **design/evidence only**. It inventories the existing BYQ components
for authoritative server-side step-safety metadata, budget binding and safe
rescheduling, and gives a minimal, *implementable* design for the next
implementation slice. It contains **no runtime code**, does **not** start or claim
a D15 superseding assessment, and does **not** complete the ADR-0084
business-recovery gate (which stays `IN_PROGRESS / BLOCKED_INTERNAL`).

Authority: ADR-0084 migration step 3/4, ADR-0081/0082/0083, ADR-0079, ADR-0077,
ADR-0066, ADR-0062, and the merged containment slice
(`docs/evidence/v090-session-containment/`).

> Rectification notes:
> - P1-A..P1-E: original-row rearm; attempt ordinals; real task-row `FOR UPDATE`
>   concurrency; ordered call evidence; unknown liability.
> - P1-F..P1-K: Adapter identity separation (prompt-receipt dedup); per-attempt
>   receipts vs the immutable single settlement slot; trigger-key dedup before
>   ordinal allocation; session-global evidence cursor closure; corrected
>   no-double-deduction budget formula; recovery-mode admission envelope.
> - P1-L..P1-N: the closed `recovery_attempt` carrier fields + Adapter
>   recompute/verify/fence; a self-consistent tri-state budget decision table;
>   stable-snapshot tail closure (`more=false` AND `idle=true` + item-by-item
>   reconciliation) and the `may_produce_new_key=true` always-ineligible boundary.

## Code facts the design must respect (verified against the committed tree)

Reservation / budget:

- `services/backend/app/research_continuation.py:107-109` — `_continuation_task`
  reads `research_tasks` with **`SELECT ... FOR UPDATE`**; every reserve/claim/
  receipt transaction starts here.
- `services/backend/app/research_continuation.py:309-310` — a new reservation is
  rejected while **any** row is non-settled (`"previous continuation result is
  unconfirmed"`).
- `services/backend/app/research_continuation.py:563-567` —
  `claim_continuation_dispatch` sets the dispatched row to **`outcome_unknown`**
  before the process boundary.
- `research_tasks.continuation_budget` is in-row JSONB: **no per-`event_key`
  unique constraint** and **no `pg_advisory_xact_lock`** on this path (that lock
  is only in `research_receipts.py:86-87`).

Adapter admission / receipts:

- `services/runtime-adapter/app/runtime.py:780-789` — `submit_prompt` returns the
  **old** `run_id` when a durable accepted prompt receipt already exists for the
  same `idempotency_key` (`if durable["state"] == "accepted": return
  durable["run_id"]`).
- `services/runtime-adapter/app/runtime.py:806-809` — with a
  `continuation_budget`, the prompt key is forced to the reservation:
  `if idempotency_key != budget['reservation_id']: raise ... 'continuation
  requires its original reservation key'`. Re-arming with the same
  `reservation_id` therefore only returns the lost old run.
- `services/runtime-adapter/app/continuation_budget.py:105-137` —
  `persist_settlement` writes `.../byq-continuation-receipts/<session>/<reservation_id>.json`;
  an existing file with different content raises
  `'original continuation settlement cannot change'` — **one immutable
  settlement slot per `reservation_id`**.
- `services/runtime-adapter/app/lifecycle_journal.py:533-539,603-613` — prompt
  receipts live in `state["prompts"][key] = {root_run_id, content_sha256}`; a key
  cannot be replaced (`'prompt receipt cannot be replaced'`), and
  `receipt()`/`lookup()` resolve a key to its one `root_run_id`.

Call evidence:

- `services/runtime-adapter/app/lifecycle_journal.py:551-559` — `observe_call`
  requires `evidence["sequence"] == len(self.state["calls"]) + 1`, where
  `state["calls"]` accumulates **across roots in the session**. The adapter
  sequence is therefore **session-global, not per-root**.
- `services/backend/app/domain_call_admission.py:29-42` —
  `agent_domain_call_evidence` **PRIMARY KEY
  `(owner_principal, workspace_id, session_id, sequence)`** — session-global.
- `services/backend/app/domain_call_admission.py:50-59` —
  `agent_domain_call_claims` **UNIQUE
  `(root_run_id, task_id, action, idempotency_key)`**, closed status
  `claimed|executing|succeeded|correctable_failure`.
- `services/runtime-adapter/app/runtime.py:1122-1133` — `domain_call_evidence`
  reads a **bounded page** with `more`, so a complete view needs pagination.

## Inventory

Machine-readable: `inventory.v1.json`.

### Step-safety and the occurred-call set

| Component | Exists | Authoritative? | Missing |
|---|---|---|---|
| `agent_domain_call_evidence` (ADR-0066) | session-global ordered rows, PK `(owner,workspace,session,sequence)`, bound to trace/root-run/generation/agent-run | **yes** — authoritative occurred-call set | no recovery consumer closes it (session-global) |
| `agent_domain_call_claims` | unique `(root_run_id,task_id,action,idempotency_key)`, closed status | **yes** — exact per-call receipt | not wired into recovery classification |
| `domain_call_admission.ACTIONS` | closed action set + idempotency identity | idempotency identity only | no closed per-action safety declaration and no recovery-mode envelope |
| `research_receipts` | exact idempotency-keyed receipt | yes for entity creations | no read path into recovery |
| MCP display strings | display text only | **no** | not authority |

### Budget binding

| Component | Exists | Authoritative? | Missing |
|---|---|---|---|
| `research_tasks.continuation_permission` + `continuation_budget` | grant + in-row JSONB rows; task-row `FOR UPDATE` | **yes** | no in-row trigger-keyed recovery allocation / aggregate |
| adapter `continuation_budget.read_guard`/`persist_settlement` | guard-journal charge; settlement slot | yes for a dispatched attempt's charge | single immutable slot per `reservation_id` (P1-G) |
| adapter `submit_prompt` + `reconcile_prompt` | prompt receipt by `idempotency_key` | yes | key is forced to `reservation_id`; old-run dedup (P1-F) |
| Gateway `_recovery_authority` | owner/workspace/auth | yes for identity | `budget_available` hardcoded `None` |

### Safe rescheduling

| Component | Exists | Authoritative? | Missing |
|---|---|---|---|
| `classify_recovery` + fence | tri-state fail-closed decision, `RECOVERY_ATTEMPT_MAX=3` | yes | no consumer |
| `containment.py` + `executor_identity.py` | fenced loss identity | yes | no trigger key |
| `claim_continuation_dispatch` | transport retry (`dispatch_attempts` ≤ 8) | yes | transport retry is not a business recovery attempt |
| Gateway read-only recovery endpoint | never submits | yes | no bounded exactly-once rearm |

**Missing authoritative pieces:** (1) a closed per-step safety registry plus a
recovery-mode admission envelope; (2) separation of budget-authority identity
from per-submission recovery identity; (3) per-attempt receipt identity with a
final Backend aggregate; (4) a deterministic trigger identity that dedups
concurrent triggers before ordinal allocation; (5) session-global evidence
cursor closure; (6) a no-double-deduction budget formula.

## Minimal design

Machine-readable: `design.v1.json`.

### Contract mapping

- Keep `packages/contracts/session_failure_containment.py` closed and unchanged.
- Add a **closed step-safety registry** derived from
  `domain_call_admission.ACTIONS`, declaring per action
  `{idempotent, result_verifiable, may_produce_new_key}`.
- Extend the trusted Backend→Adapter reservation carrier
  `task-continuation-reservation.v1` with a closed `recovery_attempt`
  sub-record (P1-F); the Backend issues it, the client/model MUST NOT mint it.
- Reuse the existing prompt/guard/settlement receipt surfaces (per-attempt keys,
  P1-G), the existing Backend row (aggregate, P1-A/P1-B), the existing admission
  path (envelope, P1-K) and the existing Gateway→Backend `/internal/task-continuation`
  seam. No second store.

### Identity separation (P1-F)

Because `submit_prompt` returns the **old** run for a reused prompt key
(`runtime.py:780-789`) and forces the prompt key to `reservation_id`
(`806-809`), a rearm must use a **different** prompt idempotency key:

- **Budget authority identity** = original `reservation_id` (Backend-issued;
  unchanged; carried in the reservation).
- **Recovery submission identity** = `recovery_attempt_key`, issued and
  atomically persisted by the Backend when it allocates an ordinal, binding
  `(reservation_id, trigger_key, ordinal)`.
- **Trusted-carrier extension (closed fields):**
  `task-continuation-reservation.v1` gains a **closed** `recovery_attempt`
  sub-record with exactly `{attempt_key, ordinal, trigger_key,
  interrupted_run_id, interrupted_generation, containment_attempt,
  executor_epoch}`. Only the Backend mints it; `validate_reservation` keeps
  owner/workspace checks.
- **Adapter recompute/verify (fail closed).** `submit_prompt` MUST:
  1. recompute `trigger_key' = sha256("recovery-trigger.v1:" + reservation_id +
     ":" + interrupted_run_id + ":" + interrupted_generation + ":" +
     containment_attempt + ":" + executor_epoch)` from the carrier fields and
     require `trigger_key' == trigger_key`;
  2. recompute `attempt_key' = "recovery_" + sha256(trigger_key + ":" +
     str(ordinal))[:32]` and require `attempt_key' == attempt_key`;
  3. require `containment_attempt` and `interrupted_generation` to match the
     durable containment record for the same session/trace/run, and
     `executor_epoch` to equal the **live** executor epoch and the target
     `RuntimeGeneration`;
  4. require the prompt `idempotency_key == attempt_key` and the carrier's
     reservation id to equal the budget's `reservation_id`.
- **Rejections:** a missing carrier field, a tampered/mismatched `trigger_key` or
  `attempt_key`, a mismatched reservation/ordinal, and a stale/unknown
  `executor_epoch` or generation all raise (fail closed). A *new* attempt key
  yields a *new* run (no old-run dedup).

### Per-attempt receipt identity (P1-G)

Each attempt gets its own identity in the **existing** receipt surfaces; the
Backend row's `recovery_attempts` is the final authoritative aggregate:

- prompt receipt: `journal.prompts[attempt_key] = {root_run_id, content_sha256}`
  (distinct keys → independent receipts; old keys are never overwritten);
- guard journal: the new root's `continuation-budget.jsonl` read by
  `read_guard` (charge for that attempt);
- settlement: `persist_settlement` uses `attempt_key.json` (extension) instead of
  `reservation_id.json`; each receipt is immutable and bound to
  `{reservation_id, ordinal, run_id, charged_tokens, settlement_sha256}`.
- **Closed attempt states:** `reserved → submitted → accepted → settled |
  outcome_unknown | rejected`, with only the legal transitions; `outcome_unknown`
  is terminal-until-reconciled.
- **Bounds:** a settlement larger than the original reservation is rejected;
  cumulative **exact** charges of the original attempt plus every recovery
  attempt must never exceed `R.token_limit`; an unknown attempt charge → `paused`;
  old receipts are never overwritten.

### Recovery trigger identity and atomic allocation (P1-H)

A bare `counter++` is insufficient: two concurrent callers reading `k-1` would
allocate `k` and `k+1`, consuming two attempts for one loss. The design
allocates by **deterministic trigger identity**:

```text
trigger_key = sha256("recovery-trigger.v1:" + reservation_id + ":" +
                     interrupted_run_id + ":" + interrupted_generation + ":" +
                     containment_attempt + ":" + executor_epoch)
attempt_key = "recovery_" + sha256(trigger_key + ":" + str(ordinal))[:32]
```

Under the task-row `FOR UPDATE`, the Backend first scans `recovery_attempts`: if
an attempt with the same `trigger_key` exists it returns that attempt (no new
ordinal); only a **new** authoritative fenced loss identity allocates the next
ordinal. A later recovery run that loses again yields a new fenced loss identity
(new `interrupted_run_id`/generation/epoch) → the next ordinal is allowed.
Cap = `RECOVERY_ATTEMPT_MAX = 3`. The attempt key is recomputable and verifiable
from the trigger key + ordinal, so it is auditable without a new store.

### Authoritative step-safety: session-global cursor closure (P1-I)

The adapter journal and `agent_domain_call_evidence` sequences are
**session-global** (`observe_call` uses `len(state["calls"])+1`; PK is
`(owner,workspace,session,sequence)`), so a per-root filter "start at 1 and
contiguous" would misread the 2nd+ root as a gap. The closure rule is:

1. **Stable-snapshot closure.** Fetch/sync bounded pages from the adapter
   (`domain_call_evidence`) under the **same locked/consistent view** until the
   **final** page has `more == false` **and** `idle == true` (the session has no
   open root). `more == false` alone under concurrent appends does not prove the
   tail is closed. Reconcile adapter pages with the persisted
   `agent_domain_call_evidence` rows **item-by-item** by `(session, sequence,
   action, idempotency_key, request_sha256, input_sha256)`; the union must be the
   session-global `1..N` strictly contiguous. `idle == false`, a tail change
   between pages, or an inability to obtain a consistent locked snapshot and
   closure → `paused`.
2. **Then** filter the target root by exact `(session_id, trace_id, root_run_id,
   generation, agent_run_id)`. The target subset must be strictly increasing and
   consistent with the global sequence; it does **not** need to start at 1
   (a second root's first observed sequence > 1 is legal).
3. If the adapter/journal/cursor is unreadable, pagination is incomplete, the
   snapshot is not stable, or the tail closure cannot be proven after loss →
   `paused`.
4. Each observed call binds `(action, task_id, idempotency_key, request_sha256,
   input_sha256)` and reconciles against `agent_domain_call_claims`. Zero
   evidence for a dispatched run, a genuine session-global gap, or any unknown/
   conflict/unqueryable call → `paused`/`blocked`. Eligible only when all
   occurred side effects are settled and the work to replay is admissible under
   the envelope below. No prompt/display/client/"last call" inference; an
   ordinary prompt-only turn with no task reservation stays `paused`.

### Budget binding: original-row rearm, corrected formula (P1-A, P1-E, P1-J)

The earlier "new continuation reservation" is **withdrawn** (`309-310` rejects it
while any row is non-settled; a lost dispatch is `outcome_unknown`). Recovery
re-arms the **same** row `R` (same `reservation_id`/`event_key`/`token_limit`);
original-row rearm is **not** a new turn.

The earlier formula `min(P.token_limit − committed − unresolved, R.token_limit −
known_charge)` **double-deducts** `R`'s ceiling (it is already inside
`unresolved`). Corrected:

```text
# 1. Grant allocation invariant (fail closed on anomaly)
other_settled      = Σ charged_tokens over settled rows other than R
other_unresolved   = Σ token_limit over {reserved,accepted,outcome_unknown} rows other than R
require other_settled + other_unresolved + R.token_limit <= P.token_limit   # else blocked

# 2. R's own headroom from its cumulative EXACT charges (original + all attempts)
cum_exact = exact charge of the original attempt (0 if never accepted) +
            Σ exact charged_tokens of every reconciled recovery attempt
R_available = R.token_limit - cum_exact          # None if any charge is unknown

# 3. No second deduction of R's ceiling; no new reservation; no new turn.
#    Tri-state decision: blocked | None(paused) | eligible.
blocked  if permission revoked / expired / continuation_blocked_reason set
blocked  if the grant allocation invariant (step 1) is violated
blocked  if ordinal >= RECOVERY_ATTEMPT_MAX
blocked  if authoritative evidence conflicts (settlement/hash mismatch)
blocked  if R_available is KNOWN and < model_call_floor AND the envelope needs a model call
None     if R_available is None (any attempt charge unknown) or any input unreadable
None     if step-safety / closure cannot be authoritatively obtained
eligible otherwise (R_available >= floor, or a pure read-only envelope)
```

- **Tri-state rule (no contradiction):** authoritative denial or conflict is
  `blocked`; unknown/unavailable cost or input is `None` → `paused`; only a known
  `R_available` below the model-call floor is `blocked` **when the envelope needs
  a model call**. A pure read-only envelope does **not** need a model-call floor;
  if the implementation still needs a model call it MUST NOT claim read-only
  floor-exemption.
- Revocation/expiry/`continuation_blocked_reason` still block. `max_turns` is
  only used to verify the original ledger/authorization was not exceeded;
  recovery within `R` does not require an extra free turn.
- **Numeric example:** `P.token_limit = 100`, other settled = 30, `R.token_limit
  = 60`, original + recovery known cumulative charge = 20. Invariant: `30 + 60 =
  90 ≤ 100`. `R_available = 60 − 20 = 40` — **40, not 10**. The old formula's
  `min(100−30−60, 60−20) = min(10, 40) = 10` was wrong.
- Unknown cost is never `0` and is never refunded; `outcome_unknown` without a
  reconciled guard receipt → `R_available = None` → `None`/`paused`.

### Recovery-mode domain admission envelope (P1-K)

Receipt closure proves only the past. A replayed prompt as a fresh model run
could still mint a **new** action key, so a registry declaration alone does not
make it safe. A recovery run is therefore admitted only inside a
**recovery-mode envelope** enforced by the Backend at admission:

- **(a) read-only only**, or
- **(b) exact reuse of an original persisted safe call** — the same
  `(action, task_id, idempotency_key, request_sha256, input_sha256)` present in
  the lost root's `agent_domain_call_evidence`, verified by the Backend.
- The registry's `may_produce_new_key` field is **conservative classification
  only**: an action declared `may_produce_new_key=true` is **always
  ineligible/blocked** for automatic recovery. It MUST NOT authorize the model
  or a recovery run to mint a new key. Enabling a new key is beyond this design
  and would require a separate **Proposed** ADR (never opened or implied here).
- The model MUST NOT choose the mode or mint keys; the Backend enforces the
  envelope against the lost root's `agent_domain_call_evidence`.
- Any out-of-envelope new write, different input/hash/key, or
  publish/order/paid/irreversible action → `blocked`/`paused`.
- If the "work to replay" cannot be predetermined from the envelope + registry,
  it MUST NOT be `eligible` for automatic rescheduling.

### Failure semantics

Unknown/unavailable authority → `paused`; conflict → `blocked`; unknown cost,
zero evidence for a dispatched run, session-global gaps, unreadable pagination or
out-of-envelope work → `paused`/`blocked`; stale epoch/generation/attempt and
terminal reopen fail closed. `failed`/`cancelled`/`discarded`/`closed` keep
ordinary semantics; `interrupted` is projected only from the fenced containment
record matching the same session/trace and exact run.

### Next implementation-slice acceptance criteria

1. Closed registry + recovery-mode envelope; `may_produce_new_key=true` is
   conservative only and always ineligible (a new key would need a Proposed ADR).
2. Backend-minted `recovery_attempt_key` carried in the closed `recovery_attempt`
   sub-record `{attempt_key, ordinal, trigger_key, interrupted_run_id,
   interrupted_generation, containment_attempt, executor_epoch}`; the Adapter
   recomputes/verifies both keys and fences the LIVE executor epoch/generation;
   client/model cannot mint it.
3. Per-attempt prompt/guard/settlement receipts (`attempt_key.json`), immutable,
   bound to `{reservation_id, ordinal, run_id, charged_tokens, settlement_sha256}`;
   Backend `recovery_attempts` is the final aggregate; cumulative exact charges
   ≤ `R.token_limit`.
4. Trigger-key dedup before ordinal allocation under the task-row `FOR UPDATE`;
   cap 3; concurrent same-trigger calls create exactly one attempt.
5. Stable-snapshot session-global closure (final page `more=false` AND `idle=true`
   under one locked view; item-by-item adapter↔Backend reconciliation; global
   `1..N` contiguous; per-root subset strictly increasing, not required to start
   at 1; unstable/unproven closure → `paused`).
6. Corrected budget formula (grant invariant; `R_available = R.token_limit −
   cum_exact`; no second deduction; numeric example reproduced).
7. Fail-able observer + negative controls (Adapter old-run dedup; immutable
   settlement slot; concurrent trigger; second-root sequence >1; double-deduct;
   out-of-envelope write).
8. No runtime code in this slice; no selector/deploy/release/tag/Phase 100
   resume/D15 superseding assessment.

### ADR decision: no new ADR (proven by the mapping)

The design only extends already-authorized components: the existing Backend
authority row (in-row `recovery_attempts`, no independent store); the existing
closed contract/carrier and a closed registry (no new persistence authority); the
existing prompt/guard/settlement receipt surfaces keyed per attempt (no new
store); the existing session-global call evidence and admission path (no new
trust subject or cross-Plane interface); the existing Gateway→Backend
`/internal/task-continuation` seam and adapter dispatch path. The ADR-0084 gate
classification is unchanged. **Therefore no new ADR is required.**

A **Proposed** ADR (never Accepted here) is required before implementation if a
later slice introduces an independent recovery store, a new public/internal
cross-Plane authority interface, a database schema/migration, a new trust
subject, or a change to the ADR-0084 gate classification.

## Boundary facts (unchanged)

- B1 `subagent-child-crash` and B2 `subagent-byq-adapter-restart` remain
  `BLOCKED_EXTERNAL`.
- Historical D15-G remains `NO_GO`; historical verdicts are not rewritten.
- `R3_RESUME = NO`; 0.9 is not closed.
- Full business-recovery gate remains `IN_PROGRESS / BLOCKED_INTERNAL`.
- No production selector switch, deploy, release/tag, Phase 100 resume or `#338`
  change. Native child resume is not implemented; unknown side effects pause.
  This PR creates no D15 superseding assessment.
