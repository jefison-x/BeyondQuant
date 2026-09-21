# ADR-0082: DSH native continuable-child resume across a BYQ adapter restart

- Status: Accepted
- Date: 2026-09-20
- Accepted: 2026-09-21 (maintainer decision; **modified** — Option 1 chosen, Option 2
  rejected; **NOT implemented**)
- Decision record: `docs/evidence/v090-adr-decisions/README.md` / `decision-record.v1.json`
  (0.9 strict-order step 4 maintainer decision; no GitHub approval is claimed)
- Relates: ADR-0079, ADR-0081, ADR-0058, ADR-0069, ADR-0003
- Stage: D15-4 follow-up
- Evidence: `docs/evidence/d15/d15-4/continuable/`

## Context

D15-4 wired the committed `byq_delegate_*` tools onto the native
`SubagentRuntime.startContinuable` branch in a **candidate-specific** profile
(`plugins/dsh-byq/profiles/dsh-0.1.5rc1-continuable/`) without changing the
production `dsh-0.1.2rc1` selector. Real isolated observations
(`continuable-observations.v1.json`, `native-runtime-isolated`) show:

- the delegate result becomes `{kind: continuable, subagentId}`;
- the child id is a durable child session (descriptor v3, `mode=continuable`);
- the parent receives exactly one settlement per child turn;
- the child is linked to the original delegation call and parent goal;
- a genuinely new OS process cold-resumes the same child (adapter-restart
  analogue), while a child-only SIGKILL stays `BLOCKED` because the only
  continuable providers are in-process.

A separate real isolated trial of the **committed** candidate image
(`continuable-adapter-restart.v1.json`) shows that a fresh BYQ runtime-adapter
process has **no committed surface** that reaches, messages or cold-resumes the
persisted continuable child: the adapter exposes only the root
`resume_session`, and the 0.1.5 Python SDK is byte-identical to 0.1.2 and
exposes no child/subagent/continuable operation. Therefore a BYQ adapter restart
cannot rebind the delegated child, even though the child session file persists.

Rebinding the child across an adapter restart is a **real architecture boundary
change**: it would let BYQ (the runtime adapter) own per-child resume/attach
semantics. That is exactly the kind of change the DSH-boundary and R3-freeze
rules reserve for an ADR before implementation. No such implementation is made
by the wiring PR.

## Decision (accepted by the maintainer on 2026-09-21, modified acceptance — NOT implemented)

The maintainer accepts this ADR **with a modification**: **only Option 1 is chosen**.
Generic child resume / independent child-crash recovery belongs to **DSH**. BYQ does
**not** build a second session store or a generic agent harness.

1. **Chosen — Option 1: a future independent-process continuable provider in DSH.**
   DSH provides an out-of-process provider implementing
   `SubagentProvider.prepareContinuable`, so a continuable child has an independent
   process with a native resume surface. This is **new upstream DSH work**; it does
   **not** exist in the 0.1.5-rc.1 candidate, is explicitly out of scope for D15-4, and
   is **not implemented** by this decision.
2. **Rejected for now — Option 2: a BYQ→native child-resume bridge.** A runtime-adapter
   bridge that, after a restart, reattaches a named child and delivers messages to it is
   **rejected as the current architecture direction**. It would make BYQ own per-child
   attach/epoch fencing and a second session store, violating ADR-0079/ADR-0081 and the
   "do not build a second generic agent harness" rule. Option 2 is recorded as
   **rejected**; it is not authorized now and is not implemented.

**Post-qualification requirement.** Option 1 is a precondition for independent
child-crash recovery. The `subagent-child-crash` and `subagent-byq-adapter-restart`
blockers therefore stay **BLOCKED** until a qualifying out-of-process continuable
provider exists and is qualified. Accepting this ADR resolves nothing by itself.

**Rollback / escape path.** No production change is made. If the future provider does
not materialize, BYQ keeps foreground delegation and leaves the native continuable seam
unexercised; the candidate wiring stays reversible (regenerate the candidate profile
with `backgroundMode: one-shot` / `enableRunInBackground: false`). `R3_RESUME = NO` and
the R3 freeze continue to hold.

Until Option 1 is qualified, D15-4 remains **BLOCKED**, `R3_RESUME = NO`, and
independent child-process capability remains BLOCKED.

## Consequences

- **No production change today.** The candidate wiring is isolated and reversible; the
  production foreground path is untouched, and **neither** a provider nor a child-resume
  bridge is implemented.
- Option 1 introduces a future DSH provider dependency and a new qualification surface
  (packaging, `prepareContinuable`, lifecycle, security review of the provider process).
  BYQ waits for and adapts to that provider; it does not build one.
- Option 2 is rejected, so BYQ does not concentrate native child semantics inside the
  runtime adapter and does not create a second session store.
- The `child-crash` capability (an independently killable child) is still unmet;
  Option 1 is required for that item.

## Alternatives considered

- **Option 2: a BYQ→native child-resume bridge.** Considered and **rejected** for the
  current architecture direction (see Decision): it would make BYQ own per-child
  attach/epoch fencing and a second session store.
- **Keep foreground delegation and do not wire `startContinuable`.** Rejected as
  the D15-4 target: it leaves the native continuable seam unexercised from BYQ.
- **Infer "adapter restart cannot recover" from "the child is in-process".**
  Rejected: cold resume was actually tested and PASSES in a new OS process, so
  the only blocker is the missing BYQ resume surface, recorded with real trials.
- **Persist subagent conversation state in BYQ.** Rejected: BYQ must not own
  subagent conversation state (ADR-0079/ADR-0081); DSH owns residency.

## Migration / rollback

The wiring is revertible by regenerating the candidate profile with
`backgroundMode: one-shot` / `enableRunInBackground: false` (the production
patch already has that shape). No database, worker or production selector
change is involved. Any future **Option 1** implementation must ship its own
rollback and qualification evidence.

## Rejected Option 2 seam (illustrative only, NOT applied)

Option 2 is **rejected for now** (see Decision). An option-2 implementation would
have added a BYQ-owned child-resume seam roughly as follows. This diff is
**illustrative of the rejected direction** and is not part of the wiring PR:

```diff
--- a/services/runtime-adapter/app/runtime.py
+++ b/services/runtime-adapter/app/runtime.py
@@ class RuntimeAdapter
+    def resume_delegated_child(self, session_id: str, child_id: str,
+                               *, generation: int) -> dict[str, Any]:
+        """Reattach a delegated continuable child of a rehydrated root session.
+
+        NOT IMPLEMENTED and NOT AUTHORIZED: ADR-0082 rejects the adapter-owned
+        child-resume bridge (Option 2). Any future implementation requires a new
+        accepted ADR, native DSH attach/resume, epoch/generation fencing,
+        at-most-once settlement, original-goal linkage and orphan cleanup.
+        """
+        raise NotImplementedError("ADR-0082 Option 2 rejected; no BYQ child-resume surface")
```

No such method exists in the committed adapter, which is why the
`byq-compose-adapter-restart` required scenario is truthfully `BLOCKED`.
