# Phase 7 slice 3 — consolidate containment into session replay

Status: implementation in the isolated Clean Break worktree; Tester, Reviewer, and Root slice gate pending.

## Decision and boundary

The Gateway currently publishes three owner-scoped views of the same fail-closed containment classification: the `containment` field in `GET /v1/agent/sessions/{id}`, plus standalone `GET .../containment` and `GET .../recovery`. The frontend consumes the session replay API and has no caller for the two standalone paths. The latter adds only `submitted: false` and performs no recovery attempt. The old URLs are listed in the current Product OpenAPI and v0.9 historical evidence, so this is an intentional public contract deletion under the authorized zero-compatibility Clean Break.

Delete only the two standalone GET handlers and their OpenAPI operations. Keep the owner-scoped session replay endpoint and its framework-neutral containment projection. Keep `_session_containment_projection`, `session_containment.py`, Adapter containment evidence, `_resume_lost_reservation`, business idempotency and fail-closed authority decisions. No endpoint alias, redirect, compatibility shim or new runtime state is allowed. Product frontend remains bound only to the Gateway Product API.

## Replacement and historical evidence

The replacement is `GET /v1/agent/sessions/{id}` with its existing `containment` field. Contract tests must prove owner scope, exact interrupted run/trace binding, absence of raw runtime IDs, no recovery submission, and 404 for the removed routes. No backend schema or DSH SDK change is required.

Historical v0.9 observation scripts may continue proving their recorded endpoint was read-only against the exact pre-Clean-Break Git tree; they must stop asserting that this historical URL remains current. Keep their evidence and negative controls, with explicit historical source binding. Current Gateway tests must prove the surviving behavior independently.

The Gateway source and tests are build inputs, so publish a new immutable `.218` build revision and revision-specific Adapter Dockerfile. Preserve `.215`–`.217` byte-for-byte, update default Compose and CI, and reconcile the H4 current interface ledger against the actual two-route deletion. Tester, independent Sol Reviewer and Root acceptance are required before any later Phase 7 deletion. No Phase 8 data or environment cleanup is included.
