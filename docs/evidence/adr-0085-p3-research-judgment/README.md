# ADR-0085 P3 — bounded research-judgment turn (0.9.1)

## Scope

This slice implements the Accepted ADR-0085 **P3** only, on top of merged P0/P1/P2.
It is a maintenance/stability change; it does not advance a Product Phase, does
not deploy, tag or release, does not resume Phase 100 and does not start 0.10.

For ONLY the genuine research-judgment plan stages (`strategy_draft`,
`backtest_analysis`, `iteration_comparison`, `final_selection`) it adds:

1. a framework-neutral, CLOSED and bounded stage-input/proposal contract;
2. a durable per-stage **model-call admission/receipt** (authoritative count);
3. authoritative durable-progress evidence derived from persisted BYQ records;
4. a **stage-scoped runtime enforcement** so the judgment turn has only the exact
   read-only tools (MCP dispatch boundary);
5. a named server-side proposal seam plus atomic task/plan terminal convergence;
6. one concrete trusted **runtime-adapter internal invocation** through
   admission → closed model result → validation/commit/progress receipt.

The model may propose a bounded research judgment. It can NEVER choose the
workflow `next_action`, object identity, approval execution, idempotency key, job
routing, recovery or continuation state. There is **no** generic
plan/event/proposal write route and no agent-facing write tool.

## Blockers fixed

1. **Two-call limit now enforced authoritatively.** `admit_research_stage_call`
   persists a `research_judgment_stage_calls` row per task/plan/stage under the
   task-row lock and derives the 1-based `call_index`; the caller supplies only a
   `call_identity`. A third admission/plan revision fails closed
   (`StageModelCallLimitExceeded`), exact replay is free, and concurrent
   admission never exceeds two (unique `(task, plan_version, stage, call_index)`).
2. **Progress is authoritative, not caller-asserted.** `record_research_stage_progress`
   takes a CLOSED durable-evidence descriptor (`none`/`plan_advance`/`artifact`/
   `experiment`/`backtest_job`) and derives/binds the identity from the named
   persisted record. A bare digest or any record not owned by the task fails
   closed. A plan advance caused by an accepted proposal is authoritative
   progress and cannot be suppressed. The FIRST completed check without progress
   atomically sets plan **and** ResearchTask to `needs_attention` /
   `no_durable_progress`.
3. **Stage-scoped runtime enforcement.** `services/mcp/src/research-judgment-admission.ts`
   admits ONLY the exact read-only tools for the stage when the trusted adapter
   sets `x-byq-research-judgment-stage`, and blocks every write/approval/execute
   tool. The Python contract `STAGE_ALLOWED_TOOLS` and the TS `STAGE_READ_TOOLS`
   table are held identical by an architecture test.
4. **Concrete internal invocation.** Backend private endpoints
   `POST /internal/research-judgment/{task_id}/admit` and `/result` (trusted
   runtime-adapter consumer) plus `services/runtime-adapter/app/research_judgment.py`
   admit a call, run the bounded turn, and submit the CLOSED model result through
   validation/commit/progress receipt. Agent-facing MCP/Browser stays read-only.
   Capturing the result from a real DSH model turn and the full three-round
   journey remain P4 per ADR-0085; P3 does not claim a completed real journey.
5. **Terminal convergence.** A `final_selection` commit completes the
   ResearchTask through the existing validated completion path (same-task
   validated evidence + no unfinished jobs) in the SAME transaction as the plan
   CAS, so the task and plan never disagree about being terminal.

## Files

- `packages/contracts/research_judgment.py` — closed stage-input/proposal,
  progress-evidence and admission schemas; bounds; forbidden raw/routing fields;
  pure commit reducer; two-call bound; first-check fence.
- `services/backend/app/research_judgment.py` — read-only stage input, durable
  admission, authoritative progress + atomic fence, named proposal commit,
  atomic terminal completion.
- `services/backend/app/main.py` — read-only stage-input route and the two
  private research-judgment consumer routes.
- `services/mcp/src/research-judgment.ts`, `research-judgment-admission.ts`,
  `server.ts` — bounded read-only tool and stage-scoped enforcement.
- `services/runtime-adapter/app/research_judgment.py` — concrete trusted
  invocation (admit → bounded turn → closed result → commit/receipt).
- `plugins/dsh-byq/runtime/byq-continuation-budget.js` — two-call mirror.

## Evidence / reproduce

```bash
python3 -m unittest tests.test_research_judgment_contract tests.test_research_judgment_benchmark
python3 -m unittest tests.architecture.test_architecture
python3 -m unittest tests.test_reliability_review_audit tests.test_v090_final_closeout
python3 benchmarks/jev/validate_benchmark.py
# isolated PostgreSQL:
BYQ_DATABASE_URL=... python -m pytest -q services/backend/tests/test_research_judgment.py \
    services/backend/tests/test_research_judgment_api.py
# runtime adapter:
python3 -m pytest -q services/runtime-adapter/tests/test_research_judgment.py
# MCP:
cd services/mcp && npm run build && npm test
```

Targeted evidence: concurrent admission <=2; replay free; fabricated progress
rejected; first no-progress atomic fence; bounded-role tool enumeration has no
writes; internal invocation through commit; zero model calls for deterministic
stages; stale bindings and replay conflicts fail closed; final task/plan terminal
consistency.

The 60-case offline `benchmarks/jev` dataset and rubric are reused ONLY as a
deterministic calibration fixture (never a router; no model, paid API or
production database is called by the tests).

## Non-claims

- No real three-round journey / fault matrix / canary (that is P4).
- No deployment, tag/release, Phase 100 resume or 0.10 start.
- `R3_RESUME = NO`; D15-G remains `NO_GO`; historical verdicts are not rewritten.
