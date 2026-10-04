# ACP native session reuse reassessment

Date: 2026-10-04. Read-only design reassessment plus narrow keyless verification. No Product Phase change, implementation of the conflicting mapping, PR push, merge or deployment.

## Mapping and delta

| Boundary | Accepted ADR-0093/0094 branch | Completed-root reuse proposal |
| --- | --- | --- |
| Public conversation / Adapter session | Stable BYQ IDs and public transcript | Same; public transcript remains durable BYQ data |
| New root / native session | New BYQ root, process, contained cwd and ACP native session; bounded completed public rows are supplied as input | New BYQ root and process-scoped identity; reuse one native ID and cwd only after exact ACK and confirmed ACP close; send only new input |
| Context | DSH starts fresh and BYQ supplies completed public context | DSH restores native log; BYQ must remove that history injection on this path |
| Domain proof | Backend root, AgentRun, per-Agent MCP identity, ingress/claim/result, unknown handling and terminal ACK | All retained, with distinct Backend registration for each BYQ root even when the native root ID repeats |
| Restart | Same-root Backend authority transfer; no interrupted-prompt replay | Same until old root closes; a crash between ACK and ACP close needs explicit fence/drain proof before cross-root reuse |

The branch can reuse its ACP transport `session/resume`, per-Agent signed MCP client, discovery-only guard, Backend ingress and registration proof, frozen terminal cursor, Gateway-to-Adapter exact ACK, public API projection, model credential isolation and old-runtime rollback artifacts. The new-root `session/new`/new-cwd path, completed-public-history injection and one-root/native binding assumptions must be replaced together **only after ADR acceptance**. Do not remove the BYQ transcript, root IDs, AgentRun/Backend evidence, prompt idempotency, budgets, unknown-result protection, late-call fence or terminal ACK. The existing fresh-native path remains needed for unqualified cancellation/fault outcomes and rollback.

The current Adapter closes the DSH process in `_run_prompt` before publishing terminal evidence, while the proposal requires exact ACK followed by confirmed ACP `session/close` and process exit before cross-root resume. This ordering and its ACK-to-close crash window require an explicit implementation and test; existing process teardown alone is not the proposed close proof.

## Narrow evidence ledger

| Question | Verdict | Evidence and boundary |
| --- | --- | --- |
| Fixed official source and root-level close/resume with new MCP header | PASS, synthetic | Independent Tester reran `/tmp/byq-acp-root-reuse-check-20261004/probe.mts` against the fixed source; one tool call and four authenticated HTTP MCP requests under each synthetic bearer after bridge rebuild. Product plugin and Backend not involved. |
| Native context without duplicate first user input | PASS, synthetic | Same probe asserts first and second user inputs each occur once in second model request. No BYQ public history was appended. |
| Actual BYQ per-Agent root/child identity across cross-root reuse | NOT_RUN | Probe supplies ACP `mcpServers` directly; branch passes `mcpServers: []` and uses scoped signed clients. |
| Late old-root ingress after the new root opens | NOT_RUN, cross-root | Existing focused Backend tests prove close/transfer fences and late observe tombstones, but no delayed old scoped client crossed a reused native session. |
| Exact Backend terminal ACK permits next-root admission and missing ACK blocks it | NOT_RUN, cross-service | Existing focused Backend/Gateway/Adapter tests cover pieces; current qualification ledger explicitly marks full cross-service ACK NOT_RUN. |
| Parent ACP child tool updates | FAIL, fixed source | Earlier keyless probe found native child call/result, but parent ACP updates omitted them. This remains an unsuitable proof channel. |
| ADR-0094 MCP-to-Backend delegate proof on reused session | NOT_RUN | Existing isolated ingress/Backend components pass; the full resumed-session child identity and tool path has not run. |
| ADR-0085 judgment child tool catalog and ACP F6 route | FAIL, independent | Fixed-source child catalog exposes 13 instead of five intended tools; current ACP F6 remains locked to old SDK. Session reuse does not repair either. |
| User cancellation then reuse | NOT_RUN | Close/history and queued-input behavior cannot be inferred from a completed prompt. |
| Unknown business outcome then reuse | FAIL, blocked by contract | Pending/unknown ingress or claims must be reconciled by exact business ID before root close. No automatic replay or absent-result inference. |
| Fault before closure / ACK-to-close crash window | NOT_RUN | Requires separate fencing and native close/drain proof; same-root authority transfer evidence cannot prove cross-root reuse. |
| Real Product API/browser, paid model, exact-head CI/release | NOT_RUN | This reassessment makes no Product acceptance or deployment claim. |

Independent Reviewer recommends **deferring ACP default promotion** while treating completed-root reuse as a candidate amendment. See Proposed ADR-0096. The fixed current candidate's other recorded failures remain in [CURRENT-QUALIFICATION](CURRENT-QUALIFICATION.md); reuse does not supersede them.

Documentation verification: `git diff --check` passed. The branch's architecture unit test run completed 72 tests with two failures unrelated to these new documents: `test_phase63_product_plugins_are_generated_and_cannot_online_install` and `test_sdk_runtime_does_not_use_bundled_zero_config` inspect existing Runtime Adapter source and Dockerfile text. Full output is retained at `/tmp/byq-acp-reuse-architecture-tests.log`; these failures remain open and are not overwritten by the session probe.

Rollback remains the retained `0.1.5rc1` image/configuration recorded in [BASELINE](BASELINE.md). ACP native files are not an old-SDK migration format; use only verified completed public history after exact Backend closure.
