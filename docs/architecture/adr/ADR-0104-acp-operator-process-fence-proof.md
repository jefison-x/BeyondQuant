# ADR-0104 — Operator process-fence proof for an unresolved ACP root

- Status: **Proposed** (2026-10-06; awaiting maintainer decision). This is a
  draft decision point, not an accepted contract. No behavior changes until
  accepted.
- Scope: the ordinary Product ACP resource group (ADR-0100) and the dedicated
  judgment ACP root (ADR-0097/0098). Does not change the Backend's
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

## Proposed minimal contract

A trusted, runner-owned operator fence-proof entry that proves an **exact old
runner execution** is stopped and cannot re-execute, without a cleanup receipt:

1. **Runner-instance identity.** The runner persists a durable, signed
   `runner_instance` record on startup (instance id + boot identity + the fixed
   workspace), separate from any per-scope cleanup receipt.
2. **Instance-replacement proof.** A later runner instance, on the same durable
   state, can emit a signed proof that the previous instance owning a scope is
   no longer the current instance and cannot be running: the container/PID
   namespace was replaced, so no process of the old instance can survive. The
   proof binds the old instance id, the new instance id, and the exact scope.
3. **Old-identity invalidation and scope binding.** The proof binds the exact
   one-shot scope (task/call/root/boot/epoch), the exact root identity and the
   old runner instance; a proof for one scope/instance never authorizes another.
   The old instance's scope is one-shot (`_consume_scope`), so it can never
   re-execute.
4. **Business result stays unknown.** The proof settles the business outcome as
   `unknown`/`interrupted`; it never fabricates a result or a historical EXIT.
5. **Exact Backend ACK.** The Backend accepts this proof as the process fence
   only under its existing exact terminal ACK and ingress checks; the receipt
   never replaces the business result check or the terminal ACK.
6. **Fail closed.** Missing, corrupt, wrong-scope, wrong-instance or
   non-replacing proofs keep the root `needs_attention`. No automatic
   `abandoned` state releases the next turn; an operator must explicitly act.

## Explicitly rejected

- Treating "no current process" as a fence proof.
- Forging or replaying a historical EXIT.
- An unproven-fence `abandoned` outcome that releases the workspace without a
  trusted proof.
- Relaxing the Backend `process_fence="stopped"` requirement for ordinary close.

## Consequences

- Defines the production recovery story for a lost runner: which cases are
  closable via a runner-instance-replacement proof and which remain
  `needs_attention`; rebuilding the database is never the recovery.
- Requires runner durable instance records and a Backend acceptance path; the
  exact Backend contract is a follow-up decision once this direction is
  accepted.
