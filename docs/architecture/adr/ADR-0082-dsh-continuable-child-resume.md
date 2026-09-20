# ADR-0082: DSH native continuable-child resume across a BYQ adapter restart

- Status: **Proposed (DRAFT for review — NOT accepted, NOT implemented)**
- Date: 2026-09-20
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

## Decision (proposed, not implemented)

If BYQ is to rebind a delegated continuable child across an adapter restart, the
maintainer must first accept an ADR that chooses **exactly one** of:

1. **A future out-of-process continuable provider** in DSH that implements
   `SubagentProvider.prepareContinuable`, so a continuable child has an
   independent process with a native resume surface. This is new upstream
   provider work and is explicitly out of scope for D15-4 (no provider is added).
2. **A BYQ→native child-resume bridge** in the runtime adapter that, after a
   restart, asks the DSH runtime to reattach a named child and then delivers
   messages to it. This makes the adapter responsible for child attach/epoch
   fencing and must include: child-id persistence owned by BYQ contracts,
   exactly-once settlement, original-goal linkage, orphan cleanup, and an
   epoch/generation fence so a stale writer cannot duplicate work.

Option 2 is closer to the R3 supervisor definition (native attach/resume,
epoch fencing, cleanup) but must **not** become a second session store or a
second generic agent harness. Option 1 keeps the process boundary independent,
which the current D15-4 `child-crash` item would also require.

Until an option is accepted, D15-4 remains **BLOCKED**, `R3_RESUME = NO`, and
independent child-process capability remains BLOCKED.

## Consequences

- **No production change today.** The candidate wiring is isolated and
  reversible; the production foreground path is untouched.
- Choosing option 1 introduces a new DSH provider dependency and a new
  qualification surface (packaging, `prepareContinuable`, lifecycle, security
  review of the provider process).
- Choosing option 2 concentrates native child semantics inside the runtime
  adapter, which risks duplicating DSH state; the ADR must define the hard
  boundary that prevents a second session store and must specify the epoch
  fence, at-most-once settlement and cleanup semantics.
- Neither option removes the need for the `child-crash` capability (an
  independently killable child); option 1 is required for that item.

## Alternatives considered

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
change is involved. Any future option-1/option-2 implementation must ship its
own rollback and qualification evidence.

## Unimplemented change this ADR would gate (illustrative only, NOT applied)

A future option-2 implementation would add a BYQ-owned child-resume seam roughly
as follows. This diff is **illustrative** and is not part of the wiring PR:

```diff
--- a/services/runtime-adapter/app/runtime.py
+++ b/services/runtime-adapter/app/runtime.py
@@ class RuntimeAdapter
+    def resume_delegated_child(self, session_id: str, child_id: str,
+                               *, generation: int) -> dict[str, Any]:
+        """Reattach a delegated continuable child of a rehydrated root session.
+
+        NOT IMPLEMENTED. Requires an accepted ADR: candidate-specific only,
+        native DSH attach/resume, epoch/generation fencing, at-most-once
+        settlement, original-goal linkage and orphan cleanup.
+        """
+        raise NotImplementedError("ADR-0082 not accepted; no BYQ child-resume surface")
```

No such method exists in the committed adapter, which is why the
`byq-compose-adapter-restart` required scenario is truthfully `BLOCKED`.
