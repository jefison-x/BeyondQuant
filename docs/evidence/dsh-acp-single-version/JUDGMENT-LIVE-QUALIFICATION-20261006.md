# Judgment `/acp-root/run` live qualification (2026-10-06)

Isolated candidate compose project `byq-acpcand` on this host. The running
production stack (`beyondquant-*`) was not modified. No volume was deleted.
The dedicated root was exercised end to end against the real provider.

## Real provider requests (honest accounting)

Across all diagnostic runs the durable journals record **20 real paid provider
attempts** (17 roots, some with several tool-use calls): input 11,204 tokens /
output 9,213 tokens. Every attempt is a single call recorded by the journal's
pre-dispatch fence; there was no automatic retry and no model switch. Usage is
the provider-reported value; no unknown-usage estimate is included.

## PASS (localized and fixed)

1. **Runner → judgment MCP**: with a correctly derived per-root bearer the
   runner's netns completes `initialize` + `tools/list` and receives exactly the
   five read-only tools (`byq_agent_context`, `byq_research_get`,
   `byq_research_stage_input_get`, `byq_backtest_task_get`,
   `byq_backtest_analysis_get`).
2. **MCP network alias (fixed)**: the `mcp-acp-judgment` service had **no
   network alias on the judgment network** (`Aliases: null`), so the runner
   could not resolve it (`EAI_AGAIN`); it could only be reached by IP. Added the
   alias on `byq_acp_judgment`.
3. **Runner child environment (fixed)**: the child env omitted
   `BYQ_DSH_RUNTIME_ROOT`, so `byq-acp-mcp-identity` failed with
   `BYQ_ACP_AGENT_IDENTITY_UNAVAILABLE` and never mounted the MCP client. The
   runner now passes its fixed runtime root to the child.
4. **Judgment profile (fixed)**: the `byq-acp-mcp-identity` insert lacked
   `config: {maxDepth: 1}` (present in the Product profile), so the plugin's
   exact-config check failed. Added it; children remain vetoed in judgment mode.
5. **Whole-root budget (fixed)**: the provider profile/journal set the
   whole-root totals to a single call's values, so the second (post-tool) call
   was rejected as "budget exhausted". Totals now scale by `max_calls`.
6. After these fixes the provider request carries the five BYQ tools as
   `mcp__byq__<name>` and the model issues **structured tool calls** (three
   completed provider calls in one turn), so tools are delivered and the route
   is tool-call compatible.

## New blocker (decision point)

- The turn now fails with `AcpTransportError: ACP update consumer failed`
  because `AcpJudgmentRootOutput` requires **exactly one** root
  `assistant.message`. A tool-use turn emits intermediate assistant text plus
  the final answer (separate messages), so the parser rejects the second
  message. This is a BYQ-side contract conflict between "exactly one closed
  root answer" and multi-message tool-use turns, not a route/model problem.
- Options: (a) let the parser accept the root's final completed answer among
  several root messages (still rejecting foreign sessions and non-JSON finals);
  or (b) require the prompt/DSH to suppress intermediate narration so exactly
  one answer is emitted. Deciding (a) relaxes a documented parser invariant and
  needs the maintainer's call.

## NOT_RUN

- Tool allow/deny instrumentation, zero-child proof, cancellation, lost-receipt,
  restart and unknown branches on a completed path.
- Real Gateway/Product API browser flow (internal call only).
- F6, single-version default switch, release chain.

No production switch, no release, no deployment. The candidate stack is left
running for continued acceptance.
