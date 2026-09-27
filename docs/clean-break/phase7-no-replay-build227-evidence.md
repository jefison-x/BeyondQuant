# Phase 7 — no automatic lost-turn replay and immutable build identity repair

Status: bounded local evidence; Phase 7 overall remains OPEN.

## Scope

Base: `efd16e29` on isolated `clean-break/runtime-simplification` (2026-09-27, Asia/Shanghai). The Gateway continuation consumer no longer sends the original instruction again after an accepted or `outcome_unknown` Agent turn loses its exact prompt receipt. It still reconciles that original receipt, records a known exact charge, and permits an ordinary `reserved` first dispatch. A stale recovery carrier fails closed. This is an ADR-002 Agent replay boundary change; it does not delete the still-live Backend/Adapter recovery carrier implementation or the root business-call authorization fence.

A separate build-identity repair freezes `.226` byte-for-byte, selects new immutable `dsh-0.1.5rc1-post-u8.227`, and updates the Compose/CI selectors and current-build tests. The `.227` Dockerfile differs from `.226` only in its embedded manifest path. The branch's inherited Backend approval-contract test had one extra EOF blank line, which was removed.

## Focused verification

- Isolated Gateway Compose test image, no dependencies or database started: `tests/test_business_recovery.py` and `tests/test_task_continuation_delivery.py` — **30 passed**. The first run had 29 passed and one failure in an inherited contradictory restart test: it forbade `_restore_product_session` while expecting that function's live attachment and trace reopen. The corrected test checks `attach_live_only=True`, the original runtime IDs, no prompt, and the missing-session path. The second run passed 30/30.
- Build revision `create` produced `.227` manifest SHA-256 `13e0c76bce80fcb46e86617cbf40cd0f67dd699a5391f4fd938edf08f1be6961`. Current `check` and frozen `.225`/`.226` checks passed. Worker ran 13 focused build/current-artifact/retirement/CI architecture tests — **13 passed**.
- Root's disposable Compose config resolved the `.227` Dockerfile and only project-prefixed, non-external resources. The Runtime Adapter image built successfully with `pip check` and exact DSH SDK/runtime-bin `0.1.5rc1`; a one-off Adapter container read its embedded manifest and confirmed `.227` and the SDK version.
- The Gateway test project and Adapter build project each ended with **zero** project containers, volumes, networks and images. Both temporary credential directories were removed. No existing database, user data, backup, service, push, merge or deployment was touched.

## Remaining limit

This test proves the Gateway no-replay branch and current image identity, not removal of all Backend/Adapter recovery carriers. It does not prove the final journal → Gateway → Backend authority-fence replacement or the post-deletion `outcome_unknown` gate. Phase 7 overall remains OPEN; Phase 8 remains CLOSED.
