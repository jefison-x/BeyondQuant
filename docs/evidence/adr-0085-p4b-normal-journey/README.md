# ADR-0085 P4-B — normal three-round journey (0.9.1)

## Scope

This slice implements **ADR-0085 P4-B** on top of the merged P4-A integration
foundation, Accepted ADR-0086 and Accepted **ADR-0087**. It is a
maintenance/stability change for the **0.9.1** version. It does **not** deploy,
does **not** write a version number, does **not** create or move any tag or
release, does **not** run a production canary, does **not** resume Phase 100 and
does **not** start 0.10.

P4-B proves the **normal research main chain**: one compound `ResearchTask` driven
through the real Product API, the authenticated Runtime Adapter judgment route,
the real DSH child/tool invocation and the committed Backend deterministic seams:

```
create compound task -> conversation continuation grant
  -> bounded strategy_draft judgment (real DSH child/tool)
  -> exact plan-bound strategy approval (human, Product API)
  -> exact plan-bound task-create approval (human)
  -> deterministic create_backtest_task (zero model calls)
  -> data-ready (zero model calls)
  -> exact plan-bound execute approval (human)
  -> deterministic execute_backtest_task (zero model calls)
  -> backtest-completed (zero model calls)
  -> backtest_analysis judgment -> iteration_comparison
  -> three rounds 1->2->3 (exact create gate, no skipped iteration)
  -> final_selection judgment -> waiting_for_paper_account_approval
  -> exact plan-bound paper_account_create approval (human, Product API)
  -> deterministic ready_to_create_paper_account -> real Product API account create
  -> deterministic CAS commits the account reference -> plan/task completed
```

It does **not** run the asynchronous-handoff fault matrix (P4-C1/P4-C2) and does
**not** run the unified final acceptance (P4-D).

## Result: `format_valid=true`, `all_pass=true` (P4-B scoped)

With ADR-0087 the paper-account row is **required and gating** and is now derived
TRUE from the raw facts: exactly one account, the exact plan-bound
`byq_paper_account_create` approval (`plan_action=paper_account_create`,
`plan_resource_kind=research_task`, `plan_resource_id=task_id`, BYQ
`params_digest`, BYQ `plan_idempotency_key`, plan/task versions), created through
the real Product API, an exact replay returning the **same** account, the
deterministic CAS completing plan/task, and **no** order/position/fill. The P4-B
verdict is:

```
format_valid = true
all_pass     = true
blocked_rows = {}
```

This `all_pass=true` is **scoped to P4-B** (normal main chain + request gate +
deterministic paper-account approval); it is **not** an overall P4/P4-C/P4-D
pass and does not by itself unlock P4-C1. The P4-A verdict is unchanged
(`all_pass=false`).

## ADR-0087 deterministic paper-account approval

- `docs/architecture/adr/ADR-0087-deterministic-paper-account-approval.md`
  (Accepted 2026-09-25).
- `final_selection` now commits to `waiting_for_paper_account_approval`; the
  exact plan-command-bound `paper_account_create` approval advances the plan to
  `ready_to_create_paper_account`; the deterministic `create_paper_account`
  action completes it.
- `paper_account_create_parameters` (trusted, read-only) returns the FROZEN
  approved `create_paper_account` command: `name`, `cash` (BYQ policy default),
  `resource_kind/resource_id`, `params_digest` and `idempotency_key` are all read
  from the persisted approved approval row and the plan's bound approval, never
  recomputed for a newer plan version. The observer proves the approved
  `plan_params_digest`/`plan_idempotency_key` EQUAL the executed params
  digest/key even though the plan advanced (approval vN, create vN+1).
- The account is created through the existing Product API
  (`POST /api/product/paper/accounts`) / `PaperTradingStore` idempotency/audit
  path; the Backend never calls the Gateway and MCP/DSH never write the account.
  `create_paper_account` is a declared BYQ domain capability, never an MCP write
  tool.
- `apply_deterministic_action_result` verifies the account belongs to the exact
  task owner/workspace, commits the `paper_account` reference and completes the
  plan/task in one transaction; replay is a free re-projection.

## ADR-0086 request-scoped provider gate

ADR-0086 replaces the historical fixed "at most 2 model calls" reading with a
**request-scoped layered budget**:

- `packages/contracts/research_request_budget.py` — closed, pure contract:
  `stage_request_limits`, `validate_request_budget`, `validate_request_usage`,
  `request_budget_decision`. Hard dimensions: provider call, attempt, input
  bytes, **declared** output-token ceiling, tool-payload bytes, deadline,
  concurrency, cancellation.
- `services/runtime-adapter/app/research_request_gate.py` —
  `ResearchRequestGate` + a loopback `RequestGateProxy`. The DSH harness is
  pointed at the proxy (`DEEPSEEK_BASE_URL`) and reaches the real provider only
  after the gate admits the request, so the gate runs BEFORE every root and child
  request and covers both roles.
- `research_judgment_turn.py` opens one request-scoped gate per named judgment
  request and points the harness at the proxy. A refused request fails the turn
  closed.

### Per-stage named profiles (ADR-0086 §1)

The limits are NOT a global constant. `packages/contracts/research_request_budget.py`
holds a closed, BYQ-trusted registry (`REQUEST_PROFILES` / `STAGE_PROFILES`): each
of the four judgment stages maps to its OWN named profile carrying the full
multi-dimensional limits and a mandatory evidence note. The observed
root→child→root path is 3 provider calls for each current stage, but that value is
a per-profile fact, not a claim that 3 is the constant for all DSH work. The
trusted-profile binding is exact: `profile_id`, `stage`, `evidence` and every
multi-dimensional limit must equal the registered profile (only `deadline_at_ms`
is derived from the request start time). A budget whose profile is unknown, whose
stage does not match, whose evidence is forged, whose limits differ, or whose
evidence is missing fails closed; a caller cannot pass a different stage's profile
or raise a limit.

### Declared output ceiling (ADR-0086 acceptance)

Every provider call must declare its output-token ceiling. A missing, zero,
boolean, negative, or conflicting declaration (`max_tokens` vs
`max_completion_tokens` vs `max_output_tokens`) fails closed BEFORE the request is
issued with a closed reason (`declared_output_limit_missing` /
`declared_output_limit_invalid` / `declared_output_limit_conflict`); a declaration
above the profile ceiling is refused (`output_tokens_limit`). The ceiling is never
silently filled with a default, and the upstream is never hit for an undeclared
cap.

### Closed provider header forwarding

The loopback proxy forwards only a minimal closed allowlist of provider headers —
`authorization`, `content-type`, `accept` — from the DSH→proxy request to the real
provider. The DSH provider is configured with `apiKeyEnv` (`DEEPSEEK_API_KEY` /
`OPENCODE_API_KEY`) and the OpenAI-compatible adapters authenticate with
`Authorization: Bearer`; there is no repository/SDK evidence for `x-api-key`, so it
is not forwarded. BYQ product/internal tokens (`x-byq-*`), cookies and hop-by-hop
headers (`connection`, `proxy-authorization`, …) are never forwarded, and no
header VALUE is written to a receipt, log or evidence. A fail-able loopback test
proves the upstream receives the expected `Authorization` while the internal token
and cookie are absent and the journal contains no secret value.

### Declared ceiling vs actual usage (ADR-0086 §3)

The pre-request receipt records the **declared** ceiling
(`declared_max_output_tokens`); the completion receipt records the
**provider-reported actual** input/cache/output tokens (`actual_*_tokens`) and
`elapsed_ms`. The declared ceiling is never reported as actual consumption. A
provider-proven actual output above the declared ceiling is **discarded** and the
request fails closed (`output_tokens_exceeded`); a result that arrives after the
deadline is never forwarded (`deadline_exceeded`), and the upstream timeout is
exactly the remaining deadline (no artificial floor). A response whose actual
output usage cannot be proven is **not** forwarded or submitted: it fails closed
with the structured reason `actual_usage_unknown` (ADR-0086 §3), so an unprovable
result is never treated as 0 or as a free budget refresh. Usage is parsed from
both supported OpenAI-compatible shapes: a streamed SSE body whose final `data:`
chunk carries `usage`, and a non-streaming JSON body with a top-level `usage`.

### Observed real gate evidence

`observations.v1.json` records, for each of the 8 judgment turns, the named
request profile and the per-call gate receipts with declared ceiling, actual
usage, usage source, elapsed time and forward decision.

`request_gate_negative_control.py` (host, no carrier) drives real HTTP requests
through the real proxy and proves each dimension is refused before/instead of
forwarding: provider call, input bytes, tool payload, expired deadline,
cancellation, concurrency, provider-proven over-limit output (discarded),
unprovable actual usage (discarded) and a slow upstream bounded by the remaining
deadline; plus unknown stage/profile, missing field, caller override, forged
evidence and a forged/raised budget all fail closed, and an undeclared/zero/bool/
negative/conflicting/over-profile output ceiling fails closed with the upstream
never hit (`upstream_hits=0`).

### Adapter convergence for a gate failure

A gate refusal fails the DSH turn; `run_bounded_research_judgment` then propagates
a closed `ResearchJudgmentError` to the authenticated entry (HTTP 503
`research_judgment_failed_closed`) and the existing needs_attention/error path. It
does **not** auto-retry the same pending attempt and does **not** submit any
result; a later duplicate for the same in-flight admission is an explicit
`409 research_judgment_in_progress`.

## Deterministic hand-offs and object uniqueness

The journey makes **zero** model calls for the deterministic transitions; the
provider accounting shows exactly 3 provider calls per judgment turn (8 turns =
24 calls). Raw facts record exactly one `ResearchTask`, one execution plan, 8
stage calls (one per judgment turn, `call_index=1`), 7 plan-command-bound
approvals, 13 continuation events, 3 signal jobs, 3 backtest jobs and 1 paper
account. Every approved approval carries its plan action/resource, parameter
digest and a stable low-entropy audit alias for the plan-command key (the raw
high-entropy key is never persisted in evidence).

## What was actually run

- **Real isolated non-production stack**: `byq-p4-judgment` compose project over
  `compose.runtime-qual.yml` + `compose.p4-judgment.yml` + `compose.p4b.yml`
  (dedicated network/volumes, fresh PostgreSQL, loopback-only ports).
- `scripts/v091/continuation_p4b/run_journey.py` drove the normal journey and
  wrote `observations.v1.json`; it then tore the isolated stack down and recorded
  zero leftover containers/networks/volumes with production untouched.
- The fail-able observer (`observer.py`) re-derives every row from raw facts and
  produced `verdict.v1.json` (`format_valid=true`, `all_pass=true`).
- `--selfcheck` rejects all 35 defect-targeting controls while a legacy
  label-trusting gate accepts every one.

## Reproduce

```bash
# Observer self-check (fail-able; 35 defect-targeting controls all rejected).
python3 scripts/v091/continuation_p4b/observer.py --selfcheck

# Host request-gate negative controls (no Docker).
PYTHONPATH=services/runtime-adapter:. \
  python3 scripts/v091/continuation_p4b/request_gate_negative_control.py

# Governance/contract/matrix tests (architecture lane, no DB, no Docker).
python3 -m unittest tests.test_v091_continuation_p4b

# Re-derive the committed verdict (exit 0: P4-B scoped all_pass=true).
python3 scripts/v091/continuation_p4b/observer.py \
  --observations docs/evidence/adr-0085-p4b-normal-journey/observations.v1.json \
  --out docs/evidence/adr-0085-p4b-normal-journey/verdict.v1.json

# Real isolated stack journey (opt-in; requires Docker; no paid API, no production).
PYTHONPATH=services/runtime-adapter:. BYQ_P4_ROOT=<worktree> \
  python3 scripts/v091/continuation_p4b/run_journey.py
```

## Production changes (minimal)

- `services/backend/app/research_judgment.py`: completion starts a still-planned
  task in the same transaction so a deterministic plan journey can converge.
- `services/runtime-adapter/app/research_judgment_api.py`: each named judgment
  request gets its own DSH home so a later stage never collides with an existing
  DSH session.
- `services/runtime-adapter/app/research_judgment_entry.py` /
  `research_judgment_turn.py`: attach the request-scoped gate and expose its
  limits/receipts.
- `plugins/.../byq-research-judgment.patch.yml`: declares a real output ceiling.

## Non-claims

- No production deployment, version write, tag or release.
- No production canary; only an isolated non-production stack.
- No real-LLM research-quality semantic claim; the driver uses a keyless
  scripted provider.
- No Phase 100 resume and no 0.10 start.
- No second generic agent harness or session store; the model only submits a
  bounded research proposal and never chooses `next_action`, object identity,
  approval, idempotency, routing or recovery state.
- No claim of the P4 fault matrix, P4-C, an overall P4 all_pass or phase
  completion. The P4-A evidence and verdict are unchanged (`all_pass=false`).
