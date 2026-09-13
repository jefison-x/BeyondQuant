# H4 feedback Hub delivery recovery

2026-09-13; isolated test databases and loopback HTTP only. No production Hub/GitHub writes.

## Changes and evidence

- Crash/reclaim cannot exceed the existing eight delivery attempts. Original event and snapshot remain available when exhausted; exhaustion is not a successful delivery.
- Delivery callbacks retain worker/fence validation. Old workers cannot complete replacement leases. Malformed or lost HTTP success replies remain unknown and retry the original event; canonical Hub receipt validation precedes completion.
- Feedback metadata transactions use a two-second process/row lock wait and five-second SQL statement limit with safe 503 rollback. These are storage bounds, not a total agent or HTTP wall-clock deadline. Relay HTTP uses a 12-second socket timeout and a 64 KiB response cap.
- Status callbacks lock the original receipt. Published receipts cannot regress or change issue identity. Publishing to accepted remains allowed for the existing Hub publisher retry contract.
- POST `/internal/feedback-hub/status-checks/claim` reserves at most 20 eligible status checks for 30 seconds in PostgreSQL. Failed reads and relay restarts preserve this wait so later receipts can be queried. Existing GET candidates remains a read-only diagnostic; relay polling uses the new claim.
- Six Backend recovery tests include restart, lost callback, lease replacement, retry exhaustion, actual row lock timeout, fair polling and authenticated API validation. The broader feedback set previously passed 17 tests before the added API contract; parameter validation uses the existing 422 response contract.
- Six relay tests include real loopback HTTP commit then connection loss, replacement worker with identical original event, bounded malformed success and status claim ordering.
- Unchanged actual Cloudflare workerd Hub suite: 19 tests passed, including original installation/event deduplication. Local fake HTTP tests alone are not claimed as Hub qualification.

## CI boundary

Build .90 CI run 34745642538 passed MCP but failed integration because the real browser assertion matched two succeeded materialization rows. This batch changes that UI assertion to allow multiple history records while retaining Product API polling scoped to the newly created pool and member verification. A new CI run is required; older green checks do not qualify these changes.

H4 remains incomplete. This evidence does not qualify local/Cloudflare GitHub publisher ambiguous-create recovery, all MCP tools, or the real-model H5 research scenario.
