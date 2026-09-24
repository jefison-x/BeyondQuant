# ADR-0085 P4 — real journey and fault matrix (0.9.1)

## Scope

This slice implements the Accepted ADR-0085 **P4** only, on top of merged
P0/P1/P2/P3. It is a maintenance/stability change for the **0.9.1** version. It
does **not** deploy, does **not** write a version number, does **not** create or
move any tag or release, does **not** run a production canary, does **not**
resume Phase 100 and does **not** start 0.10.

P4 has two parts:

1. **The minimal missing production seam.** P0-P3 delivered the closed plan
   vocabulary, the durable event ledger and the bounded judgment turn, but no
   production code created a plan for a granted compound task, requested a
   plan-bound approval, executed a `ready_to_*` deterministic action, or
   advanced the plan from a real approval decision. `services/backend/app/
   research_plan_continuation.py` adds exactly that trusted seam.
2. **The frozen acceptance matrix and fail-able evidence.** The matrix is frozen
   in `acceptance-matrix.v1.json` **before** capture; the closed contract is
   `scripts/v091/continuation_p4/contract.v1.json`; the observer re-derives every
   row from raw facts and distinguishes `format_valid` from `all_pass`.

## Real driver and the real gap (2026-09-23)

`run_journey.py` is now a genuine driver: it reuses the committed
`scripts/v090/composite_research` stack/HTTP helpers, boots the isolated
non-production stack, creates the compound ResearchTask and conversation grant
through the real Product API, reads the real execution plan, drives the
deterministic remainder through the real production seam via the trusted
in-container `step_runner.py`, restarts Gateway/Backend/Runtime Adapter at the
precise hand-offs and asserts real PID change + resumed business state, and
records raw facts only from real HTTP responses, container identities and
DB/ledger queries. Guard functions fail closed on an empty Gateway, zero real
HTTP calls, a restart without recovery, placeholder raw facts and hardcoded
PASS (negative-tested in `tests/test_v091_continuation_p4.py`).

**Corrected P3-to-P4 seam audit (BYQ wiring gap, not an upstream blocker):**
machine evidence `p3-to-p4-invocation-seam-audit.v1.json`
(`scripts/v091/continuation_p4/dsh_invocation_seam_audit.py`, run inside the
candidate image). DSH 0.1.5rc1 does not expose a host-named role/tool API (the
SDK has only `initialize`/`start_session`/`session.run`; the carrier emits
`subagent/start` as a plugin event, and the mcp-client has no tool allow/deny
list). But ADR-0085 does not require such an API: P3 authorizes a **minimal DSH
composition/MCP surface**. Root-level `toolFilter` is not supported and the MCP
client always registers the server's full `tools/list`, so the ADR-required
mechanism is a **dedicated static bounded composition** that loads only a
minimal read-only MCP subset and the bounded `research-judgment-turn` persona.
This is feasible under existing DSH native capability; the real gap is that the
P3 `turn_runner` is an **unconnected BYQ seam** (no production caller). P4 must
implement the minimal read-only MCP surface, the dedicated composition and the
Runtime Adapter `turn_runner`/endpoint — not relabel it as upstream.

## Isolated read-only MCP surface (2026-09-23)

The bounded judgment composition needs a read-only MCP surface that exposes only
the five bounded read tools. `services/mcp/src/server.ts` now gates registration
with an explicit, type-checked guarded function (it no longer overwrites
`registerTool`), reads its own `BYQ_MCP_READ_ONLY_PORT`/`BYQ_MCP_READ_ONLY_TOKEN`
and refuses to start without them, and only starts listening when it is the
server process (importing the factory has no side effects). The default Product
surface is unchanged.

`services/mcp/tests/read-only-subset-test.ts` spawns two real servers on
separate ephemeral ports with separate credentials and calls the **real MCP
`tools/list`** through `@modelcontextprotocol/client`: the isolated instance
exposes exactly five tools (`full=82`, `read_only=5`), the Product instance still
exposes the write tools, and each instance rejects the other's token. A negative
control that patches the built server to ignore the gate makes the same test exit
`1`, so a trailing `exit 0` cannot mask a broken surface. The change to
`server.ts` invalidated the H4 current reliability ledger and the current build
revision, which were re-verified and refreshed (digest-only; no interface row was
deleted, bulk-marked or re-affirmed) — the historical D15/v090 verdicts and
evidence are untouched.

Still **not** proven and recorded as such: the root and child tool arrays on the
real DSH carrier with this read-only MCP loaded, the bounded read-tool returns,
the child persona invocation and the real closed loop.

## Real-carrier child-persona proof and the `maxDepth` correction (2026-09-23)

`carrier_readonly_mcp_probe.py` runs inside the real `byq-d15-runtime-candidate`
image against a live isolated read-only MCP endpoint with a keyless scripted
provider. Raw facts (`carrier-readonly-mcp-child.v1.json`):

- the real carrier starts and the ROOT provider request exposes `byq_research_judgment_turn`
  plus exactly the five read-only MCP tools (`mcp__byq__byq_agent_context`,
  `byq_research_get`, `byq_research_stage_input_get`, `byq_backtest_task_get`,
  `byq_backtest_analysis_get`) and no write/approval/execute/routing tool;
- the root invokes the bounded persona and the CHILD provider request exposes
  exactly the five read-only MCP tools (the static `toolFilter` allowlist);
- the child returns a closed result to the root; the provider saw three calls;
- the MCP endpoint's real `tools/list` returned exactly the five read tools.

This run also found a real defect: the dedicated composition used `maxDepth: 0`,
which makes the role **unspawnable** (`subagent depth 1 exceeds maxDepth 0`). The
dedicated P4 composition now uses `maxDepth: 1` — the role is the first delegation
level, and a grandchild at depth 2 is still refused, so it cannot spawn further
subagents. The shared Product composition's `research-judgment-turn` is left
byte-identical because its identity is bound by the frozen B2 provenance; the P4
Runtime Adapter path uses the dedicated composition. Correcting the shared
composition later requires an explicit provenance re-baseline.

The dedicated composition now reads only the dedicated
`BYQ_MCP_READ_ONLY_URL`/`BYQ_MCP_READ_ONLY_TOKEN` (never the generic Product
`BYQ_MCP_URL`/`BYQ_MCP_TOKEN`), with no fallback. The trusted Runtime Adapter guard
`resolve_read_only_mcp_endpoint` fails closed if they are missing or collide with
the Product endpoint/credential. `carrier_readonly_mcp_probe.py` exits non-zero
unless every observed fact matches the bounded surface; the fail-able negative
control `carrier-readonly-mcp-negative-control.v1.json` points the same probe at
the full Product MCP and exits `1` (root sees all 82 tools), so the positive run is
not a self-written PASS label.

## Four-boundary closed loop: seam, entry and honest status (2026-09-23)

Inventory and minimal trusted entry are recorded in
`four-boundary-closed-loop-status.v1.json`. The Runtime Adapter exposes the named
internal route `POST /internal/runtime/research-judgment/{task_id}/run` (plus a
healthz probe). It is **authenticated** with a shared runtime service token
(`x-byq-runtime-judgment-token` == `BYQ_RUNTIME_JUDGMENT_TOKEN`, constant-time);
unset token is `503`, missing/forged token is `401` before any admission or model
turn, so path privacy/network isolation is not treated as authentication. The
trusted caller supplies the exact task id, the BYQ context headers and the
authoritative attempt binding (`x-byq-judgment-attempt` = persisted plan
`version:stage:iteration`). The adapter derives the **retry-stable** durable call
identity from `task_id + attempt`, so an admit whose result was lost reuses the
same admission instead of consuming a second model-call slot; it labels the
per-request value `adapter_invocation.id` and reports
`dsh_generation.status=not_available` rather than claiming a persisted runtime
generation. The authoritative task/owner/workspace/stage binding is the Backend
admission transaction (`_plan_task`) which runs before any model call. The driver
`run_journey.py` drives that route as boundary 2 and `step_runner.py` gained a
`judgment-context` command returning the trusted identity and the authoritative
attempt binding.

Exactly-once across interrupts: `admit` checks a **completed** call first and
replays its stored receipt (before any attempt/current-plan check), so a lost
response or a late retry after the plan advanced returns the original receipt and
runs **no** model turn; only then does it validate the attempt binding against the
current plan and create a call. A duplicate/concurrent request for an in-flight
admission does **not** terminate or mutate the live turn: with no verifiable
cross-process lease it fails closed with `409 research_judgment_in_progress`, so a
concurrent request cannot fence the original owner's stage to `needs_attention`.
A genuinely dead in-flight attempt therefore stays admitted (no auto-convergence)
and real cross-process resume is neither implemented nor claimed; a durable
attempt lease is required before safe abandonment, and the corresponding
fault-matrix row stays not-passed. The Backend rejects a stale/forged/future
`attempt_binding` for a new call before creating any stage call. A stage's
legitimate second model call requires model-supplied durable evidence, which the
bounded adapter forbids (`extract_closed_result` fails closed on any non-`none`
durable evidence) and the persona has no write tool for, so it is unreachable
here; a future continue-second-call flow would need an explicit durable attempt
discriminator.

Proven so far: the authenticated entry and its rejection cases (runtime-image unit
test), the DSH child role on the real carrier (`carrier-turn-runner.v1.json`) and
the read-only MCP surface (`read-only-mcp-subset.v1.json`). **The first REAL
isolated non-production four-boundary loop has now run**
(`isolated-four-boundary.v1.json`): Product API (Gateway conversation + grant) ->
authenticated Runtime Adapter judgment route -> real DSH child persona -> Backend
admit/result receipt, with negative controls (no/forged token 401, forged attempt
rejected, zero control stage calls). The isolated stack reuses the D15
runtime-qualification images with the current tree bind-mounted and adds a
dedicated read-only MCP service plus a keyless judgment-aware scripted provider
(`compose.p4-judgment.yml`, `judgment_scripted_provider.py`). The observed outcome
is the **normal** `strategy_draft_committed` advance: the plan reaches
`waiting_for_strategy_approval` with the approval bound to the exact
user-confirmed validated `strategy_version` (the trusted Backend plan-creation seam
now derives plan references from the persisted grant's confirmed validated
artifacts, re-checking validated status/digest/ambiguity and the grant's
revoke/expiry in the plan transaction). The model-visible bounded stage projection
is measured from the provider's real child request (710 bytes / 14 closed fields,
read-only `allowed_tools` subset, no forbidden raw key) and cross-checked against
the trusted Backend stage input; one real turn makes exactly 3 total provider calls
and a duplicate completed request replays the stored receipt with zero extra calls.

The slice then drives two real **deterministic handoffs**. First, the trusted seam
asks for the plan-command-bound strategy approval, the user decides it through the
Product API, and the Backend deterministically advances the plan to
`waiting_for_task_create_approval` with **zero model calls**; a duplicate decision
does not change the plan or duplicate events. Second, the trusted seam asks for the
plan-command-bound task-create approval, the user decides it, the plan advances to
`ready_to_create_backtest_task`, and the trusted deterministic `create_backtest_task`
action (exact persisted `signaljob_<hex>` identity) advances the plan to
`waiting_for_data`; an idempotent replay changes nothing. **Per-task provider
accounting** proves the whole real judgment turn made exactly 3 calls and the
deterministic handoffs made **zero** extra model calls; the cumulative provider
counter is shared across isolated runs and is never attributed to one task. The
signal job and its stock-pool snapshot in this run are honest isolated fixtures for
the deterministic action (a real signal-worker data-ready event is still not
driven). The remaining deterministic handoffs, the three-round journey and the
async-handoff fault matrix remain unexecuted, so the P4 verdict stays
`all_pass=false`.

## What was actually run (honest)

- **Component capture (executed):** `scripts/v091/continuation_p4/capture.py`
  against real isolated PostgreSQL and the real production seam, plus
  `services/backend/tests/test_research_plan_continuation.py` (6 tests) and the
  full P0-P3 backend suite (138 tests). This proves the grant→plan creation,
  bounded read-only dispatch, server-minted plan-command-bound approval, the
  deterministic READY-action CAS, the duplicate-event replay, and the route that
  advances the plan from a real human decision.
- **Partial runtime-isolated-stack probe (executed):**
  `run_p4_isolated.py` produced `isolated-four-boundary.v1.json` through the
  real Product API, authenticated Runtime Adapter, real DSH child persona and
  Backend admission/result boundary. It observed the strategy-draft handoff and
  the deterministic path through `waiting_for_data`; it did not execute the
  three-round journey or the complete fault matrix.
- **Full acceptance-matrix journey (driver provided, not executed):**
  `run_journey.py` reuses the committed v090 composite stack contract and is
  the driver whose output can satisfy the complete frozen matrix. No single run
  of that full driver is committed in P4-A. Therefore `observations.v1.json`
  remains the component baseline and `verdict.v1.json` remains
  `format_valid=true`, `all_pass=false`. The P4-B/P4-C/P4-D rows are not inferred
  from the partial probe and are never labelled PASS.

## Reproduce

```bash
# Observer self-check (fail-able; 21 defect-targeting controls all rejected).
python3 scripts/v091/continuation_p4/observer.py --selfcheck

# Governance/contract/matrix tests (architecture lane, no DB, no Docker).
python3 -m unittest tests.test_v091_continuation_p4

# Re-derive the committed component verdict.
python3 scripts/v091/continuation_p4/observer.py \
    --observations docs/evidence/adr-0085-p4-real-journey/observations.v1.json \
    --out docs/evidence/adr-0085-p4-real-journey/verdict.v1.json

# Real isolated stack (opt-in; requires Docker; no paid API, no production).
python3 scripts/v091/continuation_p4/run_journey.py \
    --scope byq-v091-continuation-local \
    --out docs/evidence/adr-0085-p4-real-journey/observations.v1.json
```

Component capture requires an isolated PostgreSQL and the backend container; see
`capture.py --help`.

## Non-claims

- No production deployment, version write, tag or release.
- No production canary; only an isolated non-production stack.
- No real-LLM research-quality semantic claim; the driver uses a keyless
  scripted provider.
- No Phase 100 resume and no 0.10 start.
- No second generic agent harness or session store; the model never sees raw
  bars/frame/date-index/signal/corporate-action rows or a full execution
  snapshot, and never chooses `next_action`, identity, approval, idempotency,
  routing or recovery state.
- Historical D15 snapshots are not rewritten; `R3_RESUME = NO`.
