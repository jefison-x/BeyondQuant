# Judgment `/acp-root/run` live qualification (2026-10-06)

Isolated candidate compose project `byq-acpcand` on this host. The running
production stack (`beyondquant-*`) was not modified. No volume was deleted.
The dedicated root was exercised end to end against the real provider.

## Real provider requests (honest accounting)

Across all diagnostic runs the durable journals record **35 real paid provider
attempts** (roots with several tool-use calls): input 17,652 tokens / output
15,320 tokens. Every attempt is a single call recorded by the journal's
pre-dispatch fence; there was no automatic retry and no model switch. Usage is
the provider-reported value; no unknown-usage estimate is included. The count is
reconciled request by request from the durable journals, not estimated.

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

## Parser contract (maintainer chose option a; bounded)

`AcpJudgmentRootOutput` now accepts intermediate root `assistant.message`
observations within one dedicated root turn and validates the **last complete**
message, only after a nominally completed turn. Preserved gates:

- exact root/session/turn ownership; foreign sessions and child/session outputs
  are rejected;
- messages are the official assembled complete messages, never a lone streaming
  chunk (aggregation tested);
- the final answer must satisfy the existing strict JSON/schema/field/size rules;
- an invalid final answer fails directly with no fallback to an earlier valid
  JSON;
- cancellation, disconnect, missing completion evidence and post-terminal
  messages never become a success;
- intermediate messages are process evidence only; no early result or business
  action;
- the exact Backend terminal ACK and cleanup proof remain required.

## PASS — full committed lifecycle

One real turn returned the exact closed JSON
(`{"proposal": null, "durable_evidence": {"kind": "none"}}`); the lifecycle
submitted the result, closed the root and received the exact terminal ACK:
`agent-run-lifecycle-receipt.v1`, sequence 2, with the root and event hash. When
the model instead returned non-JSON narration the lifecycle correctly settled
`outcome_unknown` (fail-closed), confirming the no-fallback rule.

## NOT_RUN

- Tool allow/deny instrumentation, zero-child proof, cancellation, lost-receipt,
  restart and unknown branches on a completed path.
- Real Gateway/Product API browser flow (internal call only).
- F6, single-version default switch, release chain.

No production switch, no release, no deployment. The candidate stack is left
running for continued acceptance.
