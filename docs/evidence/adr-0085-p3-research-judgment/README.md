# ADR-0085 P3 — bounded research-judgment turn (0.9.1)

## Scope

This slice implements the Accepted ADR-0085 **P3** only, on top of merged P0/P1/P2.
It is a maintenance/stability change; it does not advance a Product Phase, does
not deploy, tag or release, does not resume Phase 100 and does not start 0.10.

For ONLY the genuine research-judgment plan stages (`strategy_draft`,
`backtest_analysis`, `iteration_comparison`, `final_selection`) it adds:

1. a framework-neutral, CLOSED and bounded stage-input/proposal contract;
2. a minimal READ-ONLY MCP surface (`byq_research_stage_input_get`);
3. minimal DSH composition wiring (the read-only tool is exposed to the strategy
   and backtest-analysis roles; the runtime guard mirrors the two-call default);
4. a named server-side proposal seam plus a durable-progress fence.

The model may propose a bounded research judgment. It can NEVER choose the
workflow `next_action`, object identity, approval execution, idempotency key, job
routing, recovery or continuation state. BYQ validates and commits an accepted
proposal through `commit_research_proposal` and the deterministic reducer/plan
CAS. There is **no** generic plan/event/proposal write route.

## Files

- `packages/contracts/research_judgment.py` — closed stage-input/proposal schema,
  byte/item bounds, forbidden raw/routing fields, the pure commit reducer, the
  two-call bound and the first-check no-progress fence.
- `services/backend/app/research_judgment.py` — `get_research_stage_input`
  (read-only), `commit_research_proposal` (named seam, plan CAS) and
  `record_research_stage_progress` (atomic `needs_attention/no_durable_progress`).
- `services/backend/app/main.py` — one read-only `GET
  /v1/research/tasks/{task_id}/stage-input`; no proposal write route.
- `services/mcp/src/research-judgment.ts` + `server.ts` — bounded read-only tool.
- `plugins/dsh-byq/compositions/templates/byq-product-sdk.cordis.yml` (+
  regenerated composition/identity and candidate profiles) — minimal wiring.
- `plugins/dsh-byq/runtime/byq-continuation-budget.js` — `RESEARCH_JUDGMENT_MAX_CALLS`.

## Boundaries preserved

- DSH keeps Agent Loop/session/compaction/generic guards; no second harness or
  session store is built; DSH never accesses PostgreSQL.
- P2 exact approval/event binding and the "no generic continuation write route"
  invariant are unchanged.
- Deterministic stages use **zero** model calls; a deterministic stage input or
  progress call fails closed.
- The stage input excludes raw/full signal snapshots, bars/frame/index lists and
  stays under explicit byte/item bounds.

## Evidence / reproduce

```bash
python3 -m unittest tests.test_research_judgment_contract tests.test_research_judgment_benchmark
python3 -m unittest tests.architecture.test_architecture
python3 -m unittest tests.test_reliability_review_audit tests.test_v090_final_closeout
python3 benchmarks/jev/validate_benchmark.py
# isolated PostgreSQL:
BYQ_DATABASE_URL=... python -m pytest -q services/backend/tests/test_research_judgment.py
# MCP:
cd services/mcp && npm run build && npm test
```

The 60-case offline `benchmarks/jev` dataset and rubric are reused ONLY as a
deterministic calibration fixture: every oracle decision is classified through
the commit reducer, every case is representable within bounds and without raw
data, and no production module imports the benchmark. Jev is never a router; no
model, paid API or production database is called by the tests.

## Non-claims

- No real three-round journey / fault matrix / canary (that is P4).
- No deployment, tag/release, Phase 100 resume or 0.10 start.
- `R3_RESUME = NO`; D15-G remains `NO_GO`; historical verdicts are not rewritten.
