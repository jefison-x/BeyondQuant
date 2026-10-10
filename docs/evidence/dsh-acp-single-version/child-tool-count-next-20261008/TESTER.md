# Independent Tester — child tool-count bounded PASS (raw + fixed source)

Read-only. No probe re-run, no network/model. Candidate image
`byq-acpf6-runtime-adapter:latest` = `sha256:c324ef803409c0a38e9c34b68bcc847942614eb1e907d13ac2b0a30952b1b0b9`;
DSH source commit `639ed015397290b3745d163aafe02ffee4aa3f84`.

| # | Check | Verdict | Evidence |
|---|---|---|---|
| 1 | Run 1 real delegate error | PASS | `diagnostic-run/probe-result.json` `tool_role_messages[0].content` = `Error: tools.restrict() names unknown global tools "mcp__byq__byq_market_daily", …`; `delegate_in_catalog=true`; `mcp_calls=15` |
| 2 | Run 2 counts/ids | PASS | `raw/probe-result.json`: `agent_created_count=2`; `child_agent_ids=["0b44497d-89a4-45c9-9833-ea841b0c87d3"]`; `child_tool_event_count=15`; `tool_agent_ids=[child, root 1855c433…]`; `mcp_calls=15` (all `byq_research_get`); `journal_admitted=16`; 1 blocked `BYQ_CONTINUATION_TOOL_LIMIT` |
| 3 | Parent/root relationship | PASS | child session header `origin:"subagent"`, `parentSession:"1855c433…"`, `delegationDepth:1` in `raw/probe-result.json` and `raw/observer.jsonl` |
| 4 | Guard journal | PASS | `raw/guard-journal.jsonl`: schema `product-turn-tool-guard.v1` no reservation; 1 × `byq_delegate_market_research` + 15 × `mcp__byq__byq_research_get`; 1 blocked |
| 5 | PASS needs real child + MCP | PASS | `probe_delegate_capture.py` `PROBE_OK` requires `child_agent_ids>=1` AND `child_tool_event_count>=1` AND `mcp_calls>=1` (plus 16/1); Run 1 fails with empty child ids |
| 6 | Fake MCP set == allow minus globals | PASS | 15 advertised = product-patch `delegate-market-research.toolFilter.allow` (16 entries) minus DSH-native `web_search`; no missing/extra |
| 7 | No secrets in tree | PASS | only env var names + synthetic placeholders (`probe-discovery-token`, `probe-signing-key`, `synthetic-only`); no key/token/password/signed START |
| 8 | Observer samples minimal | PASS | `raw/observer.jsonl` only `event/agentId/source/tool/sessionHeader`; observer `hint()` copies primitives + `origin`/`parentSession` only |
| 9 | Fixed-source schema validity | PASS | `tool-subagent`: `description` and `prompt` required, `run_in_background` optional; Run 1 args schema-valid; abort was `tools.restrict` unknown globals, not schema |

**Verdict: bounded PASS warranted** for the child tool-count proof within the stated boundaries.
Not an overall single-version qualification / default upgrade. Discrepancies: none on counts; the
"16/17 boundary" label was clarified (1 root delegate + 15 of 17 requested child MCP admitted; 16th
child blocked; 17th never reached). Minor provenance note: the diagnostic run used the probe's
initial 8-tool fake-MCP set (catalog proves it); only the fixed source is persisted.
