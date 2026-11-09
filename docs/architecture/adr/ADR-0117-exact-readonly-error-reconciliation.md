# ADR-0117 — Exact historical read-only error reconciliation

- Status: Accepted (2026-11-09). The maintainer explicitly answered:
  “接受 ADR-0117，继续实现和测试” after the bounded design and existing
  architecture restriction were presented. Source, proof and execution gates
  below remain required; acceptance does not claim successful recovery.
- Scope: maintenance of the retained development-test execution only; no Product
  Phase advancement, production change, publication, merge, or generic recovery.

## Problem and boundary

Root `f6dc48f8c4e446c6912eed772a47493f` in Workspace
`workspace_4c5b803209d549019b7804976f6930c6` remains active because ingress
request `d654db9604d2a0631a6db5ba5e77412c` (sequence 8,
`byq_market_daily`) is unknown. Its retained request lacks required dates and
the retained result is a deterministic 422 validation error. The audited
implementation is read-only and rejects the malformed request before querying.
The prospective MCP classification fix does not change this historical record.

ADR-0113 covers ordinary audit appends only; ADR-0114 covers exact local strategy
validation. Neither proves or authorizes this different reconciliation. No
container restart, missing PID, fresh conversation, or ordinary caller assertion
can resolve the retained record.

## Accepted bounded decision

1. Admit only the exact Root, Workspace, request, tool and sequence above. Bind
   owner, conversation, private session, trace, original authority boot/epoch,
   generation/native identity, complete ingress/registration/claim snapshot,
   original argument and settlement hashes, original normalized terminal event,
   and reviewed exact-version read-only implementation evidence. The stored
   arguments hash must match the retained request; preserve the retained failed
   response as evidence without claiming a proven paired HTTP422 delivery.
   Prove the exact tool call chain cannot perform external, financial or data
   writes. Missing proof of that property is HOLD, not an inferred exemption.
   Changed scope or evidence is HOLD. No live tool replay is permitted.
2. Freeze dispatch while obtaining the existing Product runner's signed,
   exact-scope proven cleanup. Verify its MAC and original control-key binding;
   use existing native lifecycle/control operations. Stop further provider use
   for that Root. If no valid cleanup proof exists, HOLD; ADR-0104's separate
   process-fence requirements are not waived or fabricated.
3. Through a restricted local Engineering entry, recheck current authority and
   the frozen snapshot under the existing writer/authority/Workspace/request/
   Root locks. Require all other ingress settled, no pending registration and
   no unresolved domain claims. Reject changes or concurrent late writes.
   Product credentials, ordinary audit input and browser/MCP calls cannot issue
   or change the proof; add no HTTP endpoint, table, service or scheduler.
4. Append one deterministic, Backend-owned reserved `agent_audit` receipt with
   operator attribution and disposition `readonly_query_outcome_unknown_acknowledged`.
   Include the exact original hashes, evidence digests and signed process proof.
   Keep the unknown ingress and its settlement bytes unchanged. Exact repeats
   return the original proof; different inputs fail. This explicitly acknowledges
   that the pure read's result remains unknown, not successful research, a
   successful/rejected request, proven HTTP response delivery, or permission
   to reconcile writes, financial effects or an arbitrary unknown result.
5. The terminal safety guard may cover only this one unknown through the exact
   protected proof. Bind raw ingress plus reconciliation receipt into the
   terminal ingress digest. Preserve the raw unknown ingress count separately;
   domain claim count retains its independent zero requirement. Protect the proof
   from ordinary audit creation/update/deletion and reset/retention deletion.
   Validate late settlement and failure/retry paths against the frozen snapshot.
   Reuse the
   genuine original terminal event and exact Backend/Runtime/Gateway ACK and
   cleanup/release contract. No invented historical exit, success, or ACK.
6. Preserve original conversation/messages, test data, unknown row, failure
   verdict, volumes and rollback images. Recover new input eligibility only
   after all independent business and process checks pass. Reuse verified public
   history through the normal recovery path; never resume/replay the old child.

## Verification and execution gates

Source and negative-path tests must cover altered scope/hash/receipt, an unrelated
write tool, additional unknown/pending ingress, unresolved claims, changed
authority, missing or forged cleanup proof, exact repeat and conflicting repeat.
Independent source review and Root approval precede any retained-data operation.
Keep exact source/image/command/readback evidence separate. After recovery,
confirm raw unknown/message preservation, old Root closure, exact ACK and cleanup;
then update only the existing test environment and send the original research
question once. Compare actual financial sources and stage timings, explicitly
qualifying differing data/search conditions. Production stays untouched.

Independent Proposed-design review: PASS for this narrow uncertainty-
acknowledgement design; not implementation, deployment or recovery acceptance.
