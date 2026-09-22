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
4. a dedicated bounded judgment DSH **persona** with a static exact read-only
   `toolFilter`;
5. an **atomic** trusted result operation (proposal commit + progress receipt +
   admission completion + terminal convergence in ONE transaction);
6. one concrete trusted runtime-adapter internal invocation through that persona.

The model may propose a bounded research judgment. It can NEVER choose the
workflow `next_action`, object identity, approval execution, idempotency key, job
routing, recovery or continuation state. There is **no** generic
plan/event/proposal write route and no agent-facing write tool.

## Design

### Bounded judgment persona (not a client header)

The judgment turn runs INSIDE the composition role `research-judgment-turn`
(`toolName: byq_research_judgment_turn`, `maxDepth: 0`, foreground one-shot). Its
`toolFilter.allow` is a static exact read-only allowlist
(`byq_agent_context`, `byq_research_get`, `byq_research_stage_input_get`,
`byq_backtest_task_get`, `byq_backtest_analysis_get`). The model invoked through
that role has no write/approval/execute/routing/identity tool and no proposal
tool; the capability cannot be omitted or widened by model output. The
`byq_research_stage_input_get` read tool is exposed ONLY to that role. The
runtime adapter (`RESEARCH_JUDGMENT_PERSONA_TOOL`) invokes exactly that role; an
architecture test fails CI if the constant and the generated composition diverge,
and asserts the enumerated tools are write-free. (`@deepseek-ai/dsh-tool-subagent`
is the official rc.1 bounded-role seam; ADR-0038 records that rc.1 has no root
tool filter, so the bounded role is a subagent persona.)

### Atomic trusted result

`POST /internal/research-judgment/{task_id}/result` calls ONE named store
operation, `record_research_judgment_result`, which in a single transaction:
validates a closed proposal, commits it through the deterministic reducer/plan
CAS, records the authoritative durable-progress receipt, completes the stage-call
admission and (for `final_selection`) converges the ResearchTask through the
existing validated completion path. The named evidence record is verified even
when an accepted proposal already advanced the plan. Any failure leaves the plan,
task, stage-call ledger and receipts unchanged; an exact replay returns the same
stored receipt without another write.

### Two-call bound and fence

`admit_research_stage_call` persists a `research_judgment_stage_calls` row per
`(task, plan_version, stage)` under the task-row lock and derives the 1-based
count; the caller supplies only a `call_identity`. A third admission fails closed,
exact replay is free, and concurrent admission never exceeds two. A FIRST
completed check without authoritative progress atomically sets plan and
ResearchTask to `needs_attention/no_durable_progress`.

## Files

- `packages/contracts/research_judgment.py` — closed stage-input/proposal,
  admission, progress-evidence and judgment-result schemas; bounds; forbidden
  raw/routing fields; pure commit reducer; two-call bound; first-check fence.
- `services/backend/app/research_judgment.py` — read-only stage input, durable
  admission, atomic result operation, authoritative progress + atomic fence,
  named proposal commit, atomic terminal completion.
- `services/backend/app/main.py` — read-only stage-input route and the two
  private research-judgment consumer routes.
- `services/mcp/src/research-judgment.ts`, `server.ts` — bounded read-only tool.
- `plugins/dsh-byq/compositions/templates/byq-product-sdk.cordis.yml` — the
  bounded judgment persona (regenerated composition/identity/profiles).
- `services/runtime-adapter/app/research_judgment.py` — concrete trusted
  invocation: admit → bounded persona turn → atomic result.
- `plugins/dsh-byq/runtime/byq-continuation-budget.js` — two-call mirror.

## Evidence / reproduce

```bash
python3 -m unittest tests.test_research_judgment_contract tests.test_research_judgment_benchmark
python3 -m unittest tests.architecture.test_architecture
python3 -m unittest tests.test_dsh_d15_4_subagent tests.test_dsh_d15_4_continuable_wiring
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

Focused evidence: bounded role/composition enumerates only exact read tools with
no optional-header bypass; missing/forged stage binding fails closed; valid
proposal plus invalid progress evidence causes zero state changes; injected
failure between proposal decision and call completion rolls back everything;
exact result replay is stable and free; concurrent admission <=2; no-progress
fence; deterministic zero-call; terminal consistency.

The 60-case offline `benchmarks/jev` dataset and rubric are reused ONLY as a
deterministic calibration fixture (never a router; no model, paid API or
production database is called by the tests).

## Non-claims

- No real three-round journey / fault matrix / canary (that is P4). Capturing the
  result from a real DSH model turn and the full journey remain P4.
- No deployment, tag/release, Phase 100 resume or 0.10 start.
- `R3_RESUME = NO`; D15-G remains `NO_GO`; the D15-4 verdict is not rewritten (its
  composition reachability count tracks the added foreground persona).
