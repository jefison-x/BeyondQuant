# Phase 7 — Compose authority cutover contract

Status: candidate design. The prior per-call Adapter proof proposal is
superseded by this smaller, Compose-scoped design. **No runtime deletion or
Phase 7 PASS is authorized by this document.**

## Supported boundary

BYQ 0.10 supports the Product Agent runtime in its Compose topology: Adapter
Uvicorn is PID 1 of a private PID namespace and owns its DSH subprocesses in
that container. No host PID mode, separate DSH container, Docker socket, or
external child runner is supported under this contract. When namespace PID 1
dies, Linux kills all processes in that namespace, so a dead Adapter container
cannot leave an old DSH child calling Product MCP. This is a deployment
contract, not a general claim about killing an arbitrary Python parent.
Any topology that permits a surviving DSH child needs a new ADR and a stronger
live-call fence before use. The actual Compose image, PID identity and child
death must be proved in a real container test and protected from config drift.

An MCP call durably admitted before container death may have an exact result
or an unknown external outcome. Killing DSH cannot roll back an already
dispatched financial action. BYQ keeps the claim ID, idempotency key and
`outcome_unknown` business safeguards, with no automatic second execution.

## Replacement ownership

The current Adapter journal → Gateway lifecycle delivery → Backend root
terminal transaction is a live BYQ domain-call authorization fence. It must
stay until all of the replacement below works in the same vertical cutover.

1. Adapter exposes a random boot identity in a transport-health response.
   Health must not wait for Gateway's fence, because Compose starts Gateway
   after Adapter becomes healthy. A separate Agent-ready gate denies session
   creation, prompt admission and DSH launch until Gateway has committed the
   Backend fence for that exact boot identity.
2. Gateway holds a dedicated Backend service credential unavailable to DSH.
   For a new Adapter boot identity, Gateway requests one idempotent Backend
   transaction that revokes old active roots and their AgentRun domain-call
   authority. The Backend records only current business authority and exact
   claim facts, not a generic Agent session/recovery ledger. A lost response
   retries with the same boot identity. Backend outage keeps Agent traffic
   unready. The old root becomes `authority_revoked_unconfirmed`: the Agent
   outcome is not fabricated as completed, failed or cancelled.
3. Gateway-only restart with the same live Adapter boot identity does not
   rotate authority. Gateway must preserve or re-establish active/unknown
   Product state and block a conflicting new turn. It may show `interrupted`
   only after Backend has revoked that exact root or acknowledged its exact
   terminal. If identity cannot be checked, Agent traffic stays unready.
4. For a normal terminal, Gateway verifies the exact root's terminal state
   through its fixed Adapter service client; it does not trust a DSH-supplied
   terminal event or root header. Gateway synchronously closes that root in
   Backend using its service identity and returns the idempotent receipt.
   Adapter cannot admit the next
   same-session turn before the receipt. Gateway is a thin service caller,
   not a lifecycle replay/delivery owner. The exact close and retry must not
   reopen a root or close another root. A pending close during Gateway outage
   blocks the next turn until the same exact receipt is obtained.
5. Once startup revocation, normal exact close and their tests pass, delete
   generic Adapter session/root/generation/replay persistence and Gateway
   lifecycle recovery/delivery. Keep only thin DSH translation, transient
   correlation and the ADR-002 bounded child watchdog. ResearchTask, Job and
   Artifact state remains BYQ-owned and queryable by stable business IDs.

The service credential must not be added to DSH's environment or exposed by a
Product API/MCP tool. Existing Adapter research-judgment environment copying
must be narrowed to an allowlist if any new Adapter-held secret is introduced.
An old shared MCP token or client-provided root/session headers are not an
authority-rotation credential. The existing network bridge alone is not an
authorization boundary.

## One-cutover acceptance contract

- Real Compose test: use the supported `compose.yml` plus
  `compose.override.yml` selection (or an explicitly pinned equivalent
  current-build image), assert the resolved Dockerfile/image and Adapter PID
  namespace/PID 1, then start pinned DSH root/child and observable MCP traffic;
  kill Adapter PID 1/container with test-only `restart: "no"`, while MCP,
  Gateway and Backend remain live. Verify Docker reports Adapter stopped,
  DSH descendants disappear, no new old-child MCP call occurs, and Gateway
  rejects a new Agent session/prompt before a replacement starts. A host-only
  `killpg` test does not substitute for this.
- Restart Adapter. Before any new Agent turn or MCP-capable DSH launch,
  Gateway/Backend revoke the exact old root. The old session stays interrupted;
  a fresh session may query durable Jobs/Artifacts by ID. A late old lifecycle
  registration cannot reopen the revoked authority.
- Restart Gateway alone with Adapter and DSH still live. The boot identity is
  unchanged; the existing root stays active/unknown, and a conflicting new
  turn is blocked until exact terminal or explicit revocation.
- Concurrent Backend domain claim and authority rotation have one serial
  order. A pre-rotation committed result stays exact; a post-rotation claim is
  denied. A claimed/executing external action stays unknown until business
  reconciliation; no second execution or compensating action is invented.
- A lost rotation or terminal-close HTTP response retries idempotently;
  Backend unavailability fails closed. Normal terminal close has an exact
  Backend receipt before next-turn admission.
- Inspect the actual diff and schema: no generic Agent session manager,
  journal replay, recovery coordinator, compatibility bridge or old migration
  remains. Existing business approval, audit, Job and Artifact contracts pass.
- Tester, independent Sol Reviewer and Root explicitly PASS the implementation
  before Phase 7 closes. Phase 8 resource deletion stays separately gated.
