# H4 shared pending-request storage bounds

2026-09-13. Eight frontend domain modules now call the same bounded storage read/write functions: research task, pool, paper account, feedback, feedback moderation, credential metadata, model profile and personal policy.

The common helper only checks serialized text length and accesses browser storage. Domain modules retain original key generation, owner/workspace namespace, field validation, pending-intent equality, receipt validation and completion rules. Credential requests still persist an allowlisted metadata object, never the secret; model profiles retain exact normalized input matching; paper import retains its larger limit. No generic submitter, Agent scheduler or automatic retry has been added.

Existing limits retain their JavaScript string-length semantics (UTF-16 code units), not a new claim about UTF-8 network bytes. Backend request limits still apply separately. Research pending text now has a 32,768-character cap before JSON.parse and before storage. This accommodates escaped valid title/objective limits while rejecting oversized stored extras before parsing. Storage failures propagate before a caller can send its mutation. This helper does not make localStorage transactional across browser tabs.

Validation:

- Nine storage/API test files, 24 tests passed: original identity retention, namespace isolation, payload equality, sensitive-field exclusion, failure before submission, oversize preservation and research parse-before-bound prevention.
- Production Vue/TypeScript build passed.
- Nine real-browser flows through isolated Gateway/Product API passed (30.1 seconds): credential, profile, binding/delete, feedback draft, account/order, account import, rejected retry retaining unknown state, five personal-policy commands and pool creation. Lost replies were injected after actual Backend commits; refresh used original receipts. No production or external provider calls.

This is shared-mechanism consolidation and one pre-parse bound addition, not eight newly discovered production bugs. The H4 full interface ledger and H5 real-model research remain incomplete.
