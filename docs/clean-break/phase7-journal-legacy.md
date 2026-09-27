# Phase 7 slice 9 — discard historical journal adoption

Base: `766f9a10` on `clean-break/runtime-simplification`.

## Boundary and deletion

The current v4 lifecycle journal records bounded BYQ root authorization
evidence. Gateway delivers an exact terminal to Backend, which closes the
domain-call authority and acknowledges it before another turn is admitted.
Adapter process loss does not resume a DSH Agent or replay its prompt.
Deleting that live delivery without a replacement would leave Backend roots
active; it is outside this slice.

This slice removes automatic v1–v3 journal migration, boot-bound lease
adoption, manual reanchor and stale-session archive operators, their tests and
the obsolete runbook. The old session data is disposable under the accepted
Clean Break baseline. New journal reads require the exact v4 envelope and
stable executor fields; missing epoch state with any existing journal fails
closed. The current v4 lock, epoch write fence, terminal ACK, prompt receipt,
and process-loss root closure remain.

No database table, volume, container, DSH API or Product API changes. No old
journal is migrated. The deleted scripts have no current source, CI or test
callers; roadmap and ADR-0078/0079 mentions are historical records.

## Focused acceptance

- v1–v3 envelopes are rejected without rewrite; missing executor epoch with
  any existing journal cannot bootstrap a new identity.
- Fresh v4 journals, exact ACK and old-epoch writer fencing still work.
- Current `.224` build identity binds the changed source; `.223` is frozen.
- Root/Backend authorization delivery remains in place. A real killed-Adapter
  wire journey needs a live Backend and is a later integration gate if its
  environment is unavailable for this source-only slice.

Tester, Reviewer and Root evidence is recorded in [phase-gates.md](phase-gates.md).
