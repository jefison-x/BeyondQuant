# Phase 13 Product reset feature checklist

Status: candidate; local real browser acceptance passed. All state below is from
the isolated Phase 13 branch and disposable test resources.

| User-visible requirement | Current evidence | Gate |
| --- | --- | --- |
| Signed-in user finds Runtime and Workspace reset in account menu | Vue route/menu tests; real browser reached reset page after login | PASS |
| Runtime reset requires confirmation and preserves research data | Frontend tests; Gateway contract; real browser confirmed runtime reset and read back its ResearchTask | PASS |
| Workspace reset requires exact typed confirmation | Frontend tests; real browser entered phrase before submitting | PASS |
| Browser uses only Gateway Product API with durable user cookie | Gateway auth tests; real browser same-origin assertion and protected page reload | PASS |
| Active Job or unknown external outcome keeps business data | Disposable PostgreSQL Backend tests | PASS |
| Completed Job, research and Artifact graph is removed | Disposable PostgreSQL Backend Product reset test | PASS |
| Exact Workspace scope, release proof and request replay | Disposable PostgreSQL Backend and Gateway tests | PASS |
| Second Workspace and account remain after current Workspace reset | Disposable PostgreSQL Backend scope test; browser protected page reload for account | PASS |
| Real browser resets Runtime then Workspace through Gateway/Product API | Single Playwright case on fresh isolated six-service project, 1/1 PASS | PASS |

Product reset deletes database references in its transaction. Physical Artifact
blobs are collected separately by a global-reference-safe GC pass; request
completion does not claim immediate file deletion.
