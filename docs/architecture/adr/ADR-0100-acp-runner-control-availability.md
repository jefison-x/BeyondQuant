# ADR-0100 — Isolate ACP runner control from ordinary Product DSH

- Status: **Accepted** (2026-10-05; maintainer: "接受"). Acceptance permits
  bounded implementation, not Product qualification or default promotion.
  This expressly amends ADR-0099 Decision 2, which placed only the dedicated
  judgment DSH process in a separate runner container.
- Accepted simplification (2026-10-05): maintainer: "那就按上面的方法收敛。"
  One authenticated Workspace owns a resource group; initially that group has
  one ordinary ACP execution slot. This replaces the unaccepted multi-root
  supervisor proposal without granting team membership or provisioning
  features.
- Scope: fixed official DSH `dsh-v0.2.0-rc.2` candidate only. Keep the
  `0.1.5rc1` image and configuration as the exact rollback path.

## Evidence and problem

ADR-0099 puts only the research-judgment DSH process in an internal-network
runner. The Adapter still starts ordinary Product DSH as its own UID 10002
child and joins supplementary GID 10005 to access the judgment runner's Unix
socket. The ordinary DSH child inherits GID 10005. The socket directory is
`root:10005` mode `0710`, the socket is `root:10005` mode `0660`, and the
server handles connections sequentially with a five-second authentication
deadline. An ordinary Product DSH process can therefore repeatedly connect
and occupy the unauthenticated handler. The control HMAC prevents an
unauthorized START but does not give an authorized Adapter request a bounded
opportunity to start. An offline candidate image confirmed UID 10002 with
groups `[10002, 10005]`; an unprivileged `setgroups([])` attempt returned
`EPERM`. Independent review classifies this as a P2 default-promotion gate.

The first candidate also shared the judgment session volume with Adapter;
ordinary DSH could access a judgment leaf under the same UID. That mount has
been removed. Final judgment wiring now needs a runner-signed or
Backend-bound native-session proof instead of local marker reading. This
second issue is a separate acceptance requirement.

## Decision

Move ordinary **ACP** DSH processes out of the trusted Adapter container into
a separate process-owner service. The service runs the same fixed official DSH
image and a reviewed process relay, not a second Agent harness. It makes no
Agent, tool, budget, business or Backend authority decisions. It has its own
control socket, separate control secret and session storage. The Adapter
remains the sole Gateway/Backend runtime authority and performs all existing
MCP identity, budget, result and terminal-ACK checks.

Only the trusted Adapter **container** mounts the judgment runner control
socket. Its other subprocesses, including the provider HTTPS worker, inherit
the container's process credentials; the final design must inventory them and
exclude arbitrary model-controlled execution. The
ordinary process-owner service and its DSH children do not mount that volume
and do not join the judgment control GID or `byq_acp_judgment` network. They
cannot reach the isolated five-read MCP or judgment provider-proxy listener.
The judgment runner remains on its internal-only network with no ordinary
Product provider route. The ordinary process owner gets only the network and
volumes its existing Product DSH process needs; it receives no Gateway/Backend
authority or Engineering credential. Reuse the runner framing and process
cleanup implementation with separate, explicit Product versus judgment
profiles and secrets; do not add a generic planning/tool harness.

The Adapter must not start an ordinary ACP DSH child locally after this
switch. Keep the existing SDK image/configuration selectable for rollback.
No Product API or public session identity changes are permitted. A new root
must still receive a new MCP identity, late requests retain the old root, and
the next root waits for exact Backend terminal ACK. Each group mounts its own
durable ordinary ACP session volume with the same DSH UID. A session's native
ID and canonical cwd stay stable within that group. Existing ACP candidate
state outside the configured group is not silently moved or replayed; retain
it as evidence and require exact closure before any explicit cutover. The
retained SDK deployment and its old volume remain selectable for rollback.
Cut over only after every old local process is
fenced and its root has exact Backend terminal ACK. An active or unknown root
must remain blocked; never migrate it by replay. For a completed root, resume
the same native ID/cwd only with the ADR-0096 binding proof preserved by a
signed or Backend-bound readback. If that proof is unavailable, start a fresh
native session only after exact closure and use verified public history once;
do not also restore the old DSH context.

## Accepted simplification — Workspace resource group and one slot

Use the Backend-authenticated `workspace_id` as the resource-group identity.
`owner_principal` records the initiating user; it is not the group key. The
current Backend supports only personal Workspaces. A later team Workspace may
use this same boundary only after its membership/RBAC contract is implemented;
this ADR does not add invitations, teams, billing or a tenant control plane.

The existing singleton Adapter selects a statically configured socket and
separate control secret for the authenticated Workspace. The execution
container is itself bound to that Workspace and rejects another Workspace,
arbitrary commands, foreign cwd or authority secrets. Each group has its own
ordinary native-state volume, control volume and runner tombstones. An
unconfigured group fails closed; it does not borrow another group's slot.
Deployment binding belongs to a trusted operator, never the browser or DSH.

Initially each group has one slot, and each execution container runs at most
one root at a time. Multiple sessions may be stored without occupying a slot:
start execution lazily on user input. An occupied group returns the existing
Product conflict/busy response rather than introducing a queue. Different
groups execute independently. The Adapter retains occupancy through both the
exact Backend terminal ACK and confirmed process cleanup, in either order.
An unknown or lost receipt keeps that group fenced; no prompt is replayed.
Backend root authority remains the durable business truth across Adapter loss.

Reuse the existing sequential runner's process ownership, bounded relay and
cleanup. Do not add a supervisor process per root, per-root UID pool, cgroup
delegation, dynamic container allocator or cross-group scheduler. The runner
must be PID 1 in its private container PID namespace. On cleanup uncertainty
or transport loss it retires that slot; daemon death terminates the remaining
processes in that namespace. Only its one active root is affected, and no
clean business ACK is inferred from container exit. Actual candidate process
and container behavior requires focused proof.

Later capacity can be increased by adding statically bound slots to the same
group. Their routing and storage access still require qualification; changing
the count alone is not evidence of safe session concurrency. A given native
session can execute only one root at a time, with ACK before its next input.
Group persistence is separate from an ephemeral execution container.

The former shared-container, concurrent per-root subreaper/PID1 fallback is
withdrawn. Its local mechanism probe remains valid historical evidence, but
it is not an implementation requirement or Product acceptance.

## Rejected and deferred alternatives

- A shorter socket timeout or a threaded unauthenticated handler reduces one
  connection's effect but cannot bound repeated same-GID saturation.
- HMAC or `SO_PEERCRED` alone cannot separate Adapter and ordinary DSH while
  they share UID/GID and the same container boundary.
- Granting the Adapter `CAP_SETUID`/`CAP_SETGID` to launch ordinary DSH under a
  different UID changes the privilege of the existing authority holder. It
  would also require a new readback contract for the ordinary session volume.
  This is deferred unless the separate process-owner path proves infeasible.
- Running a second full Adapter is rejected: it would duplicate the singleton
  Backend/Gateway authority and conflict with ADR-0099.

## Required evidence

The maintainer accepted this ADR before conflicting implementation.
ADR-0096 requires native ID/cwd proof, not a specific local marker file, so a
signed or Backend-bound replacement preserving its semantics does not by
itself require another ADR amendment. A changed public resume contract would.

Before promotion:

1. A narrow source and Compose design shows that the existing Adapter owns one
   boot/epoch, ordinary DSH cannot see the judgment socket or secret, and no
   Product DSH receives Engineering or Backend authority. Inventory every
   Adapter-side subprocess with the socket GID and prove none executes
   arbitrary model-controlled code. The process relay must not become a
   generic Agent harness.
2. Two-user ordinary ACP conversations, multi-turn, stop/continue, end,
   restart/resume, distinct root MCP identities, late requests and exact
   terminal ACK pass through Gateway/Product API. Verify normal provider
   routing and the retained SDK rollback.
3. A deliberately untrusted ordinary DSH process fails to reach the judgment
   socket, session volume, isolated MCP and judgment proxy listener; repeated
   connection attempts cannot starve a judgment START. Confirm actual
   container mounts/networks, not just Compose text. Continue the separate
   ADR-0099 provider egress and process cleanup gates.

Until qualified, keep `/internal/runtime/research-judgment/{task_id}/acp-root/run`
at 503, do not default-promote ACP, and do not push a qualification PR.
