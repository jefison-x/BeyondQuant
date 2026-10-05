# Judgment `/acp-root/run` live qualification (2026-10-06)

Isolated candidate compose project `byq-acpcand` on this host. The running
production stack (`beyondquant-*`) was not modified, restarted or re-pointed.
No volume was deleted. One real paid DeepSeek call was made; no retry and no
model switch.

## Environment

- Candidate services healthy: `postgres`, `backend`, `mcp`,
  `mcp-acp-judgment`, `acp-product-runner`, `acp-judgment-runner`,
  `runtime-adapter`, `gateway` (avoids the production port conflict via a
  candidate-only bind). The adapter binds the judgment-network address
  `172.27.0.250` so the runner's DSH child can reach the private provider proxy.
- Synthetic persistent task+plan at `strategy_draft` created through the
  current Backend store (owner `admin`, admin personal workspace).
- Route wiring added with an opt-in gate (`BYQ_JUDGMENT_ACP_LIFECYCLE_ENABLED`);
  the default `/acp-root/run` behavior without the flag remains
  `503 research_judgment_acp_lifecycle_unqualified`.
- Runtime authority transfer performed for the exact current Adapter boot.

## PASS

- Candidate stack build/boot and identity: postgres/backend/mcp/judgment-runner
  healthy; `healthz` reports `authenticated:true`.
- Budget cap: the private overlay now sets the pinned `llm-deepseek`
  `maxTokens` to the stage budget, so the root's declared output is `8192`
  instead of the model's `256000`; the proxy budget gate accepts the request.
- Real paid provider call succeeded: `deepseek-official` `/anthropic/v1/messages`
  returned HTTP 200 with real usage (e.g. input 609 / output 383 tokens; a second
  run 327). One provider attempt, no retry, no model switch.
- Fail-closed terminal: when the root did not return a completed closed result,
  the lifecycle settled `outcome_unknown`/`interrupted` with an exact Backend
  settlement receipt and terminal ACK, process fence `stopped`.

## FAIL / blocker (decision point)

- The provider request carried **`tools=None`**: the five read-only judgment
  tools were not mounted/sent to the model. With no declared tools, the model
  emitted DeepSeek DSML tool-call markup as plain assistant text instead of a
  native `tool_use`, so `AcpJudgmentRootOutput` correctly rejected the result and
  the call settled unknown. The captured assistant text began
  `I'll gather the bounded read-only context ... <|DSML| calls> <|DSML| invoke
  name="byq_agent_context"> ...`.
- Consequence: the dedicated root cannot exercise the five read-only tools yet,
  so no completed judgment result is produced. The fail-closed behavior is
  correct; the tool-mount path is the gap.
- Unresolved cause (needs a decision): the judgment MCP client
  (`mcp-acp-judgment:8301/mcp/v1`, via the identity plugin) does not appear to
  attach its tool catalog to the ACP root in this composition. Open options:
  (a) fix the identity-plugin MCP attach / composition so the five tools are
  registered on the root; (b) verify the MCP endpoint returns the five tools for
  the derived per-root bearer; (c) treat the `deepseek-v4-flash` Anthropic
  Messages DSML behavior as a route incompatibility and select a route/model
  that returns native tool calls.

## NOT_RUN

- Tool allow/deny, zero-child, cancellation, lost-receipt, restart and unknown
  branches on a completed path.
- Real Gateway/Product API browser flow (internal call only so far).
- F6, single-version default switch, release chain.

No production switch, no release, no deployment.
