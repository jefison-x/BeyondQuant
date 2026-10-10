# Post-fix real signed child qualification — PARTIAL PASS / terminal FAIL

One authorized real read-only Product delegation was submitted to the new isolated candidate.
No second submission, model retry or model switch was made. OpenCode Go/deepseek-v4.1-flash;
ADR-0106 request/tool/time limits remain active. Provider-call count has not yet been independently
extracted; do not invent a count PASS. Native logs and DB evidence are preserved in existing volumes.

- Root: 0a00179537f54edab8cd92a9fc37af03.
- Trace: byq-trace-cbc240369d9b4620af472a4a186677c6.
- BYQ conversation: conversation_7188fe820439418fb73ac9b4dc3b452f.
- Native root: 885cd534-bee6-4521-b6cb-8bdbb8548b2b.
- Native child: c65660cb-e9f7-4804-96f8-913ab2436247, origin=subagent, depth=1,
  native parent equals native root.
- Child AgentRun: agent_run_9f58ede2555a475cae37c852e171f99b;
  parent AgentRun: agent_run_b586bb85508046b0b4cb33d2d125889f.

## Actual result

PASS (bounded): separate native root/child registrations and own AgentRuns; the child's real
byq_research_get was observed and settled under its own native identity/AgentRun, sequence 2.
No root impersonation was used for that read. This is actual Gateway/Product → signed BYQ MCP
→ Backend evidence, not fake MCP or a keyless probe.

FAIL: exact terminal ACK has NOT been obtained. Two byq_agent_authorize ingress records
(sequences 1 root / 3 child) are unknown; the two Backend authorize POSTs returned HTTP 403.
Backend close requests return 409 because `_require_acp_root_terminal_safe` refuses pending/unknown
ingress. The root remains active/active with no terminal sequence/hash. Model final text is NOT
proof of Backend settlement. No signed cleanup PASS is claimed for this unresolved root.

The old evidence RESULT.md remains FAIL; this new result does not erase it. The original probe
stopped polling after a stable first assistant message, which was intermediate text. Root caught
this and continued ONLY read-only polling of the same submitted root. `turn-evidence.json` is an
intermediate snapshot; `settled-transcript.json` contains the subsequent final public text but
its filename does NOT establish settlement. `root-terminal.json` records the actual active state.

## Narrow necessary follow-up

Audit the known authorization denial versus unknown-result classification. `server.ts` treats
non-read-only 4xx without a precise receipt as unknown; authorize performs policy checks and audit
inside a transaction. Generic 4xx classification must stay unknown. If adding a precise trusted
negative control receipt changes the accepted proof contract, propose that exact amendment first.
Do not auto-settle existing unknown rows from a model statement or HTTP status count, retry the
old business call, forge ACK, remove its fence, or start another root in this workspace.

No production/default/storage/release/tag/Phase/PR/merge/deploy change. No credentials or signed
headers are included. Actual dispatch budgets/cleanup and independent terminal review remain
unqualified for this attempt; no overall candidate qualification PASS.
