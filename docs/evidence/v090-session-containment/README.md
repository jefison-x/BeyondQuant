# BYQ session failure containment and business recovery (ADR-0084)

This evidence slice implements the ADR-0084 replacement hard gate: **BYQ session
failure containment and business recovery**. It is an independent, reversible,
contract-first implementation and acceptance slice. It does **not** implement
native child-process resume, rejected ADR-0082 Option 2, a second generic
harness/session store/PTY runtime, a production selector change, deployment,
release/tag, or Phase 100 resume, and it does **not** create or claim a D15
superseding assessment.

## Implemented scope

- `packages/contracts/session_failure_containment.py` — framework-neutral closed
  contract: loss causes, `interrupted` terminal, generation/epoch/attempt fence,
  terminal settlement guard, a tri-state fail-closed recovery classification,
  and the separation of the execution-boundary assertion from actual
  preservation evidence.
- `services/runtime-adapter/app/containment.py` — bounded, fenced BYQ-owned
  containment evidence ledger under `byq-lifecycle-evidence/containment/`; a
  lost open root is truthfully recorded as `interrupted` with `executor-loss`,
  and a stale executor epoch or a duplicate/reopened attempt fails closed. The
  record carries a framework-neutral trace/run binding and a boundary assertion,
  never a claim of business preservation.
- `services/runtime-adapter/app/runtime.py` — records containment on rehydration
  and fences terminal settlement by the live generation before it can overwrite
  a newer generation's state.
- `services/gateway/app/session_containment.py` — read-only. Derives the truthful
  terminal status from the normalized BYQ WorkflowTrace **plus** the fenced
  adapter containment record, which must match the same session/trace and the
  exact terminal run. There is no attempt ledger and no submit path.
- Product API: `GET /v1/agent/sessions/{id}/containment`,
  `GET /v1/agent/sessions/{id}/recovery` (classification only), and a
  `containment` field on `GET /v1/agent/sessions/{id}`.

## Fail-closed boundaries

- **No client-declared safety.** The public recovery request has no step-safety
  field. Idempotency/result-verifiability must come from server-side
  authoritative action/workflow metadata; that metadata does not exist yet, so
  the classification always fails closed to `paused` and no prompt is submitted.
- **No new authority.** Authority is verified from existing components: the
  owner-scoped Product catalog and the durable Backend auth session. Each item is
  tri-state; `None` (unknown) pauses and is never treated as allowed. Budget
  availability for an arbitrary unanswered turn has no authoritative binding, so
  it is unknown and never defaulted to allowed.
- **No second store.** The `/tmp` attempt ledger was removed. Recovery is
  read-only, so restart/corruption/concurrency cannot reopen an attempt.
- **Interruption is evidence-bound.** An ordinary `session.failed` stays
  `failed`; `cancelled` stays `cancelled`; `discarded` keeps its semantics.
  `interrupted` is projected only when the fenced containment record matches the
  **same session and trace** and, when a terminal exists, the terminal carries a
  **valid `run_id` strictly equal** to the containment `interrupted_run_id`.
  A missing summary session binding, a missing terminal run or an invalid
  terminal run stays the ordinary status. Only a genuinely terminal-free trace
  may project `interrupted` from the fenced containment itself.
- **Preservation is observed, not asserted.** The boundary invariant is
  `boundary_verified: false`; a field is `preserved` only when an authoritative
  catalog/trace read proves it, otherwise `unknown`/`unavailable`.

## Evidence files

- `observations.v2.json` — real observations from the Runtime Adapter synthetic
  compatibility harness (loss + late-success, with real before/after journal
  state), the real Gateway read-only module and the pure contract functions;
  source-digest bound.
- `verdict.v2.json` — fail-able observer verdict (`format_valid=true`,
  `all_pass=true`).
- `negative-controls.v2.json` — 27 negative controls, all rejected; 27
  defect-targeting controls that the pre-fix result-trusting algorithm would have
  reported as PASS.
- `design-check.v1.json` — pre-step authoritative-model inventory and minimal
  design check.

## Delivery status

This PR delivers **containment + fail-closed read-only classification** only. The
full ADR-0084 business-recovery gate (authoritative server-side step-safety +
budget binding + safe rescheduling) remains **`IN_PROGRESS / BLOCKED_INTERNAL`**.
The next sole task is an inventory + minimal design for that authority; if it
requires a new persistence authority, trust subject or cross-Plane call, an ADR
decision must be proposed first. No D15 superseding assessment is started.

## Boundary facts (unchanged)

- B1 `subagent-child-crash` and B2 `subagent-byq-adapter-restart` remain
  `BLOCKED_EXTERNAL`.
- Historical D15-G remains `NO_GO`; historical verdicts are not rewritten.
- `R3_RESUME = NO`; 0.9 is not closed.
- No production selector switch, deploy, release/tag, Phase 100 resume, or
  `#338` change. Native child resume is not implemented; unknown side effects
  pause. Automatic rescheduling remains blocked pending authoritative step-safety
  and budget metadata.
