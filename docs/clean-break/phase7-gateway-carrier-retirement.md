# Phase 7 — Gateway recovery carrier retirement

Status: bounded local candidate; Phase 7 overall remains OPEN.

Base: `92242d06` on the isolated Clean Break branch (2026-09-28).

Gateway no longer imports or forwards the old `recovery_attempt` carrier. Its
historical helper module is deleted. A reservation containing that field can
still undergo exact original receipt/charge reconciliation, then stops before
dispatch or prompt submission. Ordinary first dispatch still uses the original
reservation ID. The Backend's legacy recovery-root domain-call denial remains
in place; no Agent replay or new authorization path was added.

The 0.9 business-recovery observer now loads its captured Gateway source from
fixed Git commit `2f8aca4a877d01481be556236c8f56d6ad7fa290`. Its
committed observations and verdict were not rewritten. The historical test
checks that the old source remains reachable and the product helper is absent.

Focused verification: Gateway image tests for recovery and continuation
delivery **31 passed**; historical business-recovery unittest **12 passed**;
historical observer self-check passed its baseline and negative controls;
`dev-check.py --base 92242d06` syntax/classification passed. Selected DSH
build `.232` binds the changed tree while `.231` remains frozen.

This deletes a dead positive Gateway carrier path only. The live Adapter
journal, Gateway lifecycle delivery and Backend business-call authority fence
are separate Phase 7 work. No database, Compose stack or external service was
changed. No push, merge or deployment occurred.
