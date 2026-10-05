# ADR-0096 — Reuse a DSH ACP session after a completed BYQ root

- Status: Accepted (2026-10-04). The maintainer explicitly accepted the simplified session design in the development chat. Implementation and qualification remain separate.
- Date: 2026-10-04
- Scope: fixed official `dsh-v0.2.0-rc.2` at `639ed015397290b3745d163aafe02ffee4aa3f84`, Product Runtime Adapter only. No Product Phase change.
- Amends the one-native-session-per-root mapping in Accepted ADR-0093 and ADR-0094 for the normally completed, exactly acknowledged path only. A fresh process per BYQ root, their business proof, same-root transfer, per-Agent identity and security gates remain in force.

## Evidence and limit

The keyless source probe at `/tmp/byq-acp-root-reuse-check-20261004/probe.mts` closed a completed ACP root, disposed its bridge, resumed the same native ID and canonical cwd in a new bridge with a different `mcpServers` HTTP bearer, then sent a second input. An independent Tester reran it against the fixed source: both synthetic tool calls used their own bearer, with four authenticated HTTP MCP requests in each bridge, and each user input appeared once in the restored model context. This establishes only a root-level official ACP transport capability. BYQ's candidate sends `mcpServers: []` and signs a distinct MCP client in each Agent scope; the probe did not exercise that Product composition, Backend terminal ACK, a delayed old-root request, a delegate, cancellation, unknown business result or crash recovery. See [narrow reassessment](../../evidence/dsh-acp-upgrade/SESSION-REUSE-REASSESSMENT.md).

The fixed source accepts `mcpServers` on `session/resume` for an inactive top-level session with the same canonical cwd. ACP close cancels current activity, waits for root idle, drains continuable descendants, flushes the native session, then disposes the Agent. A failed or ambiguous close is not proof that no child or old request remains. Backend's existing ACP registration key includes both BYQ root ID and native Agent session ID, so the schema can distinguish repeated native IDs across roots; that alone does not prove registration or late-call safety.

The present Adapter tears down the root-scoped process in `_run_prompt` before publishing a terminal event and receiving Backend ACK. It does not explicitly await ACP `session/close` on that normal path. The proposed ACK → close → resume ordering therefore needs a focused lifecycle change and crash-window proof, not just replacement of `session/new` with `session/resume`.

## Accepted narrow amendment

For a **normally completed** BYQ root only, the next reply may reuse the same DSH native ACP session and canonical contained cwd after all of these conditions are proven in order:

1. The old root's exact Backend terminal closure, frozen ingress cursor and business outcome checks have produced the exact Gateway-to-Adapter terminal ACK. Pending or unknown ingress/claims block progress; neither ACP completion nor a user-visible answer substitutes for this receipt.
2. ACP `session/close` succeeds, its continuable descendants are drained, native persistence is flushed, and the old DSH process exits or is authoritatively fenced. A close error or lost close response blocks cross-root reuse until this state is reconciled; Backend's old-root fence still rejects late calls.
3. The new root gets a fresh BYQ root ID and runtime generation; Backend root authority must be established before DSH tool dispatch. A fresh process carries only the new root's environment identity. `session/resume` uses the same native ID and cwd. Its Agent-scoped MCP clients and root/child AgentRun registrations must bind to the new root before any business tool call. A delayed old client remains an old-root request and is denied after closure.
4. The Adapter sends only the new user input to the resumed native session. It does not prepend BYQ completed public history to a native log already restored by DSH. BYQ still stores the durable public transcript and normalized Product API projection.

Keep the BYQ public conversation ID and private Adapter session ID stable, but store the native ID/cwd at that session boundary and retain exact per-root receipts. This is bounded transport correlation, not a second Agent session manager. Preserve domain authorization, idempotency, observation before execution, unknown-outcome reconciliation, budget limits, credential isolation, cancellation, terminal ACK and late-call fencing.

## Other outcomes are separate decisions

| Old root state | Proposed behavior before further qualification |
| --- | --- |
| User cancelled | Do not reuse the native session across roots merely because cancel returned. An already queued input or child result may remain in native history. Require a separate cancellation/close/history proof; until then use the Accepted ADR-0093 fresh-native path only after exact terminal ACK, or block if outcome is uncertain. Never replay the cancelled input. |
| Business result unknown | Block next root and native cross-root reuse until exact business-ID reconciliation and Backend closure. Do not classify a lost response as no execution. |
| Adapter/DSH process fault before old-root closure | Apply Accepted same-root Backend authority transfer only if its proof succeeds; do not replay the interrupted prompt. Otherwise retain revoked/unknown state and block new input. |
| Process fault after Backend ACK but before confirmed ACP close | Do not resume with a new root identity until old execution is fenced and native close/drain state is proven. If proof is unavailable, block reuse; a fresh native session may be considered only after old process/event generation fencing, under the existing public-history and exact business-root rules. |
| BYQ session ended | Reject later Product input regardless of ACP's resumable native file. |

## Required proof before changing the mapping

Run narrow, keyless fixed-source and isolated BYQ tests for: delayed old-root MCP ingress after new-root activation; root and spawned delegate identity before/after close-resume with the actual per-Agent plugin; Backend's distinct AgentRun binding for the same native root ID under two BYQ roots; actual tool observation/claim/result proof and frozen terminal cursor; a missing, mismatched or lost terminal ACK blocking the next reply; no duplicate native/public context. Keep cancellation, unknown-result and crash windows as separate fail-closed cases. A source probe alone is not Product integration acceptance. ADR-0094's child call evidence and ADR-0085's bounded delegate catalog require independent qualification. The ACP F6 continuation guard and Product API/browser checks also remain gates.

## Rollback and decision boundary

The existing `0.1.5rc1` image and tracked/protected configuration remain the exact rollback set. Its SDK cannot read an ACP native session: cutover or rollback must use only verified completed public BYQ history for a fresh old-runtime root, after exact business-root closure. No pending/unknown prompt or business action is replayed. Any durable binding-format change must be additive and explicitly checked for rollback; incompatible migration needs a separate accepted decision.

Acceptance authorizes a bounded design and implementation slice for normally completed roots, not ACP default promotion. ADR-0093/0094's fresh-native mapping remains authoritative for the other outcomes above. Current qualification blockers and all PR/release gates remain unchanged. The maintainer's later instruction to hold broad implementation, PR push, merge and deployment remains in force.
