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
  terminal settlement guard, bounded recovery classification and old-to-new
  attempt lineage.
- `services/runtime-adapter/app/containment.py` — bounded, fenced BYQ-owned
  containment evidence ledger under `byq-lifecycle-evidence/containment/`; a
  lost open root is truthfully recorded as `interrupted` with `executor-loss`,
  and a stale executor epoch or a duplicate/reopened attempt fails closed.
- `services/runtime-adapter/app/runtime.py` — records containment on rehydration
  and fences terminal settlement by the live generation before it can overwrite
  a newer generation's state.
- `services/gateway/app/session_containment.py` — derives `interrupted`,
  recovery eligibility, pause reason and attempt lineage from the normalized BYQ
  WorkflowTrace and the durable adapter containment summary only (never a raw DSH
  event), with a file-locked attempt ledger that yields exactly one authoritative
  attempt.
- Product API: `GET /v1/agent/sessions/{id}/containment`,
  `POST /v1/agent/sessions/{id}/recovery-attempt`, and a `containment` field on
  `GET /v1/agent/sessions/{id}`.

## Recovery classification (fail closed)

Cancel, budget exhaustion, revoked authorization and owner/workspace mismatch
block recovery. A confirmed success receipt is `settled` and is never replayed.
A non-idempotent or non-reconcilable side effect is `paused` with a user-visible
reason and is never auto-retried. Only a step the contract explicitly declares
idempotent **and** result-verifiable, with no existing receipt, may create at
most one bounded, auditable attempt; concurrent requests converge on one.

## Evidence files

- `observations.v1.json` — real observations from the Runtime Adapter synthetic
  compatibility harness (loss + late-success), the Gateway attempt ledger and the
  pure contract functions; source-digest bound.
- `verdict.v1.json` — fail-able observer verdict (`format_valid=true`,
  `all_pass=true`).
- `negative-controls.v1.json` — 20 negative controls, all rejected; 19
  defect-targeting controls that the pre-fix result-trusting algorithm would have
  reported as PASS.
- `design-check.v1.json` — pre-step authoritative-model inventory and minimal
  design check.

## Boundary facts (unchanged)

- B1 `subagent-child-crash` and B2 `subagent-byq-adapter-restart` remain
  `BLOCKED_EXTERNAL`.
- Historical D15-G remains `NO_GO`; historical verdicts are not rewritten.
- `R3_RESUME = NO`; 0.9 is not closed.
- No production selector switch, deploy, release/tag, Phase 100 resume, or
  `#338` change. Native child resume is not implemented; unknown side effects
  pause.
