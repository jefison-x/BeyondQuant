# ACP global MCP fallback: keyless qualification

- Date: 2026-10-04
- Fixed official source: `dsh-v0.2.0-rc.2`, commit
  `639ed015397290b3745d163aafe02ffee4aa3f84`.
- Scope: official ACP bridge, AgentLoop, spawned child and official MCP client;
  local mock LLM/MCP only. No paid model, BYQ business API or deployment change.

## Results

| Gate | Result | Exact observation |
| --- | --- | --- |
| Per-Agent scoped MCP transport | PASS, separate intact-client probe | `/tmp/byq-acp-all-scoped-driver.mts` kept both scoped clients active. Root and child each called mock `ping` once with different scoped bearer headers. Parent ACP stream still carried zero child tool updates. Every observed bootstrap/root/child header and the missing child ACP update were asserted. |
| Missing child scoped client, unguarded ingress | PASS, negative control | The child client was disposed after activation and before the child prompt. The child tool still resolved through the global MCP client. The final HTTP request had the bootstrap bearer, the mock business handler ran, and the native child tool result succeeded. |
| Missing child scoped client, discovery-only ingress | PASS, mock guard | The same fallback request reached mock MCP with the bootstrap bearer and was denied before its protected action. The protected mock action ran only once, for the root; the child tool result was an error. |
| Real HTTP scoped-endpoint disconnect | PASS, limited | `/tmp/byq-acp-disconnect-driver.mts` closed the child-only MCP endpoint after the scoped client had connected. A subsequent child tool call returned an error through the retained scoped registration; the global MCP endpoint received no child/bootstrap request. This exercises endpoint loss, not transport-close notification or reconnect exhaustion. |
| Real scoped-client reconnect exhaustion | NOT_RUN | A separate stdio crash probe under `/tmp/byq-acp-stdio-disconnect-driver.mts` failed during initial scoped-client connection, before the intended crash/reconnect phase, so it supplies no reconnect verdict. The explicit-disposal fallback probe remains the proven missing-registration case. |
| BYQ MCP discovery-only credential and signed Agent identity | NOT_RUN | The production MCP ingress still accepts its current bearer; the tested denial exists only in the local fixture. |
| Backend child registration, call proof, unknown outcome and restart receipts | NOT_RUN | No isolated Backend was included in this probe. |
| Real-model retry/stop and budget protection after fallback denial | NOT_RUN | The local scripted model ended after receiving the tool error. |

The three earlier runnable probe drivers are `/tmp/byq-acp-all-scoped-driver.mts`,
`/tmp/byq-acp-fallback-driver.mts` and
`/tmp/byq-acp-fallback-guard-driver.mts`. Each runs under the fixed source
checkout with `node --import tsx/esm`. The guard fixture is under
`/tmp/byq-acp-probes/` with a symlink only to the checkout's dependency
directory; no official source file is needed for a rerun. The independent
Tester identified an earlier deleted-fixture import and an unstated separate
intact-client probe; both were corrected before all three drivers passed again
with exact headers and zero child ACP updates asserted. The fixed request
sequence and counts support the narrow attribution; no server-side call-ID
mapping was proved.

The HTTP disconnect probe additionally observed three child-scoped HTTP
requests at initial registration and no child tool execution there after
shutdown. The global endpoint recorded the root's one protected `ping` only,
no denied fallback request, and the native child `tool/result` had
`isError=true`. This is a fail-closed outcome for that HTTP loss timing, but
does not remove the proven fallback path after scoped registration disappears.
The independent Tester found that the first driver only printed these values.
The driver now asserts every stated request header, protected/denied call count,
child event and ACP update count; the corrected driver passed in one keyless
rerun. The Tester did not execute the probe independently.

The first loopback attempt ran under a sandbox that disallowed binding
`127.0.0.1` and stopped before any request. Approved isolated loopback runs
passed. An earlier temporary guarded fixture was placed in the clean official
source checkout only for module resolution, then removed; `git status --short`
was empty and HEAD remained the fixed commit afterward.

These results show why the global client must be discovery-only in the final
Product composition. They do not qualify the proposed ADR-0094 protocol or
authorize ACP promotion, PR, merge or deployment.
