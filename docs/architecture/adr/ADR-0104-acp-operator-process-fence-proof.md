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

## Accepted amendment — existing failed terminal (2026-10-18)

**Status: Accepted** (2026-10-18; maintainer: "接受", in response to the
specific existing-failed-terminal amendment). This narrowly amends item 6
above; all other Accepted boundaries remain in force.

Actual retained evidence has a Root with a genuine Backend `failed` terminal
and closed business authority, while its Runtime binding has no confirmed
process exit. The current operator snapshot rejects any existing terminal;
normal Runtime recovery rejects the missing process-exit proof. The existing
Engineering process-fence path therefore cannot finish this cleanup.

Amend item 6 only for an exact, already-recorded `failed` terminal that has
not received its exact terminal ACK and whose occupancy has not been released:

Here, terminal ACK means the completed cleanup/slot-release protocol. Runtime
may already have persisted the exact Backend terminal receipt before teardown
failed. That partial receipt must remain unchanged and match the original
Backend terminal in the locked snapshot, hashed proof, operator observation
and fresh recovery record; its presence alone is not completed cleanup.

1. Reuse the existing private Engineering CLI, pre-execution instance/scope
   binding, native stopped proof, authoritative-volume lock and signed
   successor tombstone. Preserve all item 1–5 identity, authority, snapshot,
   ingress, registration, pending/unknown and domain-claim gates. A failed
   status or container replacement alone never proves cleanup or no effects.
2. Preserve the original failed outcome, sequence, event hash and ingress
   settlement exactly. Do not create a second terminal, relabel it
   `interrupted`, invent an EXIT, or set native cleanup flags to true.
   Persist a separate Backend-owned, protected process-fence receipt bound to
   that original terminal and the complete existing proof/snapshot.
3. Bind Runtime's operator observation and the exact ACK/drain/slot-release
   receipts to the original failed terminal and this separate fence receipt.
   Release occupancy only after all of them verify. Exact retries are
   idempotent; changed terminal, identity, authority, snapshot or proof is HOLD.
   Do not overwrite an existing ACK or reuse an old execution authorization.
4. A later user instruction starts a fresh native execution with verified
   public history once; no old prompt, child or business operation is replayed.

Keep implementation in the existing Backend/Runtime/Gateway contracts and
private CLI; no new service, table, Product API, collector or helper program.
This amendment does not authorize another injected fault, production, merge
or deployment. Reuse the retained failure evidence; any subsequent browser
continuation is a separate bounded acceptance slice after source review.

## Accepted amendment — cleanup proof for an exactly ACKed completed Root

**Status: Accepted** (2026-10-24; maintainer: "接受以上需求，继续。",
accepting the independently reviewed narrow amendment and bounded A operation).

The contract applies only to an exact original scope and old boot whose
Backend Root is `completed` and `closed`, with its matching immutable terminal
ACK, zero unknown ingress for this Root, all claims terminal, and every existing
business gate satisfied. Missing or mismatched evidence remains HOLD.
Initial operational qualification is A only: Root `7ff777b689024eb49076cdf6d65a3624`,
session `byq-session-734f644d7a8f4cc7b39fb253c5cebe02`, ACK sequence 344 and hash
`0763e967f42dc958edbf3fb832b1dc5f84b4dfc2455cc4a774debc763fe45e1e`.
Operations for other identities are not authorized by this proposal.

For an admitted exact Root, the existing qualified Engineering process-fence
path may produce an independent cleanup-only proof after verifying the
originally bound runner instance, exclusive startup/late-START fence, actual
container process termination, authoritative control-volume lock, consumed
successor tombstone, and Backend drain. Retain the existing CLI audit fence.
This proof may authorize a fresh native session after one verified history
read; it does not reopen or reconstruct the completed execution.

Do not alter the completed status, original terminal, ACK, claims, raw unknown
evidence or binding by direct mutation. Do not synthesize a DSH EXIT or MAC.
Keep every safeguard in items 1–5 above. D and any business-unknown Root remain
excluded; qualification does not authorize operations for other identities.
No new API, MCP method, table or program is authorized.

Implementation requires a separately reviewed source change, offline
contract checks, independent review and explicit command authorization before
the isolated current-browser check. Keep those gates separate; a source or
offline pass alone does not qualify cleanup or browser recovery.


## Accepted correction — completed terminal persisted before cleanup/ACK

**Status: Accepted** (2026-10-24; maintainer: "接受 ADR-0104 这处纠正，继续最小修补。";
corrects the admission premise above).

The retained A binding proves that Runtime received and persisted the exact
Backend terminal receipt. It does not prove completed terminal ACK: Runtime
persists settlement before cleanup, and records the ACK only after cleanup.
Therefore A is not qualified by the preceding exactly-ACKed amendment.

For the initial A-only qualification identified above, permit the same
independent cleanup-only proof when Backend is `completed` and `closed`, the
original immutable terminal matches the exact persisted settlement receipt,
and cleanup/ACK remains incomplete. Preserve every scope, pre-execution runner
binding, native stopped proof, exclusive volume lock, successor tombstone,
late-START rejection, Backend snapshot, unknown-zero, claim and drain gate
already required above. Never treat the persisted settlement as a completed ACK.

Keep the original completed outcome, terminal, settlement receipt and business
records unchanged. Persist a separate protected cleanup proof and verified
Runtime observation before exact slot release and the new cleanup/ACK
confirmation. Only then allow a fresh native execution with verified public
history once. Do not retrospectively assert a missing original ACK or restore
the old Agent. D and genuine business-unknown executions remain excluded.

Keep the same six-file implementation scope, existing private CLI and routes;
no new API, MCP method, table, program or authority expansion. Source, offline,
independent-review, exact-command and isolated-browser gates remain required.
The maintainer accepted this corrected admission condition before implementation.

## Accepted correction — pending cleanup confirmation after Runtime replacement

**Status: Accepted (2026-10-26).** The maintainer continued the concrete,
independently reviewed proposal with: "继续验证并修复，不要停，直到完成整体验证。"
This authorizes its bounded implementation and isolated qualification, subject
to the source, command and service gates below; it does not authorize production
deployment, pushing, merging or broader recovery semantics.

The first A-only completed-cleanup proof is now durably stored, but Runtime
failed with `NameError` while validating its observation, before the observation
write or slot release. Its Backend ACK count is zero and its original V2 bytes
remain unchanged. Fixing the validator requires replacing the Runtime process;
that creates a new boot and authority epoch. Existing ACK and cold-recovery
contracts reject that new authority for the stored close receipt. Neither
rewriting the original proof nor reusing the old boot is an acceptable repair.

Permit one protected Engineering handoff of **cleanup-confirmation authority**,
with these closed conditions:

1. Initial qualification is only operation
   `a510a3c04f2abd4aa22d7ac72347e315`, Root
   `7ff777b689024eb49076cdf6d65a3624`, Workspace
   `workspace_4c5b803209d549019b7804976f6930c6`. The original protected proof
   receipt SHA is
   `82cff128ed5f46694b27a917b4eb349614fa8d1fbcaf64d2c75238f5a4baa217`;
   retain its close receipt, execution scope, settlement and terminal344 with
   event SHA
   `0763e967f42dc958edbf3fb832b1dc5f84b4dfc2455cc4a774debc763fe45e1e`.
   This does not admit D or genuinely unknown business results.
2. Before replacement, prove that this exact operation has no persisted Runtime
   observation, no slot release and no Backend ACK. Logs alone are insufficient:
   require the unchanged original binding, exact reservation/lease facts and
   protected audit records. A partial or uncertain confirmation remains HOLD.
3. Require accurate native stopped-process proof for the old Runtime, the same
   trusted deployment and authoritative storage, zero active prompts, settled
   claims, unknown-zero and unchanged original runner/successor fence anchors.
   Stop all old confirmation writers before adopting a new current authority.
4. Append one independently protected, idempotent handoff receipt through the
   existing Engineering CLI and operations-audit mechanism. Bind the full
   original proof/close digests, operation, scope, reservation and binding digest,
   exact stopped Runtime identity, old confirmation boot/epoch and the actual
   newly registered current boot/epoch. Reuse returns the exact receipt; changed
   content or a second conflicting successor is rejected. No Product actor may
   create or widen this authority.
5. Original proof, close receipt, business execution authority and terminal are
   immutable. Only enumerated Runtime authority metadata and its new boot
   receipt may differ in the confirmation preimage; every business row and
   unknown/claim condition must still match. Do not use a general delta waiver.
6. The existing authenticated private terminal-receipt/confirm-ack flow may
   consume a closed handoff envelope while retaining the original close bytes.
   It must verify the separate handoff and actual current authority before
   adopting only that operation's pending reservation. Persist the independent
   observation, verify it, release the exact reserved slot, then persist the
   Backend confirmation. Bind all later receipts to both the original proof
   and handoff. Do not replay close, native execution or business work.
7. Crashes, late old-authority requests and repeated acknowledgements must be
   resolved from durable exact receipts. Unknown observation/release/ACK state,
   changed scope, absent old-process proof or any business unknown remains HOLD.
   Never delete a protected proof, fabricate an ACK, force-release a slot, or
   claim restoration of the original Agent.
8. Keep the existing private CLI/routes/tables and Product/Engineering boundary;
   no new API, MCP method, helper program, harness or Product privilege. This is
   a maintenance correction, not Product Phase advancement.

Before implementation: maintainer acceptance of this specific correction, then
independent review of the full transaction, lock order, restart gap and receipt
chain. Before service changes: targeted existing checks, source/image admission
and complete actual-command review. Qualification must separately establish the
pending-proof handoff, exact observation/release/ACK chain and current-browser
continuation before either remaining business acceptance case. Keep the retained
environment/pages and report PASS, FAIL and NOT_RUN separately.
