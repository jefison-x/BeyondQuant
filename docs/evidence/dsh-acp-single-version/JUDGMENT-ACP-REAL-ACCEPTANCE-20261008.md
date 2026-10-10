# Dedicated 0097/0098 judgment entry — real internal-integration acceptance (2026-10-08)

Scope: **service internal integration** (Runtime Adapter internal route -> isolated judgment
runner -> isolated judgment MCP -> Backend), not the MCP/Product end-to-end entry. No push,
merge, deploy, tag, default promotion or Phase advance. Production stack untouched.

## Candidate image (isolated `byq-acpf6`)
- runtime-adapter `sha256:e3cc66759462e25dec0facc30800840e26e392202ed267043e35249054fd0246`
  (contains all four fixes below). gateway `839e964a…`, product-runner `189712b1…` unchanged.

## Four proven pre-dispatch defects fixed (each with keyless tests)
1. **session/new -32603 (overlay).** `private_provider_overlay` disabled `llm-deepseek`, but the
   pinned DSH `session/new` needs a registered adapter for the default provider. Fix: keep
   `llm-deepseek` ACTIVE (output-capped); the selected route is the only session model. No
   DeepSeek credential is present, so no unbudgeted DeepSeek call is possible.
2. **ADR-0098 masked never-dispatched settlement.** A failure after `JudgmentRunnerProcess`
   started left the caller's `transport` unset, so the runner fence was lost and `_settle`
   raised `never-dispatched settlement lacks exact no-dispatch evidence` (masking the original
   error). Fix: `IsolatedJudgmentAcpDriver.open` closes a started runner on failure and raises
   `JudgmentRootOpenFailed` carrying the proven fence; the orchestrator uses it so the root
   settles `never_dispatched` with `process_fence=stopped`. Unknown is never fabricated.
3. **Missing `user-agent`.** The judgment proxy dropped the client `user-agent`; the upstream
   rejected the request with an HTTP 403 and a bounded error body (`error code: 1010`) until a
   client User-Agent was present (observed: a client User-Agent returns 200). Fix:
   `admit_provider_request` forwards the client `user-agent` (values never stored/logged). The
   403 entity is recorded only as the upstream response; no external vendor is asserted.
4. **Missing `x-opencode-session` (OpenAPI routing).** The OpenCode Go route returns 400
   `MissingSessionID` without it. Fix: the overlay carries `x-opencode-session`, derived
   server-side from the root's own session identity (`uuid5(...)`); the proxy validates and
   forwards it. The legacy disk-patch path (unused by the ACP slot) omits it and still verifies.

## Real acceptance (one fresh task, no replay)
- Task `task_708860b9596c4142985167893f646cb3` (owner `acpchain-user`,
  workspace `workspace_475249…`), attempt `1:strategy_draft:1`, call_identity
  `byq-judgment-d6fb69a9ced6d4910c6d116e653d1703`; entry HTTP **200**.
- Root `b32e963461514aa3b4786d2771253bcc`; native root session
  `86d0606f-b651-4f72-9462-6253080e4e60`; AgentRun `agent_run_b23cd902059942019e5a3bcd137cc5e6`
  (role `research_judgment_readonly`).
- **Provider:** 2 attempts, both `opencode-go-chat` / `deepseek-v4.1-flash`, `status:200`,
  `phase:completed`, known usage (`actual_input_tokens` 2146/870, `actual_output_tokens`
  277/4561). One model call is committed (`model_calls_used:1`, `remaining:1`).
- **5 read-only tools:** judgment ingress observations `byq_research_stage_input_get` and
  `byq_research_get` (origin `root`, depth `0`, `settled`); no subagent, no write tool.
- **Result:** `research-judgment-result-receipt.v1` with `progress.status=stop`,
  `outcome=needs_attention`, `reason=no_durable_progress`, `proposal=null` (the model produced
  no durable progress -> plan moved to needs_attention). No fabricated evidence.
- **Exact Backend terminal ACK (DB readback):** root `status=completed`,
  `authority_status=closed`, `terminal_sequence=2`,
  `terminal_event_sha256=64d0882107e7b3bef969d22ea39ccde9efb4b40e6a8bc199d140a45c4f01db59`
  (equals the returned terminal receipt), `terminal_acp_ingress_sequence=2`,
  `terminal_unknown_claim_count=0`. `research_judgment_acp_roots.status=agent_bound`;
  `research_judgment_stage_calls.status=completed`.
- **Cleanup:** judgment runner signed receipt `cleanup:"proven"`, `code:0`, exact `root_run_id`.

## Preserved failed fixtures (read-only reconcile, no replay)
`task_306513…` (root `497e63ee…` `root_created`), `task_c95b1b70…`, `task_d0fb6b5c…`,
`task_4eb6183a…` — each with its journal under
`…/research-judgment-control/<task>/`; original pre-dispatch causes captured (session/new
-32603 / provider 400). These are preserved, not replayed.

## NOT_RUN
- Keyless cancel-unknown / permission windows at the entry boundary (targeted tests pending).
- Independent Tester/Reviewer on the actual diff and raw evidence.
- MCP/Product end-to-end entry (this is the internal integration path).

## Current-image binding (2026-10-08, adapter `91e50816…`)
The four fixes are unchanged between `e3cc6675…` (fixture9 completed run) and the current
`91e50816…` (only the composition identity file was corrected so the Adapter `/readyz` reports
`runtime_adapter=ready` / `release_identity=matched`; the judgment code is identical). A second
clean run on `91e50816…` (task `task_688378755ace42b1849e3f7cf3dbff54`, root
`2b2c2f301e2147018460730aa039e04f`, boot `352e10e4…`) reached the real provider (3 attempts,
all `opencode-go-chat`/`deepseek-v4.1-flash`, `status:200`, known usage) and **settled
`outcome_unknown`** (`needs_attention`, `terminal_outcome=interrupted`, proven
`process_fence=stopped`, `provider_attempt=may_have_started`, `unknown_claim_count=0`).
**Exact cause (read, not inferred from a model summary):** the DSH `turn/end` reason was
`completed` and the model returned the last message
`{"proposal": {...escalate...}, "durable_evidence": {"kind": "none"}}`, but
`validate_proposal` rejected it: `research proposal has forbidden caller routing/identity
fields: ['next_action']`. So `AcpJudgmentRootOutput.result` raised `ACP judgment root proposal
is invalid`, the result was not committed, and the root settled `outcome_unknown` fail-closed
(the invalid proposal produced no business action; the unknown is preserved). This is the
ADR-0085/0098 fail-closed path, not a provider/network failure. So the entry has been observed
on the current image to settle **both** a committed result (fixture9) and a proven
`outcome_unknown` (fixture10); the provider-outcome variance is real and preserved.


## Independent Reviewer pass (2026-10-08)
An independent read-only Reviewer examined the actual five-file diff. Verdicts: A (no
result/ACK bypass), B (the ACP slot always supplies a server-derived session id; the
`None` branch is unreachable there), C (`x-opencode-session` server-derived + validated),
D (`user-agent` forwarding cannot leak `x-byq-*`/credentials), E (`JudgmentRootOpenFailed`
fence is settlement-evidence only) — **all PASS** with file:line evidence. Two defects found:

1. **Stale disk-patch verifier (latent).** `dsh_acp.py::_verify_private_provider_patch`
   reconstructs the overlay with `provider_session_id=None`; it is not on the live ACP slot
   path (which uses `JudgmentRunnerProcess`/`overlay_b64`), so it is consistent today for the
   header-less disk patch. Noted, not changed (changing it would risk the legacy disk path).
2. **Handshake-failure leak (fixed).** `IsolatedJudgmentAcpDriver.open` kept
   `transport.start()` outside the guarded block, so an ACP `initialize` failure after the
   runner process was set left the transport leaked and the fence unset, reproducing the
   ADR-0098 masking. Fixed: `transport.start()` is now inside the guarded block, so a
   start/handshake failure also closes the runner and raises `JudgmentRootOpenFailed(fence=…)`.
   Keyless test added: `test_open_start_failure_is_wrapped_with_the_proven_fence`.

## Final candidate identity
runtime-adapter `sha256:3ac2410bc7103ad322bdf1a7c956532958fdd7a37eca5edeecb2e1d896d5ef8b`
(`/readyz` `runtime_adapter=ready`, `release_identity=matched`), acp-product-runner
`sha256:3da73530d1ec4caf720c9d27caefbec228b2dc405b3570ba9f12f001f6cd58b2`, gateway
`839e964a…`. All diagnostic hot-patches removed. Offline suites on the changed judgment
modules: 41 (turn+output), 98 (output+turn+overlay+routes), 136 (incl. proxy/assembly).

## Official call chain (ACP vs SDK)
No in-repo component dispatches either the SDK route (`/internal/runtime/research-judgment/
{task}/run`) or the ACP route (`/acp-root/run`); the Backend admits the stage call
(`begin_acp_judgment_root`) and the dispatch is performed by the external trusted
"runtime-adapter consumer" (`research_judgment.py` docstring). So the official chain does not
select ACP in-repo; the ACP entry is an opt-in internal route gated by
`BYQ_JUDGMENT_ACP_LIFECYCLE_ENABLED=1` (default disabled). No speculative wiring was added.

## Independent Tester (raw evidence) and Reviewer (fixes) — 2026-10-08
**Tester (read-only, DB/journals/receipts):**
- fixture9: PASS on every check — `agent_runtime_turns` `completed/closed`, `terminal_sequence=2`,
  `terminal_event_sha256=64d08821…db59`; `research_judgment_acp_roots.status=agent_bound` with the
  exact native session/AgentRun; `agent_runs.role_id=research_judgment_readonly`; ingress tools
  `byq_research_stage_input_get`+`byq_research_get` (root/0/settled); journal `terminal_closed` with
  2 `opencode-go-chat` 200 attempts; cleanup receipt `proven/0`.
- fixture10: root `interrupted/closed`, `terminal_sequence=2`, `terminal_event_sha256=253713a1…`;
  journal `prompt_may_have_dispatched` with 3 `opencode-go-chat` 200 attempts; cleanup `proven/0`.
- **Image correspondence — cannot confirm.** Neither fixture is bound to the current image
  `3ac2410b…`: fixture9's exact adapter digest is not recorded anywhere; fixture10 ran on
  `91e50816…` (absent locally). So the fixture evidence was produced by earlier adapter images.
- Note: fixture9's journal appears under both mounted volume paths (`workspace_475249…` and
  `workspace_c1b071…`) with identical content; the DB binds it to `workspace_475249…`.

**Reviewer (fixes):**
- Handshake-failure fix: **PASS** (start failure caught; closed exactly once; `close()` failure →
  `fence=None` with the original cause preserved; the fence never overrides the journal-derived
  `dispatched` decision; an open failure is always pre-dispatch → `never_dispatched`).
- Latent disk verifier (`_verify_private_provider_patch`): **no live path** sets
  `harness.private_provider_patch` (only tests); the bounded risk is a **fail-closed denial**
  (rejects a legitimate overlay), not a security bypass. No fix required now; if a live path is
  introduced, thread the derived `provider_session_id` + `max_output_tokens` into the verifier.

**Current-image binding (fixture11, adapter `3ac2410b…`):** task
`task_fe4c8b5a17124755853398909395dde4`, root `5b4d298b018943e6893c57d73fbe692c`, boot
`05ea828d…`. Entry HTTP 200, settled `outcome_unknown` (`needs_attention`, proven
`process_fence=stopped`, `unknown_claim_count=0`); exact Backend terminal ACK
`interrupted/closed`, `terminal_sequence=2`,
`terminal_event_sha256=d1009b81c6bbe939adb1e83abca7f4c8bcf0d432ee7e82b76155530a5884c210`,
`terminal_acp_ingress_sequence=2`; `research_judgment_acp_roots.status=agent_bound` (native
`f1d8088f…`, AgentRun `agent_run_c37b81b…`); stage_call `settled`; ingress tools
`byq_research_stage_input_get`+`byq_research_get` (root/0/settled). So the **outcome_unknown**
path is bound to the current image; the committed-result path (fixture9) was observed on an
earlier adapter image with identical judgment code (only the identity file and the handshake
guard differ).

## Scoped call-chain audit (MCP research -> Backend plan/stage -> consumer -> Adapter route)
- MCP research tools create/read BYQ research objects; `research_execution_plans` holds the
  per-task plan/stage; `ResearchPlanContinuationMixin.plan_continuation_dispatch`
  (`services/backend/app/research_plan_continuation.py:158`) is READ-ONLY and returns the next
  step, including `{"kind": "judgment_turn", ...}`.
- Backend admission routes exist: `/internal/research-judgment/{task}/admit` →
  `admit_research_stage_call` (`main.py:851`); `/internal/research-judgment/{task}/acp-root/begin`
  → `begin_acp_judgment_root` (`main.py:881`).
- Adapter judgment routes exist: `/internal/runtime/research-judgment/{task}/run` (SDK) and
  `.../acp-root/run` (ACP) — both in `services/runtime-adapter/app/research_judgment_api.py`.
- **Correction (2026-10-08):** the Backend `/admit` route DOES have an in-repo caller —
  `services/runtime-adapter/app/research_judgment.py:128` (`admit_research_judgment_turn`) is
  called by `run_bounded_research_judgment` (`:174`), which the Adapter SDK route `/run` invokes
  (`research_judgment_api.py:101`). So the **SDK bounded judgment lifecycle is a complete
  in-repo entry** (route -> admit -> turn -> result); it must not be described as caller-less.
- **What is genuinely missing:** an in-repo **scheduling** caller that decides *when* to invoke
  the judgment route. `plan_continuation_dispatch` (READ-ONLY, returns `kind:"judgment_turn"`)
  has no in-repo caller, and no in-repo component calls either Adapter judgment route (`/run` SDK
  or `/acp-root/run` ACP). The Backend/Gateway never call the Adapter judgment routes (the
  Gateway only calls runtime-session routes). So the **trusted plan-continuation
  consumer/dispatcher is the missing seam**: it would read the plan's next step and, for a
  `judgment_turn`, invoke the Adapter judgment route with the trusted context.
- The docstring term "runtime-adapter consumer" is conceptual; no in-repo consumer is asserted.
  The dispatch **trigger/scheduling** (what causes the judgment turn to run) is not defined by
  ADR-0097/0098, which cover the root lifecycle/settlement, not the dispatch trigger. Adding it
  is therefore a scheduling decision, not a minimal wiring of an existing seam.

## Final-image success-path acceptance (fixture12, adapter `3ac2410b…`) — 2026-10-08
Resolves the Tester's "committed-result not bound to the final image" gap. One attempt, no retry.
- Task `task_b1cdd9ffcf35410295581e743e00ef62`, attempt `1:strategy_draft:1`, call_identity
  `byq-judgment-814d5e5babecf81f12df3d95de27f5c9`, root `e1654d96c9ab4eb2aeeac8268229be86`,
  boot `05ea828d…`. Entry HTTP **200**, `status:"completed"`.
- `research-judgment-result-receipt.v1` `progress.reason=no_durable_progress`,
  `outcome=needs_attention`, `model_calls_used=1`, `proposal=null`; `agent-run-lifecycle-receipt.v1`
  `sequence=2`, `event_sha256=986ec692362ecf14591152f8be2dadbe88047e3f2ab6e3eac310ffea49674e5d`.
- Exact Backend ACK (DB): root `completed/closed`, `terminal_sequence=2`,
  `terminal_event_sha256=986ec692…` (equals the returned terminal),
  `terminal_acp_ingress_sequence=2`, `terminal_unknown_claim_count=0`;
  `research_judgment_acp_roots.status=agent_bound` (native `f174f5f5…`, AgentRun
  `agent_run_d36119ff…`); `agent_runs.role_id=research_judgment_readonly`, `status=completed`;
  `research_judgment_stage_calls.status=completed`.
- Ingress tools `byq_research_stage_input_get`+`byq_research_get` (root/0/settled); journal
  `terminal_closed` with 3 `opencode-go-chat` 200 attempts (known usage); cleanup `proven/0`.

So both judgment outcome paths are now bound to the current image `3ac2410b…`: committed result
(fixture12) and proven `outcome_unknown` (fixture11). All earlier fixtures/unknowns preserved;
no task/attempt/call replayed.
