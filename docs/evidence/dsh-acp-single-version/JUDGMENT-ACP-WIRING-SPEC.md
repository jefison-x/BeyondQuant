# Judgment `/acp-root/run` wiring spec (ADR-0097/0098/0099)

Status: implementation spec for the next slice. The route stays an
unconditional `503 research_judgment_acp_lifecycle_unqualified` until the full
lifecycle and isolation gates pass; this spec does not enable it.

## Existing pieces (verified present)

- Boundary/identity: `research_judgment_boundary.py` (`require_service_token`,
  `trusted_context`, `require_attempt`, `derive_call_identity`).
- Durable journal: `research_judgment_acp_journal.AcpJudgmentJournal`
  (`record_request_start`, `record_begin`, `record_binding`,
  `record_provider_profile`, `mark_prompt_may_dispatch`,
  `reserve_provider_attempt`/`settle_provider_attempt`, `record_result_request`,
  `record_result_receipt`, `record_terminal_receipt`).
- Egress: `research_judgment_acp_provider_overlay.py` (private overlay),
  `research_judgment_acp_provider_profile.py`, `research_judgment_acp_provider_proxy.py`
  (single-route loopback proxy, killable worker), `research_judgment_acp_provider_routes.py`,
  `research_judgment_acp_provider_usage.py`, `research_judgment_acp_provider_worker.py`.
- Result capture: `research_judgment_acp_output.AcpJudgmentRootOutput`.
- Control: `research_judgment_acp_control.py` (`result_request`,
  `submit_result_once`, `close_result_root_once`, `settlement_request`,
  `submit_settlement_once`, `close_settled_root_once`, `exact_status`).
- Runner: `research_judgment_acp_runner_client.RunnerClient`/`RunnerSession`.
- Backend: `/internal/research-judgment/{task}/acp-root/{begin,register-agent,result,settle,status,cancel-intent}`.

## Missing piece

A trusted orchestrator (analogue of `research_judgment_entry.run_stage_judgment`
+ `research_judgment_turn.DshBoundedTurnRunner`, but for the dedicated ACP
**root** with the five read-only tools, no child). Planned module:
`research_judgment_acp_turn.py` + route wiring in `research_judgment_api.py`.

## Required sequence (fail-closed)

1. Route: `require_service_token` + `trusted_context` + `require_attempt` +
   exact `task_...` id; derive `call_identity` (never from the request).
2. `AcpJudgmentJournal.record_request_start(now_ms)` before Backend admission.
3. Backend `acp-root/begin` with the private runtime-authority bearer; persist
   `record_begin` (never cache `created`). Replayed begin without an empty
   journal fails closed.
4. Start the dedicated judgment ACP harness through the isolated judgment
   runner (`RunnerClient.start`), with the trusted composition
   `byq-research-judgment.patch.yml`, the derived per-root identity, and the
   private loopback provider proxy/overlay from the trusted resolution.
5. ACP `session/new` → `record_binding(native root)` → Backend
   `acp-root/register-agent` (fixed read-only AgentRun, stage-scoped ingress).
6. `mark_prompt_may_dispatch()` (fsync) BEFORE dispatch; build the root prompt
   for exactly the five read-only tools; run the prompt and feed observations to
   `AcpJudgmentRootOutput`.
7. On a completed closed result: `result_request` → `submit_result_once` →
   `record_result_request`/`record_result_receipt` → `close_result_root_once`
   → `record_terminal_receipt`. Require exact Backend status/terminal ACK.
8. Non-success settlement (ADR-0098): `settlement_request` with
   `durably_recorded_evidence` from the journal (dispatch marker, provider
   attempt/usage, cancellation, cleanup):
   - never dispatched → `never_dispatched` + `failed`;
   - cancelled before dispatch → `never_dispatched` + `cancelled`;
   - cancelled after dispatch → `cancelled_after_dispatch` + `cancelled`;
   - dispatched but unknown → `outcome_unknown` + `interrupted`, then close
     only after exact settlement; never manufacture a result, never replay.
9. Terminal: exact Backend terminal ACK before the route returns; a lost
   response is reconciled by exact status readback, not by re-posting a result.
10. Unknown/crash/restart: refuse replay from the durable `prompt_may_dispatch`
    fence; reconcile by exact ID.

## Isolation gates (must pass before the 503 is lifted)

- The dedicated judgment runner/network/secret/provider proxy are unreachable
  from ordinary DSH (ADR-0099/0100); the dedicated root uses the five read-only
  tools only, with no child (`tool-subagent` denied).
- Direct MCP/Backend denial for wrong audience/credential/root/task/call.
- Backend-owned begin/register/result/settle/close exactness; tool-argument
  admission bound to frozen stage evidence.
- Ordinary Product roots cannot obtain judgment credentials or the judgment
  entry.

## Evidence required

Keyless isolated probes for each settlement branch; real MCP→Backend chain;
cancellation pre/post dispatch; lost result/close response readback; restart
fence; five-tool catalog and forbidden-call denial; no child creation.
Independent Tester/Reviewer (ADR-0101) on the exact final head; exact-head CI;
merge gate. Only then remove the 503.
