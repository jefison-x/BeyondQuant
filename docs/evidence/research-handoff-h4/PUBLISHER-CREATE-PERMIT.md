# H4 publication create permission

2026-09-13, isolated Backend PostgreSQL, local HTTP fakes and Cloudflare workerd/D1 only.

Before the fix, a lost GitHub create reply followed by a temporarily empty catalog issued two POSTs. The regression first reproduced two creates. The same scenario now issues one.

Both existing trusted publishers request a durable `begin-create` permission from their existing authority (Backend for the advanced local publisher; central Hub D1 for Cloudflare). Original event, worker and lease fence are checked; only the first successful atomic consumption returns allowed=true. Expired leases cannot begin a create. Duplicate or lost permission replies do not grant another create. Catalog recovery still reads the original event/snapshot marker and can complete the original Issue.

This is an at-most-once automatic create attempt, not an exactly-once delivery promise. A consumed permission with no recoverable Issue can finish as unresolved/failed; it cannot automatically retry POST even if the original failure was pre-send or rate limiting. No manual reset, second outbox or guessed absence has been added. Existing events migrate conservatively to reconciliation-only; new events start with unused permission. Migration must precede the new worker. Production is unchanged.

Backend crash/reclaim also enforces the existing six-attempt limit. Malformed/truncated/oversized local HTTP results remain transport_ambiguous; socket timeout is not a wall-clock agent deadline.

Validation: Backend feedback family 22 passed, local publisher 11 passed, actual Cloudflare workerd 20 passed plus TypeScript check. Workerd covers authenticated permit requests and two concurrent requests yielding exactly one permission; publisher empty-catalog plus consumed-permit test performs no POST. Deployment planner tests 4 passed and local bundles dry-run required. No actual GitHub issue was created.

New Hub source, tests, migration and deployment scripts are included in the candidate input inventory. H4 full interface and manual-surface qualification remains open; these targeted tests do not close every publisher failure mode or H5 real-model research.
