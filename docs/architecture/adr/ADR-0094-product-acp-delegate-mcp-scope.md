# ADR-0094 — Product ACP delegate MCP scope and restart evidence

- Status: Accepted (2026-10-04). The maintainer explicitly accepted the new
  MCP/Backend proof contract in the development chat. Implementation,
  qualification, PR and release gates remain separate.
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

At this probe stage the remaining design options were: obtain official DSH ACP child event projection in a fixed future candidate (without forking or silently changing this pinned candidate), or move exact pre-execution evidence to a trusted BYQ MCP/Backend boundary with root/child attribution, idempotency and unknown-outcome preservation. The latter contract is accepted below; the keyless probe itself did not qualify implementation. The current `0.1.5rc1` Product runtime remains the deployable baseline until end-to-end qualification. Do not add a BYQ Agent harness or fork DSH.

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
Acceptance authorizes implementing this private proof contract. No Product ACP
promotion follows from the keyless probe alone.

## Accepted private proof boundary

The ACP candidate uses three distinct credentials in protected configuration:
a discovery-only MCP bearer, an HMAC key shared only by the trusted Product
composition and MCP ingress, and a separate MCP-to-Backend proof bearer. The
existing SDK MCP bearer remains on the old rollback path. The ACP bearer is a
bounded signed claim over the exact root/boot/public scope, native root and
Agent session IDs, native parent, origin, depth and expiry. MCP verifies the
signature and replaces caller-supplied scope headers with its verified claims.
The discovery bearer may list tools but every tool execution is refused before
a handler runs. The ACP child process does not inherit the old SDK MCP bearer
or the Backend proof bearer.

For ACP-aware `byq_agent_run_start`, MCP forwards only token-derived native
lineage using the private proof bearer. Backend derives the expected parent
AgentRun from its durable native-parent binding before registration, and
atomically stores a pending native binding with the AgentRun. MCP then
finalizes that exact binding before returning success to the Agent. A pending
or bound ACP marker on the root requires ACP evidence for domain claims; it
cannot fall through the old SDK evidence path. Exact retries return the same
receipt, while altered identity or input conflicts.

For every Product MCP tool that enters Backend, MCP observes the actual
validated arguments before invoking its handler. Backend verifies the native
Agent binding and authority, stores only a bounded canonical argument digest,
and durably returns a unique ingress receipt in a pending state. The existing
four consequential domain actions additionally use their canonical request
and input digests and claim-before-execution receipt. Raw arguments are not
stored in the evidence ledger.

The ingress receipt remains pending until MCP proves that its handler has
finished and submits an exact settlement. A lost response, timeout, uncertain
write, or lost MCP process remains pending or unknown; elapsed time never
means the business effect was absent, and no interrupted call is replayed
automatically. Backend serializes ingress, settlement and root close under the
same root lock. It refuses terminal close or authority transfer while any
ingress, native Agent binding, or consequential domain claim is unresolved.
If MCP receives no valid observation receipt **before entering the handler**,
it may send one exact `abort_before_dispatch` using the original request ID,
signed scope, native lineage, tool name and validated arguments. Backend
recomputes the argument digest under the same request/root locks. An existing
pending observation becomes durably aborted; if the observation has not yet
arrived, Backend stores a terminal tombstone that rejects a delayed observe.
The abort cannot reclassify a settled or unknown handler result. A lost abort
response or MCP crash before the abort remains fail closed until exact
reconciliation; no timeout expiry clears pending evidence.
A successful close freezes the bounded ingress
high-water cursor and digest, including each settled or aborted outcome and
settlement hash, together with the exact terminal sequence and
digest. A later old-root request cannot be dispatched, and the next root
requires the confirmed Backend terminal receipt. Restart reconciliation uses
the persisted receipts and preserves uncertain outcomes until exact
operation-specific reconciliation or trusted operator resolution.

The candidate Compose overlay supplies these credentials only to the services
that use them. Secret values remain outside Git. The old SDK image and
configuration remain the exact rollback set.

## Fixed-source qualification finding after acceptance

The official `tools.restrict` contract filters inherited global tools but
deliberately keeps registrations made in the Agent's own scope visible. The
accepted per-Agent MCP client registers the complete BYQ catalog in that
scope. A keyless fixed-source probe therefore found `byq_strategy_validate`
model-visible in root and child catalogs despite the continuation restriction
and child `toolFilter`. A pre-execute guard can still deny dispatch, but the
bounded `research-judgment-turn` has a separate Accepted ADR-0085 obligation
to **not expose** write, approval, execution or routing tools in its model
catalog. The exact role path and a supported filter mechanism remain to be
qualified. This ADR does not waive ADR-0085; until the role's catalog is
proved bounded, the Product ACP candidate cannot be promoted. Do not insert
a speculative compatibility wrapper or fork the fixed official DSH source.

## Decision and promotion boundary

The maintainer's acceptance of ADR-0093 approved **same-root Backend authority
transfer**. The subsequent explicit acceptance of this ADR authorizes the
per-Agent MCP scope, discovery-only bootstrap, trusted ingress evidence and
Backend reconciliation contract above. It does not relax completed Product
behavior or waive qualification. Product ACP promotion, PR push, auto-merge and
deployment remain gated on the end-to-end evidence and independent review.
