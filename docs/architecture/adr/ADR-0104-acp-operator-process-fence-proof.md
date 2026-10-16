# ADR-0104 — Operator process-fence proof for an unresolved ACP root

- Status: **Accepted** (2026-10-17; maintainer: "接受 ADR-0104，继续实现并验证").
  The maintainer accepted the independently reviewed 2026-10-17 revision and
  authorized one bounded fault/replacement verification of the isolated
  `byq-dev-e8b02b5475` A Product runner after implementation, review and admission.
  Preserve database, volumes, images and pages. Production/push/merge are excluded.
- First implementation scope: the ordinary Product ACP resource group
  (ADR-0100) only. Judgment recovery is deferred. Does not change the Backend's
  `process_fence="stopped"` requirement and does not authorize an
  unproven-fence `abandoned` state.

## Problem

A root can be left unresolved when its runner/DSH process is lost without a
runner-persisted signed cleanup receipt (e.g. the runner container is replaced,
or the runner crashes before writing the receipt). The Backend deliberately
preserves such roots (`authority_revoked_unconfirmed`) and requires
`process_fence="stopped"` before close, so the operator cannot close them. On a
single-workspace slot this permanently blocks the workspace's next root. The
only existing trusted fence-proof entry is the runner-persisted signed cleanup
receipt (ADR-0099 / the option-c mechanism); when no receipt exists there is no
operator path. "No current process" is not a proof and a historical EXIT must
never be forged.

## Accepted minimal contract

This adds an independent **Engineering-origin process-fence proof**, not a
runner cleanup receipt. Different instance IDs, a new PID namespace, a missing
PID, or `restart=no` alone do not prove that the old execution cannot continue.

1. **Qualified identity before execution.** A qualified runner durably records
   its signed instance/boot/Workspace identity and holds an exclusive lock on
   its authoritative state volume for its whole lifetime. Engineering binds
   that instance to an exact immutable container ID, image, deployment group,
   start identity, private PID namespace and authoritative volumes while the
   instance is running, before accepting its first START. Every START durably
   binds the full exact scope to that instance before dispatch. An old image
   without these records cannot acquire eligibility retrospectively. Switching,
   cloning or rolling back the state volume is not a replacement proof.
2. **Explicit native Engineering verification.** Freeze dispatch for the exact
   affected Workspace/Root. A bounded one-shot Engineering operation verifies
   the pre-bound old container: stopped, PID0, not paused/restarting, private
   PID namespace, and automatic restart disabled. Missing daemon/readback,
   ambiguous identity or an unverified extra instance is HOLD. A successor must
   acquire the same volume lock, validate the old instance/scope/consumed facts,
   and atomically persist an exact old-instance/scope tombstone before ready.
   Qualified startup and START reject that consumed scope even after a manual
   restart. Recheck the old container and replacement boundary before finalize.
   The successor only attests its own lock/tombstone installation; it cannot
   infer or sign a claim that another container died.
3. **Existing Engineering execution boundary.** Prefer the existing one-shot
   private Backend/Runtime CLI and protected reserved control-audit pattern of
   ADR-0113. Trust comes from restricted local Engineering execution and private
   Docker/Backend access, not caller-supplied UID/name or a Product/runner
   credential. UID/name records attribution only. No new HTTP/MCP/browser
   operation, service, generic recovery framework, database table or scheduler
   is authorized. Product DSH receives no Docker socket, business DB, host
   authority, application-source access or permission to issue this proof.
4. **Closed evidence and idempotency.** The versioned proof binds an operation
   ID; named operator; full owner/Workspace/session/trace/Root/Adapter boot/
   epoch/generation/cwd scope; old and new runner instance identities; exact old
   container/image/deployment/start identity and pre-execution binding digest;
   authoritative state-volume identity; native stopped/namespace/restart-fence
   evidence digests and observation times; tombstone digest; and the frozen
   Backend ingress/registration/claim snapshot digest. Keep native command,
   exit-code and evidence originals outside model output. Store an unforgeable
   Backend-owned receipt in the existing protected audit seam. Exact repeats
   return the same receipt; changed content, scope, authority, snapshot, volumes
   or evidence is HOLD. Ordinary audit/reset/retention cannot forge or remove
   required proof. If that seam cannot satisfy this, return to ADR review.
5. **Business outcome remains separate.** Backend locks and rechecks current
   authority, exact Root and the complete canonical ingress, native registration
   and domain-claim snapshot. Pending/unknown business effects, unbound
   registrations and unsettled claims still block. Process death never makes a
   business call successful, denied, absent or safe to replay. ADR-0113 audit-only
   reconciliation, where applicable, remains a separate explicit receipt; it
   does not authorize reconciling genuine business unknowns.
6. **Distinct interrupted lifecycle and exact ACK.** Only after proof and all
   independent business gates pass may the existing lifecycle close this exact
   Root with a Backend-owned operator-fence/interrupted fact and exact terminal
   ACK. Do not invent a historical DSH EXIT, model result, cleanup MAC or native
   close RPC. If no genuine terminal event exists, define the distinct operator
   event and its closed projection consistently across Backend/Adapter/Gateway;
   never relabel an old event to fit the existing receipt. Preserve raw history.
   Release occupancy only after exact ACK, proof and drain are all confirmed.
   Any interrupted prepare/finalize leaves the fence held until an exact retry.
7. **New execution only.** Keep the public conversation and durable Jobs/results.
   If native-close/resume proof is unavailable, a later user instruction starts
   a fresh native session with verified public history injected once. It may
   create a new child to read an existing authorized result; it never restores,
   reconstructs or replays the old child, prompt or unknown business command.

This amends ADR-0100's lost-cleanup release boundary and ADR-0113
item 2 only for this independently proven process fence. Existing signed-cleanup
recovery and qualified idle restart remain valid. Until implementation and actual
qualification, the existing missing-cleanup fence remains unchanged.

## Explicitly rejected

- Treating "no current process" as a fence proof.
- Forging or replaying a historical EXIT.
- An unproven-fence `abandoned` outcome that releases the workspace without a
  trusted proof.
- Relaxing the Backend `process_fence="stopped"` requirement for ordinary close.

## Delivery and verification gate

This is maintenance, not Product Phase advancement or production authorization.
Acceptance permits only the bounded ordinary-Product implementation above.
First audit the existing private CLI, binding, lock, lifecycle and reserved-audit
seams; no broad refactor. Keep proof types closed and independent; syntax/type/
build checks and independent Sol source review precede any environment update.

Prefer native operations and the retained browser for functional verification.
First qualify immutable instance binding, exclusive startup and tombstone
behavior without real model calls; a proof/state conflict must stop safely.
Only then admit one bounded active-execution-loss case with exact fault target,
call/Job/time caps, preserved volumes/images/evidence and independent review.
Verify interruption and fresh-child reads of an existing Job through
Gateway/Product API, no prompt replay or claim of old-child restoration. Reuse
the valid idle-restart/read evidence; do not rerun it as active-loss proof.
True business unknown remains blocked. Fault injection without the qualified
closing path is NOT_RUN. Merge, production and destructive actions retain their
separate authorization gates; no database rebuild or volume cleanup is recovery.
