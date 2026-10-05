# ADR-0100 — Isolate ACP runner control from ordinary Product DSH

- Status: **Accepted** (2026-10-05; maintainer: "接受"). Acceptance permits
  bounded implementation, not Product qualification or default promotion.
  This expressly amends ADR-0099 Decision 2, which placed only the dedicated
  judgment DSH process in a separate runner container.
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
the next root waits for exact Backend terminal ACK. Mount the existing durable
ordinary ACP session volume at the same canonical path and with the same DSH
UID in the new process owner. Cut over only after every old local process is
fenced and its root has exact Backend terminal ACK. An active or unknown root
must remain blocked; never migrate it by replay. For a completed root, resume
the same native ID/cwd only with the ADR-0096 binding proof preserved by a
signed or Backend-bound readback. If that proof is unavailable, start a fresh
native session only after exact closure and use verified public history once;
do not also restore the old DSH context.

## Proposed amendment — concurrent process ownership (not yet accepted)

This paragraph extends the Accepted decision above. It requires a separate
maintainer acceptance before the fail-closed fallback is wired or promoted,
because one supervisor failure would interrupt every active Product root in
the process-owner container.

The ordinary Product process owner must admit independent root processes
concurrently within an explicit capacity bound. A separate supervisor process
must own each admitted root and become a child subreaper before launching its
fixed DSH command. Its cleanup may reap only descendants adopted by that
supervisor; shared UID 10002 alone is not root attribution. `session/cancel`
remains an ACP request, while process termination is a separate transport
operation.

The process-owner daemon must be PID 1 in its own container PID namespace.
If a root supervisor dies before proving cleanup, the daemon must exit and
fail the entire container closed. Every active root then loses transport and
must remain unknown/fenced until independent Backend reconciliation; the
daemon cannot issue a clean per-root EXIT or terminal ACK for this fallback.
The candidate runtime must verify the actual PID namespace and kill behavior.
Writable per-root cgroups are not assumed by this design.

The alternative is a separately confined process owner for each active root
(or a verified writable per-root cgroup). That would limit a supervisor crash
to one root, but requires a new allocation and recovery mechanism and has not
been qualified. Until one of these containment choices is accepted and
verified, the ordinary ACP process-owner transport cannot be promoted.

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
