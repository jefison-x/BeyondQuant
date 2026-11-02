# Feedback status and Runner test maintenance — 2026-11-02

Status: **PASS for isolated local feedback verification and Runner test maintenance.**
Formal Hub and browser end-to-end verification remain **NOT_RUN**.

## Scope and authorization

The maintainer requested the feedback post-review return path, global usage
aggregation and Runner test follow-ups, reusing the existing environment and
evidence while preserving the current page. The maintainer subsequently stopped
usage work: “无需汇总了。直接下一步。” No usage implementation was written or retained.
For feedback the maintainer chose isolated local verification and explicitly
left formal Hub verification unaccepted.

This maintenance follows the completed Phase 17 technical acceptance. It does not
reopen that phase, define Phase 18, publish images, deploy services, send a new
external feedback report, moderate a Hub item or create a GitHub Issue.

## Runner

The original two failures were reproduced in the retained Runner image, with
network disabled, no-new-privileges enabled, read-only source and an ephemeral
temporary filesystem. Both requests were correctly rejected, but their final
assertions incorrectly expected the already-initialized state directory to be
empty. The new assertions snapshot its directories/file bytes after startup and
require them to remain unchanged after rejection. Signed rejection, no session
directory creation and no process launch remain explicit assertions.

The original source produced **2 FAIL**. The affected nodes then produced
**2 PASS**, followed by independent execution of the complete Runner test module:
**20 passed, 0 failed**. Runner application code is unchanged. Historical broad
failures and missing original file logs are retained; the new reproduction and
verification have separate logs.

## Feedback return path

The existing Backend and Relay already implement receipt-bound status polling,
authenticated return, durable status and owner-scoped projection. No product
logic or endpoint was changed. New coverage verifies accepted/rejected Relay
responses and rejected status persistence, token hiding, owner isolation and
removal of rejected receipts from subsequent status candidates.

The local ASGI scenario exercises draft/preview/submit, authenticated receipt
completion, status claim, unauthorized-return rejection without state change,
authenticated synthetic Hub rejection, duplicate return and owner readback.
It is Backend ASGI/isolated PostgreSQL plus a synthetic Hub response, not a
formal Hub request, real browser journey or newly sent feedback.

The retained test admin/workspace has no reusable Hub outbox row. Historical
formal receipt tokens and the old temporary database were removed; hashes alone
cannot authorize a real status read. Formal Hub post-review return remains
**NOT_RUN**, as agreed by the maintainer.

Two earlier host Relay test attempts stopped during collection because the
shared `feedback_http_deadline` module was absent from that command's import
path. No test body or network request ran; those failures have tool-transcript
evidence only, file logs NOT_CAPTURED. Recovery uses the existing CI container
mount/PYTHONPATH layout, with network isolation added for this local batch.
No replacement harness or collector was introduced.

Independent Tester: Backend feedback store/API modules **13 passed, 0 failed**;
full Relay module **10 passed, 0 failed**, including accepted/rejected status
refresh. Both exited zero. The Backend used a new test-only PostgreSQL database;
the Relay container had network disabled. These results close the agreed local
return-path verification, not the unperformed formal Hub flow.

## Evidence and preservation

Local receipts are under `.ci-artifacts/maintenance-feedback-usage-runner-20261102/`:
`runner-before.log`, `runner-after.log`, `runner-full-tester.log`,
`tester-runner.md`, `feedback-work.md` and `feedback-current-inventory.json`.
`tester-runner.md`, `backend-feedback-tests.log`, `relay-tests.log`,
`tester-feedback-roundtrip.md` and `independent-review.md` record the complete
commands, exits and boundaries. Independent Reviewer: Functional PASS within
the local scope, Tests PASS, Clean Break Architecture PASS. Root accepts these
two maintenance items locally; remote PR CI and merge gates remain separate.

Existing services, browser tabs/current page, Product database, volumes, user
identity and earlier evidence are preserved. Feedback tests use a separate
test-only PostgreSQL database. No runtime aggregate, user execution option or
ordinary model configuration was changed.
