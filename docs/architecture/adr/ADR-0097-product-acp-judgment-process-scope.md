# ADR-0097 — Proposed dedicated ACP root for research judgment

- Status: **Proposed — maintainer decision required** (revised 2026-10-04).
- Scope: fixed official dsh-v0.2.0-rc.2 Product ACP research-judgment
  invocation only; normal Product conversation roots keep ADR-0096.
- Would amend: Accepted ADR-0095's judgment child and DSH child-creation
  role-claim requirements. Accepted ADR-0094's per-Agent identity, ingress
  evidence and terminal rules remain mandatory. Historical ADR-0085 is not
  current Clean Break authority, but its bounded domain behavior is retained.
- This proposal alone authorizes no conflicting implementation, version
  change, default upgrade, PR push, merge or deployment.

## Fixed-source and BYQ evidence

The official pinned DSH toolFilter applies to inherited registrations; it does
not remove registrations made in the child's own scope. BYQ's ACP identity
plugin mounts a full Product MCP client into each Agent's scope. The keyless
child probe therefore saw all 13 fixture tools despite the five-tool filter.
ADR-0095 now allows this visibility but requires a trusted call-time role
guard.

The inspected pinned child creation path records parent, origin and depth, not
the invoking tool instance (packages/subagent/subagent/src/child-agent.ts).
The one-shot descriptor arrives after agent/created and its label is
model-supplied; subagent/start also lacks the invoking tool identity. No
trusted role field was identified in those inspected paths. A complete
official hook audit and dynamic ordering proof remain NOT_RUN. Parent and
depth alone must not authorize a child as the judgment role.

BYQ already has an authenticated, task/call-bound judgment entry
(services/runtime-adapter/app/research_judgment_api.py) and an isolated
read-only MCP server mode (services/mcp/src/server.ts,
BYQ_MCP_READ_ONLY_SUBSET=1) that registers exactly five bounded read tools on
a separate port and token. The retained SDK composition connects only to that
endpoint. These are reusable ownership and network boundaries, **not** ACP
integration proof. The present runner is outside a RuntimeAdapter conversation
session; its temporary adapter_invocation_id is not a persisted
RuntimeGeneration, and its stage result receipt is not a BYQ root terminal
ACK. The current read-only mode skips some actor/boot validation
(server.ts:385-388); this is an ACP implementation gate, not an existing
signed-root security guarantee.

The official pinned DSH subagent documentation says mounting the subagent
service alone does not delegate: delegation requires a mounted tool. A
dedicated composition can therefore omit the subagent providers and tools,
subject to inspecting the actual loaded plugin graph and proving there is no
other child-creation path.

## Proposed decision

Run each admitted, named research-judgment request as **one dedicated DSH ACP
root Agent**, not as a child of a model-facing root. The trusted Adapter
selects this mode after exact Backend stage admission. No Gateway/Product
input or normal Product DSH Agent may select it. Keep the same official DSH
ACP transport and Agent loop; the separate composition and process are a
task-specific invocation, not another generic harness or an Engineering grant.

The dedicated composition mounts the Agent-scoped BYQ identity client only
against the isolated five-tool read-only MCP endpoint. It mounts no subagent
provider, delegation/control/fork tool, shell, filesystem, job or other local
execution surface. Its immutable process scope binds task, call,
owner/workspace, BYQ root, Adapter boot and durable generation. The identity
plugin signs those claims with the native root Agent ID. The read-only MCP
server verifies scope and root identity on every tools/call before handler or
Backend ingress; a direct MCP request with this credential remains limited to
the same five reads. The ACP path must use a distinct signed credential, not
the retained SDK runner's static read-only bearer plus client-provided
identity headers. Main and read-only MCP must reject each other's ACP
credentials; distinct keys and an explicit audience check require
qualification. The model may see only the dedicated endpoint's catalog;
ADR-0095 permits extra visibility but does not require it.
The retained static read-only bearer and self-reported identity headers must
not bypass ACP root, AgentRun or terminal admission for the new path.

This removes the unprovable **child role attribution** from this one named
judgment path. It does not remove Product-wide per-Agent identity or call
evidence. If a child is created despite the composition, it receives no
judgment authority and the turn fails closed.

The ACP judgment path must create and persist a distinct BYQ Backend root for
the exact admitted task/call before launching DSH or issuing MCP identity.
Bind root, owner/workspace, call identity, Adapter boot/authority and durable
generation; the temporary invocation ID cannot substitute for this. Register
the native root AgentRun through a trusted non-model control path under a
dedicated least-privilege judgment role before any business read. The model
must neither call byq_agent_run_start nor choose its role.

Commit the stage result through the existing exact-call idempotency path, then
close the BYQ root with complete ingress and unknown-outcome evidence. Obtain
its exact Backend terminal ACK before reporting settlement or releasing
another invocation. A lost result or close response stays unknown until exact
receipt reconciliation; do not repeat the model or business call. Persist and
test the transitions across admission, root creation, registration, result
commit, close and ACK. This lifecycle is **new work**, not inherited from the
old SDK runner.

## Alternatives evaluated

1. **Dedicated ACP process with a judgment child** (previous ADR-0097 draft):
   preserves the child shape but requires proving that the judgment tool is
   the sole child-creation route. Otherwise any other depth-one child could
   inherit process-scoped authority. It also still needs the new BYQ root,
   AgentRun and terminal lifecycle. More moving parts, no demonstrated Product
   benefit for this named turn.
2. **Official DSH provider/plugin supplies a trusted tool-instance claim at
   child creation**: would preserve ADR-0095 exactly and support other
   role-specific children. The inspected fixed-source events do not expose
   that claim. A supported extension or upstream fix would need a narrow
   proof; a new DSH tag requires a separate pin and qualification decision.
3. **Global rather than Agent-scoped MCP registration with toolFilter**: the
   pinned filter could hide inherited tools, but BYQ has not shown how one
   global client safely supplies distinct signed root/child headers or
   prevents direct MCP use. Do not trade away ADR-0094 lineage evidence for
   a smaller model catalog.
4. **ACP permission prompt, DSH pre-execute guard, or persona alone**: useful
   as defense in depth, but none establishes role identity or blocks direct
   MCP requests with a valid Agent credential. They cannot replace the
   MCP/Backend boundary.
5. **Keep the retained 0.1.5rc1 judgment runner**: safe rollback and viable
   deferral if root-only ACP qualification fails; this does not make the fixed
   ACP candidate a complete default Product replacement.

## Qualification before promotion

1. Confirm the pinned official plugin graph contains no executable child or
   local side-effect route in the dedicated composition. Verify dedicated mode
   cannot be selected by normal Product chat, another DSH Agent or an
   untrusted caller. A root-only keyless ACP probe must show one native root,
   five reads and no child.
2. Verify separate endpoint, token and audience; correct owner/task/call/root
   binding; allowed reads; direct-MCP forbidden calls; two-user isolation;
   late/stale token denial; and no handler/Backend entry on a denied call.
   Exercise the retained static bearer and forged identity headers against
   the new path to prove they cannot bypass signed-root admission.
3. Prove trusted root AgentRun registration, persisted BYQ root/generation,
   exact stage-result idempotency, ingress/unknown reconciliation and exact
   Backend terminal ACK across crash and lost-response windows. The existing
   stage result receipt alone is insufficient.
4. Verify the actual Gateway/Product integration and user-visible behavior,
   then obtain independent Tester and Reviewer checks and Root PASS. Preserve
   the exact 0.1.5rc1 image/configuration rollback path and the original
   PR/release/deployment gates. Keyless probes are not Product acceptance.

Until this ADR is accepted and these proofs pass, the affected judgment path
and ACP default promotion remain blocked. The fixed official pin is unchanged.
