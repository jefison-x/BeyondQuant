# ADR-0113 — Historical audit-only unknown reconciliation

- Status: **Accepted** (2026-10-16; maintainer: "接受 ADR-0113，继续实现并用浏览器验证").
  Acceptance authorizes the bounded implementation and verification gates below;
  it does not itself authorize an unreviewed recovery operation.
- Scope: DSH/ACP maintenance, not Product Phase advancement or production deployment.
- Amends the unresolved audit-ingress fence in ADR-0100/0109/0112 only through
  the explicit reconciliation below. ADR-0104 remains Proposed and is not enabled.

## Confirmed gap

The retained test Root `753727634c8641a0add1597d6a304bae` has two historical
`byq_agent_audit` observations persisted as unknown. Its child received generic
422 responses; later successful audit calls do not settle those exact requests.
ADR-0112 prevents this failure for future deterministically rejected requests,
but expressly leaves old unknown observations immutable. They still prevent
terminal ACK and normal release of the Workspace slot.

Ordinary DSH belongs to the independent Product runner. Restarting only the
Adapter cannot prove that process stopped. Restarting both services is not a
substitute for an accepted process proof, business reconciliation, or terminal ACK.

## Accepted narrow decision

Allow a trusted Engineering operator to reconcile **only ordinary public audit
append uncertainty**. This is explicit acknowledgement that an old audit append
may or may not have occurred; it is not a claim that the request had no effect.
It cannot reconcile authorization decisions, Jobs, domain writes, external
effects, financial outcomes, pending requests, or unknown non-audit tools.

1. Freeze the exact owner/Workspace/public conversation/private session/trace,
   boot/epoch/Root/native scope, bound AgentRuns, and complete ingress snapshot.
   Bind each selected unknown observation by request ID, sequence/event hash,
   arguments hash, and its original settlement hash. The supplied arguments
   must match the stored hash and describe the ordinary audit append path;
   reserved ACP control records are excluded. Backend verifies the persisted
   tool identity; caller labels cannot classify an arbitrary write as audit.
   Every other ingress/claim must already have its normal proven settlement.
2. Before reconciliation, stop further dispatch/provider use for that **exact
   Root** and obtain the existing runner-signed, exact-scope **proven cleanup**
   receipt. Extend the existing private exact-Root lifecycle operation only
   as needed to stop this generation while keeping the public conversation
   open. No hard public conversation cancel, prompt replay, or reconstructed
   child process is permitted. Missing/unknown cleanup keeps the fence closed.
   A container restart or absent PID alone never supplies this proof. Lost
   runner receipt recovery remains outside this ADR, under Proposed ADR-0104.
3. Under existing authority/Root/ingress locks, Backend rechecks the exact
   frozen scope, fence, cleanup and full snapshot. Prefer the existing
   `agent_audit` insertion seam and its reserved `detail.acp_control` namespace
   for a separate Backend-owned reconciliation receipt, including the named
   operator, evidence digests and explicit
   `audit_append_outcome_unknown_acknowledged` disposition. Product MCP/DSH,
   ordinary audit input and browser clients cannot create this receipt or use
   their credentials to call the Engineering operation; its credential must
   not be a Product token or the Product MCP Backend-proof bearer. Before
   implementing release, prove that this seam can bind the correct AgentRun,
   use one deterministic reserved audit ID per exact Root with the existing
   primary-key uniqueness, compare exact content on repeats, and prevent
   ordinary creation/update/deletion of the proof. The current ordinary audit
   table is not already assumed to provide these operator guarantees. Missing
   or altered proof must hold the fence; ordinary reset/retention must not
   erase a required proof. If the existing seam cannot satisfy this gate,
   return to ADR review instead of introducing another store. This introduces no
   user continuation permission, model quota, scheduler, or second harness.
4. Original unknown rows and their receipts stay byte-for-byte unchanged.
   The existing terminal safety guard may exclude an unknown **audit ingress**
   only when the exact trusted reconciliation receipt covers it and every
   other gate passes. Pending ingress and every unacknowledged unknown still
   block. Version the Backend-owned ingress snapshot preimage to include the
   complete original ingress rows and exact reconciliation receipt/digest;
   bind it through the existing `terminal_acp_ingress_sha256` and exact
   Backend/Adapter/Gateway ACK checks. Preserve the original audit-unknown
   count and explicit acknowledged disposition in that private snapshot;
   never present them as successful/denied requests or zero unknowns.
   `terminal_unknown_claim_count` counts domain claims, not tool ingress;
   retain its independent zero-claim requirement unchanged. Prefer retaining
   the outer terminal DTO. If its shape must change, synchronize its closed
   schema and exact checks through Backend, Adapter and Gateway before use;
   no service may ignore added reconciliation evidence. An interrupted Root may
   close through the exact Backend ACK plus proven runner cleanup. Do not
   fabricate the old successful completion or claim the failed trial passed.
   The close outcome must follow the unique existing normalized lifecycle
   event; `interrupted` above is permitted, not mandatory. For the retained
   Root, a read-only Gateway read proves an original `session.result` with
   outcome `completed`, sequence 167. Preserving that real model-loop outcome
   is allowed; audit append uncertainty remains explicitly acknowledged and
   unknown, and the failed qualification batch stays FAIL. Do not relabel or
   invent a historical event merely to force an interrupted outcome.
5. An exact repeat returns the original reconciliation receipt. Changed
   identity, request set, arguments, settlement, cursor or process proof fails
   closed. A concurrent append invalidates the frozen snapshot. Never infer a
   new Root's eligibility from Adapter memory loss. Only after normal exact
   ACK/cleanup release may the same public conversation accept new input.
   Where the completed-native-resume proof is unavailable, use a fresh native
   session with verified public history once; never resume/replay the old child.

## Delivery and verification

Acceptance permits a bounded source implementation, not immediate execution on
the retained environment. First audit the existing lifecycle/control-audit
seams; do not add a new storage table or general operator framework. If those
seams cannot hold an unforgeable, exact reconciliation receipt and terminal
projection, return to ADR review instead of weakening the contract.

After syntax/type/build checks and independent Sol source review, prepare the
exact recovery preflight and rollback/hold boundary for Root review. Preserve
the original failure, unknown rows, test environment and page. Functional
verification uses browser → Gateway/Product API: apply the separately admitted
Engineering reconciliation, verify the old answer/history remains, send one
ordinary next input, then verify current delegation and automatic continuation
in small declared batches. No added functional test code is required by this
decision. Read-only receipts confirm exact ACK, cleanup and no replay; untouched
negative cases remain NOT_RUN. Production, push and merge retain their gates.
