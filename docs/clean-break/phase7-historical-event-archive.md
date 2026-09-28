# Phase 7 slice 5 candidate — archive obsolete event contract and P4 harness

Status: design and implementation slice gate PASS. The same-slice pre-deletion contract ran RED on the eight scoped archive paths while the live ResearchTask action/approval boundary passed. After deletion, the archive contract passed 3/3; PostgreSQL 45/45, Gateway 275/275, repository unittest 868 OK (11 skipped), current/frozen builds, historical release, H4 and independent Sol review passed. Root accepts this slice only. This document does not authorize Phase 8 or a DSH Agent-continuation replacement.

## Ownership and reason

Slice 4 moved the live plan-approval handoff to BYQ-owned `research_task_actions` and removed the production event-state ledger. `packages/contracts/research_continuation_event.py` now has no production import; its remaining import is a test of that obsolete contract. The P4-A/B/C1 scripts are coupled historical harnesses that query the removed table. Retaining executable names in the current tree suggests the obsolete ledger is still a supported runtime path.

## Exact candidate scope

Remove as one unit:

- `packages/contracts/research_continuation_event.py` and `services/backend/tests/test_research_continuation_event_contract.py`;
- `scripts/v091/continuation_p4`, `scripts/v091/continuation_p4b`, `scripts/v091/continuation_p4c1`;
- `tests/test_v091_continuation_p4.py`, `tests/test_v091_continuation_p4b.py`, `tests/test_v091_continuation_p4c1.py`.

Preserve historical evidence JSON, accepted historical records, frozen build manifests `.215`–`.219`, pinned historical release input commits, and current business-action runtime. Update all three P4 evidence README replay instructions and the runtime-adapter test docstring that point at removed scripts: state that the original replay source is available at commit `2f8aca4a877d01481be556236c8f56d6ad7fa290` and that the old harness is not a current acceptance gate. Do not copy the harness to another current path.

## Build identity

The selected `.219` manifest hashes the candidate files. Create `.220` from the post-removal tree, with a revision-specific runtime-adapter Dockerfile and selected Compose/CI references. Preserve `.219` manifest and Dockerfile bytes and add `.219` to `FROZEN_BUILDS`; expand `tests/test_current_build_revision.py` frozen checks through both `.218` and `.219`. Update the `docs/roadmap/STATUS.md` current build marker from `.219` to `.220`. Preserve `compose.yml` and the historical DSH release descriptor. Do not rewrite old manifests or silently reuse an old image.

## Acceptance

Before deletion, add and run a same-slice contract/architecture test that fails on the current tree. It must assert that the obsolete contract and all three coupled P4 script/test groups are absent, the live ResearchTask action and approval boundary still exists, and each retained evidence replay pointer resolves to a Git blob at the pinned pre-archive commit. Then perform the deletion and require that test to pass. This is the Phase 7 entry gate from `docs/clean-break/ownership-and-deletion-plan.md`.

- Static search: no production import or current runtime reference to the old event contract/table; no broken current-tree import of removed P4 modules.
- Current `.220` build check PASS; frozen `.215`–`.219` checks PASS; historical DSH release input check PASS; Compose selected build resolves to `.220`.
- Backend PostgreSQL regression for ResearchTask actions and plan approvals PASS; complete Gateway suite PASS; repository unittest and architecture checks PASS.
- H4 reliability review remains complete with zero missing, stale or fake-pass entries; evidence records remain readable and replay pointers name the frozen commit.
- Independent Sol Reviewer directly checks the deletion, manifests, public interfaces, tests and Clean Break boundaries. Root accepts this slice explicitly before any next slice or Phase 8.

## Explicit limits

This archive does not add DSH attach/resume/status or durable child rebind. `waiting_for_agent` and `needs_attention` remain visible unresolved business states. Phase 7 overall remains open; Phase 8 cleanup remains closed.
