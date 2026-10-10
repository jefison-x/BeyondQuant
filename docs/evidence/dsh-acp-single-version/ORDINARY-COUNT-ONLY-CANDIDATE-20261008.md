# Ordinary count-only qualification + candidate image identity (2026-10-08, session 2)

No push/merge/deploy/tag, no default promotion, no Phase advance. Production stack untouched.
Isolated project `byq-acpf6`. Historical failures and unknowns preserved.

## Candidate image identity (built this session, source recorded)
| service | image id | notes |
|---|---|---|
| gateway | `sha256:839e964aeea56ce5b1b50e8b36ed4c33e75a2789cd14e38d45cdcf5008059e08` | public session end-state projection baked in |
| runtime-adapter | `sha256:dcc04cde25b094adc579b1f8e311cd3f79dd36262f7b8a8d136a6bdc2ef57e36` | count-only overlay wiring |
| runtime-adapter (judgment fix) | `sha256:1c480fa8f32a44582ff102c13085a0a81b48e79a19ab4be4fdc44f4e5c17e9c3` | + `judgment_provider_resolution` (ADR-0105 route credential) |
| acp-product-runner | `sha256:55f79663683fe0eedd5b2ac8e1dd78bbc074ddb9e3193ed625f573563c7ff92f` | count-only validator + shipped `product_turn_request` |
| acp-product-runner (persona fix) | `sha256:189712b185808e297b3da4c8aab82430270e43185b52fe344540a456dab82fc1` | + root `byq_agent_run_start` persona instruction |
| backend | `sha256:dcabd9e671348cd5df187b25909e0434a66a528276739f4c0bb76d9c8654aa12` | unchanged |
| mcp | `sha256:3e5d6671a28594d73a646536be9f50282d8ea89a994ddd3c551069edfa427392` | unchanged |

Source hashes: `services/acp_product_runner/server.py`
`abc8992083bca202d4e66354f254fb1ea095cd409b62fcbdc2d3b2e6b6912f31`; runner Dockerfile
`6bab64e7050d02f7de29ddd09d274a9de10c5124ee35d66754924f826941d5f8`; gateway
`d2c467c681d9b8d48e1d6d2b5afbddbada4899246b7977f62f4fa53a5167f11f`; plugin
`892e42d6dcb982a6bcdfd6fc3d183b912a5909cae7dd3e4dd672de91236ee50a`; adapter
`27a65e7f795b3912d6ade2541b84160aabf5128bdbcd69ff1604aea0173db9d5`.
Pre-build backups: `byq-acpf6-*:prebuild-20261008`.

## Direct blockers found and fixed (proven, minimal)
1. **Missing contract module (packaging).** The runner image shipped only
   `packages/contracts/acp_product_slot.py`; the ADR-0106 count-only branch of
   `_validate_guard` imports `packages.contracts.product_turn_request`, so the
   runner raised `ModuleNotFoundError` (uncaught by the handler), closed the
   START socket unsigned, and the adapter saw `ProductSlotUnknown`. Fix: copy
   `product_turn_request.py` in `services/acp_product_runner/Dockerfile`.
2. **Pre/post-injection contract mismatch (validator).** The Adapter sends the
   PRE-injection overlay (no `journalPath`); it injects `journalPath` into the
   on-disk patch from the workspace-bound session home. The runner's count-only
   `_validate_guard` wrongly required `journalPath` in the frame. Fix: the runner
   accepts exactly `{guardMode, deadlineEpochMs, executionProfile, requestLimits}`
   and refuses any frame-supplied `journalPath` (set equality). No path, signed
   root, ownership, or workspace check was relaxed; the frame cannot choose the
   path. The runner cannot write the child-owned 0700 cwd, so the trusted Adapter
   remains the path writer.
   - Failed pre-fix attempts preserved (no provider dispatch): every failed START
     happened inside `_validate_start`/`_validate_guard`, before `_consume_scope`;
     neither runner wrote a scope tombstone and no `root-*` child was created.
   - Targeted offline tests: product-runner `_validate_guard` 2 passed (incl. the
     real pre-injection overlay and a `journalPath` refusal); adapter
     `test_product_turn_budget.py` 3 passed (asserts the 4-key pre-injection shape).

## Real ordinary Product turn — count hook PASS, but MCP business blocker found then fixed
- Conversation `conversation_deea48a9d71a408ba771181f263d119b`; runtime session
  `byq-session-e5435465980f494fa691412f7535a3fd`; trace
  `byq-trace-fc824a9e0b704f59b25996d5a9016a24`; run
  `80c3283c8c5d4217ae0c2c2ebe10aff0`; provider `opencode-go-chat` /
  `deepseek-v4.1-flash`.
- **Count-only tool journal** (`product-turn-tool-guard.v1`, no reservation):
  header identity `product-turn.v1` + exact limits; one real dispatch
  `{"phase":"tool","call":1,"tool_name":"mcp__byq__byq_research_get"}`.
- **Unresolved business blocker at that time (not a full turn PASS):** the MCP
  returned `acp_ingress_observation_unavailable`; the Backend logged
  `POST /internal/acp/tool-ingress-observe -> 409 Conflict`. Root cause (proven):
  ADR-0094 requires a **bound native AgentRun** before any Product business tool
  ingress (`_acp_tool_ingress_agent_run` -> `AgentConflict("ACP business tool
  ingress requires a bound native AgentRun")`). The ordinary ACP root never called
  `byq_agent_run_start`, and the ACP root persona did not instruct it (the F6 path
  does). DB for that root: no `agent_acp_native_agent_registrations` row and no
  `agent_runs` row.
- **Minimal fix (per Accepted ADR-0094; no ADR change):** the ACP Product root
  persona now instructs the Agent to first call `byq_agent_run_start` with
  `role_id "quant_orchestrator"` to bind the turn
  (`plugins/dsh-byq/profiles/acp-0.2.0-rc.2/byq-product.patch.yml`), and the
  product-runner Dockerfile's composition hash was updated. Runner image
  `sha256:189712b185808e297b3da4c8aab82430270e43185b52fe344540a456dab82fc1`.
- **Re-verified (new independent turn, no replay):** conversation
  `conversation_9077bf5a78614754926814732d8bd98b`, root
  `f90ef8c55a62451ab7b6fe3e750d1755`, run `f90ef8c5…`. Count-only journal shows
  two real dispatches: `byq_agent_run_start` then `byq_research_get`. DB confirms
  `agent_acp_native_agent_registrations`: origin `root`, depth `0`, status
  **`bound`**, `agent_run_58715cdda8dd46d1b5c1f9f544105b61`; ingress observation
  `byq_research_get` bound to that same run. The read then reached the Backend and
  returned `research_not_found` / HTTP 404 (placeholder task id). So the business
  blocker is resolved and the **call path is proven**; the read returned no real
  data, so this is **NOT** a real research-data read PASS.
- **Exact Backend terminal ACK (DB readback, not a substitute):** root
  `f90ef8c55a62451ab7b6fe3e750d1755` `status=completed`,
  `authority_status=closed`, `terminal_sequence=10`,
  `terminal_event_sha256=a847aba423bda93992d9881ead3c44afc492ba8b1fd1b8e7172b44b1db842f17`,
  `terminal_acp_ingress_sequence=1`,
  `terminal_acp_ingress_sha256=f747326d1f0e1e740a5f8432093bbbd4770ef6c360c50aaf37ea902e5a804194`,
  `terminal_unknown_claim_count=0`; signed runner cleanup receipt
  `cleanup:"proven"`, `code:0`, exact `root_run_id`.

## 17th-boundary keyless rc.2 DSH hook probe — PASS
`/tmp/opencode/acp-cand-build-20261008/count_only_hook_probe.py`, run in the
runtime-adapter rc.2 image with `--network none`. Verifies the DSH source commit
is the fixed `639ed015397290b3745d163aafe02ffee4aa3f84` (from `.git/HEAD`),
launches the exact official rc.2 DSH via the real `app.compat.dsh_acp._AcpProcess`,
loads the production `byq-continuation-budget.js` in count-only mode, and drives
one prompt with a scripted OpenAI-compatible provider and a local fake BYQ MCP:
`PROBE_RESULT {"admitted":16,"blocked":[{"blocked_reason":"BYQ_CONTINUATION_TOOL_LIMIT",
"phase":"blocked","tool_name":"mcp__byq__byq_research_get"}],
"header_has_reservation":false,"header_schema":"product-turn-tool-guard.v1",
"mcp_calls":16,"provider_requests":1}` -> exit 0. The 17th tool never reached MCP.

## Independently NOT_RUN
- **generic** (non-MCP) tool coverage in the rc.2 probe: NOT_RUN. The count-only
  guard has no allowlist (counts every `exec.name`), but a generic tool name was
  not independently observed.
- **child-Agent** coverage: NOT_RUN. Count-only mode installs no agent restriction;
  the untagged root-composition `tools/pre-execute` listener is process-wide, but a
  child Agent dispatch was not independently observed.
- Whole-suite re-run, hosted CI, push/PR/merge/deploy/tag, default promotion,
  release, Phase advance: NOT_RUN (out of scope).

## Dedicated 0097/0098 judgment entry — state and one proven fix
The entry is **not a stub**: `services/runtime-adapter/app/research_judgment_entry.py`
(`run_acp_judgment_root` / `recover_acp_judgment_root`) calls the full committed
lifecycle in `research_judgment_acp_turn.py` (`begin_root_once` -> provider proxy ->
dedicated root open -> `register_root_agent_once` -> prompt -> close -> settle).
The route `POST /internal/runtime/research-judgment/{task}/acp-root/run` gates on
`BYQ_JUDGMENT_ACP_LIFECYCLE_ENABLED == "1"` (opt-in, defaults protected).

**Proven defect (fixed).** The entry hardcoded `DEEPSEEK_API_KEY` while the stack
runs `opencode-go-chat` / `deepseek-v4.1-flash` (ADR-0105), so it always raised
"selected provider credential is unavailable" and failed closed. Fix: resolve the
credential by the exact provider route via the already-tested
`judgment_proxy_token_env`, exposed as the testable helper
`judgment_provider_resolution(environment)`. No ADR decision changed.

**Offline targeted tests** (in the runtime-adapter rc.2 image, `--network none`):
`test_research_judgment_api.py` 11 passed; `+ test_research_judgment_acp_turn.py`
31 passed (incl. the new `test_entry_provider_resolution_selects_the_selected_route_credential`).

**NOT_RUN (next, separate real acceptance).** The integrated real judgment chain
(combined MCP->real-Backend admission, exact terminal ACK readback, late/unknown/
cancel settlement, adapter restart recovery, two-user isolation) and a candidate
image containing this fix. The running adapter image `dcc04cde...` predates the
judgment fix, so no running-stack judgment acceptance is claimed.
