# ADR-0094 — Product ACP delegate MCP scope and restart evidence

- Status: Proposed; maintainer decision required before Product ACP promotion.
- Date: 2026-10-04
- Scope: amendment to the MCP mount and recovery proof in Accepted ADR-0093 for the fixed official `dsh-v0.2.0-rc.2` candidate only.

## New evidence after ADR-0093 acceptance

An independent keyless test against official commit `639ed015397290b3745d163aafe02ffee4aa3f84` created two ACP sessions with separate mock BYQ MCP bearer headers. The root session setup reached only its own mock server, but `provider: spawn` Product delegate children saw no BYQ tools. Applying the existing exact delegate `toolFilter` failed during child setup because `mcp__byq__ping` was not a global tool. The candidate ACP mounts `mcpServers` in the root Agent scope; the official in-process child gets a distinct Agent scope. Thus ADR-0093's per-session ACP mount does not preserve the Product delegate contract. No model credential or business call was used in this test.

The first implementation review also found two fail-closed restart windows: an observed domain call not yet drained to Backend has no durable Adapter evidence row after crash; and Backend may close a root before Adapter persists its terminal ACK, leaving the stored binding marked for transfer while Backend correctly refuses to transfer a closed root. Neither window permits guessing that a business call did not happen. They block general restart-resume qualification until an exact reconciliation design is proved.

The fixed ACP source filters notifications to its owned root session. In-process child sessions may therefore execute a domain tool without sending the child's `tool/call` and `tool/result` update to the Adapter. Since BYQ requires exact observed call evidence before consequential Backend execution, child tool visibility alone would not qualify the process-level option. The keyless test must also prove the full child call/result evidence path; otherwise the design remains blocked.

## Initial bounded design, superseded by later evidence

1. Retain one DSH ACP **process and native session per BYQ root**. Give that process a single BYQ MCP client with the exact root identity in its environment-backed Cordis composition. ACP `session/new` and `session/resume` pass no duplicate BYQ `mcpServers` entry. The process-level client must be visible to both root and in-process delegate Agent scopes, with each role's existing persona, tool filter and depth bound. A new root gets a new process and identity; same-root restart gets a new process only after Backend's exact authority transfer. This changes ADR-0093's MCP mount location, not its one-root-one-native-session mapping or its Backend authority contract.
2. Prove that only one effective BYQ MCP tool namespace exists, that root and child requests carry the exact same root/boot/owner/workspace/actor/trace/session identity, and that two users and two successive roots never share the client. The ACP update stream must expose each child domain call and result with a stable call ID and ordering sufficient for BYQ's existing evidence and terminal ACK contracts. Use a keyless mock MCP fixture before Product integration. The process-level configuration must fail closed on a missing or invalid root identity and never grant Engineering tools.
3. Persist only bounded, exact control receipts needed to distinguish an active transferred root from an already closed root across Adapter restart. Gateway must compare a stored terminal receipt with Backend's scoped terminal sequence and digest before treating it as acknowledged. Undrained domain-call evidence remains blocked unless an exact Backend receipt and cursor can be reconstructed; unknown claims remain unknown. Do not persist private conversation history or replay an interrupted prompt.
4. Requalify the reservation-specific DSH pre-dispatch budget guard and model route catalog under this final composition. Preserve the old `0.1.5rc1` image/config as rollback; do not interpret its native files as ACP state.

An independent second keyless probe of the exact official ACP bridge used two separate DSH processes with process-global root-scoped MCP configuration. Root and spawned child in each process saw the BYQ tool, the child's exact `toolFilter` succeeded, and the two processes sent only their own synthetic bearer headers. **That narrow mount/access result is PASS.** The same probe found child `tool/call` and `tool/result` with a stable child call ID in the native child log, but **no corresponding child `session/update` in the parent ACP stream**. Thus BYQ's required pre-execution domain-call evidence remains FAIL. Process-level MCP mounting alone cannot qualify the Product upgrade.

The remaining design options require a separately accepted, concrete proof contract: obtain official DSH ACP child event projection in a fixed future candidate (without forking or silently changing this pinned candidate), or move exact pre-execution evidence to a trusted BYQ MCP/Backend boundary with root/child attribution, idempotency and unknown-outcome preservation. Neither option is implemented or accepted here. The current `0.1.5rc1` Product runtime remains the deployable baseline. Do not add a BYQ Agent harness or fork DSH.

## Candidate resolution: official per-Agent MCP scopes and ingress proof

The fixed official source offers a narrower path than the parent ACP update
stream. `agent/created` is serial and awaited before the Agent starts work;
its Agent context can load an official MCP client in that Agent's scope. A
process-global bootstrap client makes the BYQ tool namespace known when a
delegate's `toolFilter` is composed, while the nearer scoped client supplies
that Agent's actual request headers. A keyless fixed-source probe observed
one root and one spawned child use distinct synthetic bearer identities for
their tool calls; the ACP parent still reported zero child tool updates.
Another probe confirmed `tools/pre-execute` sees the actual root/child Agent,
native session lineage and call ID, and can deny a child before MCP dispatch.
These three narrow probes PASS. They use mock LLM/MCP, not packaged CLI,
Backend, paid model or Product integration.

The independent review of the earlier process-global-only proposal was FAIL:
root-only MCP headers cannot bind a later business request to a child proof,
and current Backend claim matching omits native child/call identity. This
candidate replaces that insufficient proof source. It still requires an
accepted protocol and end-to-end qualification:

1. Keep one DSH ACP process/native root session per BYQ root. Install a
   Product-only Cordis identity plugin that awaits official `agent/created`
   and loads one official MCP client for each root or spawned child. The
   bootstrap MCP client exists only for tool discovery/filter composition;
   BYQ MCP must reject any tool execution lacking a valid per-Agent identity,
   including fallback after a scoped client disconnects or unregisters.
   The plugin may recognize only one ACP root in the exact contained cwd;
   unrelated Agents are rejected. Every child must have `origin: subagent`,
   a bounded depth and a parentSession chain ending at that exact root.
   Each scoped client carries a private, authenticated root/boot/native-Agent
   session identity and exact parent lineage. A failed scoped-client setup
   rejects Agent creation and cannot fall back to bootstrap execution.
   Product DSH gains no Engineering, shell, filesystem or database access.
2. The trusted MCP ingress, not model arguments or parent ACP updates, is the
   observation point for an actual domain tool request. Before forwarding
   any consequential call, MCP validates the scoped client identity and
   submits an inert, bounded observation to Backend. Backend binds AgentRun
   registration to the same native Agent session, checks its `parent_run_id`
   against the registered native parent session, and checks root, boot,
   owner, workspace, actor, trace, role, task, action, idempotency key and
   canonical request/input digests. The Backend receipt must be durable and
   unique for the actual MCP ingress request; only then may MCP forward the
   request to the existing claim-before-execution path. A missing/mismatched
   receipt, sibling identity, duplicate key with altered input, expired root
   or unknown outcome fails closed. Raw arguments may cross this private
   request boundary but are never stored in the evidence ledger or logged.
   Model-supplied `agent_run_id` remains an untrusted reference. No separate
   Agent loop, generic harness or DSH fork is introduced.
3. Gateway must synchronously establish the Backend root before allowing the
   first DSH tool dispatch, or prove a bounded fail-closed registration retry;
   it cannot infer an unopened root from an MCP request. For ACP, Backend
   owns the evidence cursor and exact proof/claim/terminal receipts, so an
   Adapter crash cannot erase an undrained in-memory call observation. After
   restart, reconcile Backend's scoped terminal sequence/digest before
   same-root transfer or a new root. A claimed but unsettled action remains
   unknown. The current SDK evidence path and storage stay available for
   exact rollback; any new storage is additive.
4. Qualify the packaged fixed candidate with isolated Backend/MCP and mock
   model: root/child/sibling scoped headers, two users, missing scoped client,
   forged or late header, unrelated Agent, scoped-client loss with global
   fallback, role/AgentRun/parent mismatch, changed input, concurrency,
   disconnect, cancellation, crash at every evidence/claim/terminal boundary,
   budget guard and cleanup. Then test one authorized bounded live OpenCode
   Product journey and the real Gateway/Product API browser path if user-visible
   behavior changes. The separate current `0.1.5rc1` OpenCode API smoke does
   not qualify ACP.

The scoped-client probe now asserts every observed bootstrap, root and child
header exactly. A separate negative control disposed the child client before its
call and proved official DSH fell back to the global client; a discovery-only
mock MCP rejected that same fallback request before its business handler ran.
See [fallback qualification](../../evidence/dsh-acp-upgrade/FALLBACK-QUALIFICATION.md).
The actual BYQ MCP guard and disconnect/reconnect path remain NOT_RUN. Independent review still rates the overall design FAIL until
global fallback denial, trusted lineage, Backend binding and recovery are
proved in the packaged Product composition.

The high-level DSH/MCP/Backend ownership remains; the private MCP and Backend
evidence contract changes. Per-Agent signed identity format, ingress receipt
idempotency, registration lineage and restart reconciliation are **NOT_RUN**.
This ADR stays Proposed; no Product ACP promotion follows from the keyless
probe alone.
## Decision and promotion boundary

The maintainer's acceptance of ADR-0093 approved **same-root Backend authority transfer**. It did not approve changing the MCP mount design or relaxing completed Product behavior. This ADR remains Proposed until the exact child evidence replacement and restart reconciliation contract are reviewed and accepted. Meanwhile Product ACP promotion, PR push, auto-merge and deployment are blocked. Safe local source, transport and proof work may continue without external paid-model calls.
