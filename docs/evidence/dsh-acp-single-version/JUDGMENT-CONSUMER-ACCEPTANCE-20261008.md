# ADR-0107 judgment consumer — real trigger acceptance + independent review (2026-10-08)

Scope: the accepted ADR-0107 minimal judgment-only consumer (service internal integration).
No push/merge/deploy/default/Phase/tag. Production untouched. Earlier fixtures preserved.

## Independent Reviewer (two rounds) — findings and fixes
Round 1 (consumer/claim): PASS on same-owner renew, expired-lease old-owner late intent,
two-worker single-owner, unknown-run reconcile-only, non-judgment refusal, no plan write,
additive DDL. Round 2 (post-fix) PASS on: atomic once dispatch-intent (`dispatch_intent_at IS
NULL`), unique per-instance consumer owner, real status readback, real service auth, business
gate before dispatch, no plan write/no auto-replay, additive/reversible DDL. Defects found and
fixed:
- **D1 (fixed):** global `/stages` used a fake tenant context; it now requires only the
  runtime-authority service bearer (tenant-agnostic, service-only).
- **D2 (fixed):** a reconcile-only with `dispatch_intent_exists` (root absent) hit `/acp-root/status`
  404 and crash-looped; `reconcile` now tolerates 404 as `{"status": "no_root_yet"}`.
- **D3 (fixed):** the worker now fails fast (exit 2) when `BYQ_RUNTIME_AUTHORITY_TOKEN` /
  `BYQ_RUNTIME_BOOT_ID` are unset, instead of defaulting to empty.

## Real consumer trigger acceptance (single target; normal selection + business gate)
Adapter `3ac2410b…`, Backend `8f6b5f31…`. Target task
`task_76e1c4c6dcc8448dbeceb7dfa35a43c3` (boot `05ea828d…`); the consumer ran `--once` with
`BYQ_JUDGMENT_TARGET_TASK` set so it never scanned other fixtures. Chain observed (all 200):
`GET /internal/research-judgment/stages` (service bearer) -> `GET .../{task}/dispatch`
(`plan_continuation_dispatch` business gate, `kind=judgment_turn`) -> `POST .../stage-claim`
(claimed) -> `POST .../stage-dispatch-intent` (intent once) -> Adapter
`POST .../acp-root/run` (real judgment) -> `POST .../acp-root/status` (read-only reconcile).
Status receipt: `binding_status=agent_bound`, native `715ec4d8…`, AgentRun
`agent_run_e4446b21…`, `stage_call_status=completed`, `stage_call_outcome=needs_attention`,
`result_receipt` `no_durable_progress`/`needs_attention`/`model_calls_used=1`/`proposal=null`;
`root_status=completed`, `root_authority_status=closed`, `terminal_sequence=2`,
`terminal_event_sha256=cca0207c56c1cf28ceaa695747b667d31533d7a99e6283a84e901ffa033e5032`,
`terminal_acp_ingress_sequence=2`, `terminal_unknown_claim_count=0`.
**Second run (same target):** `GET /stages` only — the task is no longer at a judgment stage
(plan moved to `needs_attention`), so the consumer selected nothing and **re-issued no model**.

This is a consumer-driven internal-integration PASS (not MCP/Product end-to-end). The
`no_durable_progress`/`proposal=null` outcome is a bounded judgment stop, not a real research
plan advance.

## Rollback (per corrected ADR-0107)
Disable the new consumer and roll back to the previous image/config; **preserve** the additive
`research_judgment_consumer_claims` table, its `dispatch_intent_*` columns and all unknown
evidence. Dropping the table is a separate destructive action requiring explicit authorization
(not granted). Schema before change recorded at
`/tmp/opencode/adr0107-backup-20261008/schema-before.sql`.

## Tests
Affected backend set: `test_judgment_consumer.py` (6) + `test_research_judgment_acp_root.py`
(+claim/intent/selection) + `test_research_plan_continuation.py` — 64 passed (test DB asserted
strictly `byq_domain_test`; credential URL never printed).

## NOT_RUN
Independent Tester re-verification of the consumer acceptance raw receipts; MCP/Product
end-to-end entry; generic/child coverage.

## Independent Tester (raw consumer evidence) — PASS
Read-only verification of the single target `task_76e1c4c6…`, root `6f12c288…`, call_identity
`byq-judgment-12f142704f075982cd52c0e1bd422a07`: all 10 checks PASS. `agent_runtime_turns`
`completed/closed`, `terminal_sequence=2`, `terminal_event_sha256=cca0207c…` (matches),
`terminal_acp_ingress_sequence=2`, `unknown_claim_count=0`; `research_judgment_acp_roots`
`agent_bound` (native `715ec4d8…`, AgentRun `agent_run_e4446b21…`); stage call
`completed/needs_attention`; role `research_judgment_readonly`; ingress tools
`byq_research_stage_input_get`+`byq_research_get` (root/0/settled); `consumer_claims` one row
with `dispatch_intent_at` present once; adapter journal `terminal_closed` (3 provider attempts,
all `opencode-go-chat` 200); cleanup `proven/0` for the root; **second run issued no model**
(one root/stage-call/intent/journal set); image correspondence backend `8f6b5f31…`, adapter
`3ac2410b…`.

## Independent Reviewer (consumer/backend/contracts diff) — PASS + gaps fixed
PASS on: intent once; all-tenant service auth (real constant-time bearer, `/stages`
tenant-agnostic and not browser-reachable); no-root-but-intent unknown (reconcile-only +
404-tolerant); no plan write/no auto-replay; closed contract; additive/reversible DDL. Gaps
addressed: added `test_dispatch_intent_is_refused_after_the_lease_expires` (expired-owner intent
refusal); the worker now fails fast when `BYQ_RUNTIME_JUDGMENT_TOKEN` is unset (not just the
authority token); the exact runtime boot is **fetched** (`/internal/runtime-authority/current`)
instead of pinned. Remaining recorded risks (not fixed): the Adapter route does not consult the
claim/intent (the fence is consumer-local); no per-task error isolation in `run_once`; no
automated down-migration.

## Worker runnable wiring + candidate identity
Added `workers/judgment/Dockerfile` and the candidate `judgment-consumer` service
(`compose.dsh-acp-rc2-candidate.yml`, existing per-domain worker pattern; candidate only, not a
production default). Image builds. **Historical note (updated 2026-10-08):** at that point only a
manual `--once` run had been done; the continuous background service had not been run. **Update:**
the continuous service was subsequently qualified with `BYQ_JUDGMENT_TARGET_TASK` bounding it to
the single target (11 polls, 0 re-sends, clean stop) — see the continuous-service section below.
The "continuous service scans all fixtures" concern is not a blocker.

## Formal Gateway/Product -> task/plan -> consumer -> ACP chain — NOT_RUN (specific boundary)
The Product/Gateway expose research **reads** only (`/research/tasks`, `/research/tasks/{id}/
execution-plan`, `/research/artifacts`, ...). No wired path creates a research **execution plan**
at a judgment stage: `ResearchExecutionPlanMixin.create_execution_plan`
(`services/backend/app/research_execution_plan.py:190`) has **no non-test caller**, and the
Backend `/v1/research/tasks` route creates a task without a plan. The ACP judgment fixtures
insert the plan directly. So the formal browser/Product chain to a judgment-stage plan cannot be
driven without adding a Product/domain capability (out of scope; no new feature). The
`no_durable_progress`/`proposal=null` outcome proves only bounded closure, not an effective
research-plan advance.

## NOT_RUN (unchanged)
MCP/Product end-to-end entry (boundary above); generic/child coverage (independent; atomic
sub-Agent recovery not promised).

## Continuous-service qualification (single target) — PASS
The candidate `judgment-consumer` service (built image) was run as a continuous container on the
`byq_product` network with `BYQ_JUDGMENT_TARGET_TASK` = the single target
`task_76e1c4c6…`. Over ~8s it polled `GET /internal/research-judgment/stages` 11 times and
issued **0** `POST .../acp-root/run` calls (no model re-issue), then stopped normally
(exit 0). The `research_judgment_consumer_claims` row is preserved (`claim_owner`,
`claim_attempt=1`, `dispatch_intent_at` present). Log:
`/tmp/opencode/acp-cand-build-20261008/judgment-consumer-service.log`.

## Official fixed rc.2 keyless hook probes (generic / child) — 2026-10-08
Run in the runtime-adapter rc.2 image (`--network none`), pinned commit `639ed015…`, count-only
overlay, scripted provider + fake MCP.
- **Generic tool hook coverage — PASS.** A generic (non-MCP) tool `list_mcp_resources` dispatched
  16 times was admitted and the 17th blocked with `BYQ_CONTINUATION_TOOL_LIMIT`, journal
  `product-turn-tool-guard.v1`, no reservation. (`/tmp/opencode/.../count_only_generic_probe.py`,
  exit 0.)
- **Child actual tool hook coverage — NOT_RUN.** A `child-scope-probe` helper was inserted into
  the rc.2 ACP composition (mirroring the strict SDK harness helper). The probe ran but the
  child produced **no observable tool dispatch** (`provider_requests` stayed 1; no second
  provider/child turn), so the process-wide hook's child coverage was not observed. The strict
  SDK harness has a working child probe; the rc.2 ACP composition/agent-API path differs. This
  is NOT_RUN, not a PASS.
- These keyless probes cover only the DSH tool-count hook; **MCP business attribution / exact
  Backend terminal ACK are NOT replaced** by them (that evidence is the real consumer run above).

## Child hook probe — official fixed-source API check (2026-10-08)
The child coverage NOT_RUN is because the probe did **not** actually start a child, not because
the official rc.2 DSH is unsupported. The inserted `child-scope-probe` helper failed to import
(DSH stderr: `child-scope-probe (file://…/child-scope-probe.mjs): failed to import`). The
fixed-source check shows the strict-SDK helper's modules are absent in the rc.2 DSH:
`@deepseek-ai/dsh-agent` exists, but `@deepseek-ai/dsh-brand` and `@deepseek-ai/dsh-llm` are not
top-level rc.2 packages (the rc.2 DSH uses `packages/{llm,session,subagent,...}`), so the helper's
`agents.create`/model-selection call path differs. The child hook coverage therefore stays
**NOT_RUN** (no observable child dispatch; `provider_requests` stayed 1). The old SDK harness is
**not** substituted. The count-only 17th-boundary and root-only hook are covered by the generic
probe (PASS) and the real consumer run; the shared-root-budget + per-child-identity evidence
requires a working rc.2 child probe (pending).

## Consumer image identity (image, not volume-mounted source)
- `judgment-consumer` image `sha256:5a19c7b284c093f7ca61963d0678118f3ae502928b79ce29db97a55a23d06423`.
- In-image `/app/worker.py` sha256 `cbda70bb7acf48fd7bc3590f64b0437e1cbcb555867bdf35eeca40bdc12116f8`
  **equals** the worktree `workers/judgment/worker.py`, so the built image includes the
  Reviewer-driven worker changes (D2 404-tolerant reconcile, D3 fail-fast, dynamic boot fetch,
  single-target filter).
- The continuous-service qualification ran this **image** (`docker run … byq-acpf6-judgment-consumer`,
  no source bind-mount), i.e. an image verification, not a volume-mounted-source verification.

## Child hook probe — official subagent tool attempt (2026-10-08, corrected)
Replaced the old-SDK helper with the official subagent tool (`@deepseek-ai/dsh-tool-subagent`,
`byq_delegate_market_research`, `provider:spawn`, `backgroundMode:continuable`); the scripted
provider emits a delegate call (`{"prompt":"probe child turn"}`) then tool calls. Result:
`{"admitted":16,"blocked":1(BYQ_CONTINUATION_TOOL_LIMIT),"header_schema":"product-turn-tool-guard.v1",
"provider_requests":2,"mcp_calls":15,"native_session_dirs":1}`.
- **Withdrawn -> NOT_PROVEN.** The earlier "shared 16 budget across root and child — PASS" is
  **withdrawn to NOT_PROVEN**. `provider_requests=2` does not prove the second request is a child
  (the root's next model call after the delegate result also produces a second provider request),
  and a session-directory count is not an Agent count. Without a trusted child nativeAgentID /
  parent / root link / actual tool-exec attribution, the cross-root-and-child shared-budget claim
  is not proven.
- **Root-only 17th boundary — PASS (retained).** The root-only probe (no delegate) admitted 16 and
  blocked the 17th with `BYQ_CONTINUATION_TOOL_LIMIT`.
- **Child nativeID — NOT_PROVEN / NOT_RUN.** No real child turn is inferred from the `spawn`
  config; the in-process/`spawn` child shares the root session storage and the
  background/continuable lifecycle was not awaited.
- No old-SDK substitution, no fabricated official event, no harness replacement/fork. MCP business
  attribution / exact Backend ACK remain the real consumer run (not this keyless probe) and cannot
  be replaced by the consumer's dedicated root.

## Child hook probe — official-event observation attempt (2026-10-08, NOT_PROVEN)
Per the correction, a keyless observation plugin (`byq-agent-observer`) was inserted into the
rc.2 ACP composition to capture the official `agent/created` and `tools/pre-execute` (with
`exec.agent`) identities and write them to a log — no fabricated events, no harness change, no
fork. It **failed to import** (`byq-agent-observer (file:///tmp/…/agent-observer.mjs): failed to
import`). The cause was **not determined**: this only shows the probe helper failed to load. It is
**not** evidence that the official rc.2 lacks `file://` observation plugins — the same candidate
loads `file:///opt/byq/runtime/byq-continuation-budget.js` successfully, so the failure is a
probe-load issue of the engineering helper, not an upstream capability gap. The stderr/exception
is preserved. So no official child-Agent event / `exec.agent` attribution was captured;
`agent_created_events=0`, `tool_events=0`. Consequently:
- **Child actual tool hook coverage — NOT_PROVEN** (no trusted child nativeAgentID / parent /
  root link / tool-exec attribution; a session-directory count is not an Agent count, and a
  second provider request is not child proof).
- **Root-only 17th boundary — PASS (retained).** Generic (`list_mcp_resources`) and root-only
  (`mcp__byq__byq_research_get`) probes: 16 admitted, 17th blocked `BYQ_CONTINUATION_TOOL_LIMIT`.
- **Gap:** the observation helper failed to load (cause unidentified) — a probe limitation, not an
  established upstream capability gap. Not painted PASS.
- MCP business attribution / exact Backend ACK remain the real consumer run and cannot be
  replaced by the consumer's dedicated root for ordinary delegated-child acceptance.

## Stop boundary
No further implementation. The Product plan-creation new entry remains **unimplemented / not
accepted** (behavior decision for the maintainer). The candidate is not a total PASS: root-only
and generic hook coverage PASS; child coverage NOT_PROVEN; formal Product chain NOT_RUN;
single-version default remains the SDK rollback. No push/merge/deploy/default/Phase/tag;
model-connection failure stops without retry; Draft A paused.


## Root clarification of the child-probe boundary — 2026-10-08
The observation helper failed to import in this particular probe. Its cause has not
been established. This is not proof that official rc.2 cannot load a file-based
observation plugin; the existing count-only guard itself loads from a file URL.
A second provider request does not establish a child turn or shared parent/child
budget coverage. Child tool-count coverage therefore remains **NOT_PROVEN**;
root and generic-tool boundary evidence remains scoped to those actual probes.
The candidate has no overall qualification PASS or default-upgrade authorization.
