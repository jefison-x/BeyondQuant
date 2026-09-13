# H4 shared short metadata transaction

2026-09-13. This is common-mechanism consolidation, not a newly counted production Bug.

Research, credential, personal policy and feedback stores previously duplicated short transaction lock acquisition, SET LOCAL timeouts, rollback/error mapping and lock release. They now explicitly call `app.db.bounded_metadata_transaction`; shared constants define a two-second lock wait and five-second SQL statement limit. Each domain retains its own public persistence error and message. Credentials explicitly preserve IntegrityError for their existing unique-key-to-domain-conflict mapping.

This follows ADR-0016's existing shared SQL layer. No new repository abstraction or Agent harness, no business transition relocation, and no automatic retries were added. PgStoreMixin default behavior and other stores are unchanged. Connection pool/connect waits, complete research duration and cross-service recovery are not claimed bounded by these two constants.

Verification:

- Seven common-function contracts passed: successful commit, failed lock acquisition without releasing an unowned lock, SQL failure rollback, commit failure mapping, explicit integrity exception preservation/default mapping, and original domain exception propagation.
- Twenty-three affected-domain test files: 152 passed against isolated PostgreSQL, including real lock contention, independent-store concurrency, original receipts, permissions and recovery after restart.
- Source review confirms changes in four stores are transaction delegation and imports only. Seventy-five existing interface entries now track the shared db.py dependency so shared implementation drift invalidates their prior review.

Remaining common-mechanism review: frontend pending-command persistence has domain-specific differences (credentials never persist secrets; profile creation uses exact normalized input; paper imports have a larger payload bound). Those must retain explicit contracts when consolidating repeated storage mechanics. No blanket pass is inferred for unreviewed interfaces.
