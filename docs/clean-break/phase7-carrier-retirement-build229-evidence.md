# Phase 7 — retire executable Agent recovery carriers

Status: bounded local evidence; Phase 7 overall remains OPEN.

## Scope

Base: `56426904` on isolated `clean-break/runtime-simplification` (2026-09-27, Asia/Shanghai). Gateway no longer requests an Agent recovery attempt. This slice removes Backend recovery allocation and target-receipt writeback, and Adapter recovery admission, snapshot anchor, and target receipt. Backend continuation dispatch accepts only the original reservation ID and requires a `reserved` row with no prior `run_id`. The original exact receipt reconciliation, known charge, `outcome_unknown` liability, ordinary first dispatch, root business-call fence, Adapter journal, and Gateway lifecycle delivery remain.

Old persisted recovery rows remain fail-closed: Backend denies a legacy recovery root or pending attempt at the domain-call gate; Gateway still validates a legacy carrier and refuses to dispatch it. The automatic recovery feature is not supported. Auto-review rejected deleting those guard paths because direct deletion could broaden call authority or expose a legacy carrier without sanitization. No rejected deletion was retried.

Immutable `.227` was frozen. `.228` was generated during test qualification, then a test-input correction made it unsuitable as the selected build; it remains byte-for-byte as a frozen, unselected candidate. The selected `.229` embeds the current source and tests; neither prior manifest was rewritten. DSH remains `0.1.5rc1`.

## Verification

- Disposable Gateway image: no-replay and continuation delivery tests **30 passed**.
- Disposable PostgreSQL database and Backend image: carrier rejection plus runtime authority rotation tests **8 passed** after the test setup was corrected to enable the continuation executor and inspect its direct intent projection.
- Disposable `.229` Adapter image: recovery/no-replay and containment tests **12 passed**. Image build `pip check` and DSH SDK/runtime-bin `0.1.5rc1` passed; a one-off container confirmed the embedded `.229` ID and SDK version.
- Historical v0.90 recovery evidence/acceptance tests **24 passed**. Current build and architecture suite **86 passed**. Selected `.229` and frozen `.228` checks passed. Branch whitespace check passed before evidence drafting.
- The first broader Backend run had **30 passed, 2 failed**: the new legacy-row test lacked its executor setup (fixed and rerun in the 8/8 target suite), while `test_terminal_between_claim_and_execution_prevents_write_but_not_receipt_replay` fails in the unchanged `_domain_identity` active-root check before this slice's recovery gate. This unrelated existing expectation was not changed or claimed as passing. The broader suite has not been rerun after the focused repair.
- The dedicated Compose project ended with zero project containers, volumes, networks, and images. Temporary credentials were removed. No existing database, user data, backup, service, push, merge, or deployment was touched.

## Remaining limit

This slice removes executable recovery-carrier paths but retains explicit legacy-row rejection and the live journal → Gateway → Backend domain-call authority fence. The remaining `packages/contracts/business_recovery.py` positive allocation/budget/envelope helpers are unreachable from the live path and still need Phase 7 cleanup; Gateway currently uses its carrier validator as a fail-closed legacy boundary. The Gateway helper's historical forward-authority docstring also needs cleanup. This slice does not prove the final post-deletion authority cutover or `outcome_unknown` across it. Phase 7 overall remains OPEN; Phase 8 remains CLOSED.
