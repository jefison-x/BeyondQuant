# H4 feedback moderation recovery

2026-09-13, isolated Product API/Backend PostgreSQL and managed Chromium; no production or real GitHub writes.

Administrator triage/accept/reject/duplicate now retain the original action, feedback ID, expected version, rationale, canonical target and request key before sending. Unknown results survive refresh under the original authenticated subject/workspace. New moderation is blocked while a command remains unresolved. Read-only recovery queries the original actor/action/key receipt rather than treating current object state as the original result. Explicit retry uses the identical original request. Definite first-attempt rejection may clear that command; an unknown operation is not replaced by a fresh key.

Backend receipt lookup requires admin and exact actor; the original moderation result survives subsequent transitions and store restart. Gateway builds moderator headers from durable login. Receipt validation checks original feedback ID, resulting status and expected version+1. The unused old moderation submit helper was removed, so the active page has one command path. Feedback options now use the same safe storage-error mapping as other feedback handlers.

Validation:

- Backend recovery plus feedback API: 5 passed; original triage receipt survives accept and restart, other actor cannot read it, non-admin rejected, one publication outbox retained.
- Gateway feedback contract: 2 passed; new read requires current admin and forwards no workspace identity.
- Frontend API/storage: 7 passed including HTTP request-ID fallback, unknown original retention, wrong-result rejection and identical-key retry. Vue/TypeScript production build passed.
- Real browser: four moderation actions across six transitions; each POST completed on the actual Backend but its response was dropped. Each refresh retained pending state, each GET recovered the original receipt, total POST count stayed six. Final read/retry button variant reverified on a fresh synthetic administrator (21.8 seconds). Existing snapshots were not fabricated. Earlier browser failures were test locator ambiguities (Element Plus select/overlapping prompts), corrected before passing.

Feature checklist: durable login + Product-only browser access PASS; persisted original moderation PASS; refresh recovery PASS; cross-actor isolation PASS; duplicate-action prevention while unknown PASS; explicit retry uses original request PASS (API contract); real external publication NOT RUN / not authorized.

This closes the specific moderation recovery gap, not the full H4 interface inventory or H5 real-model research. Shared request/unknown/result conventions still need a cross-family reuse audit.
