# Post-U8 R1 — historical outcomes

Date: 2026-09-07. Status: COMPONENT_VERIFIED_BUILD_GATE_PENDING.
Branch: `fix/post-u8-conversation-recovery`. Product Phase 97 and DSH unchanged.
No remote CI, merge or production rollout is claimed for this slice.

## Red/green and component evidence

The original AgentView regression failed immediately following a new
`session.started`: `.run-failure` disappeared (9 passed, 1 failed).
The fixed view retains operational outcomes independently of current run state
and assistant messages. Later activity does not prove the original task completed.

- Complete frontend unit suite: 51 files / 151 tests PASS.
- TypeScript/Vite production build PASS.
- Complete mocked UI Playwright suite: 20 PASS. An existing workspace journey
  emitted a ResizeObserver warning; this is not claimed as warning-free evidence.
- Regression coverage: shuffled/duplicate replay, cross-session exclusion,
  unknown/prototype-key error codes, private payload exclusion, passive resume,
  later success, and no injected assistant answer.

Architecture/governance suite was run, not skipped: 202 tests, 1 failure and 4
errors. The frozen U7.3 inventory binds all Product source/test files, including
the five changed frontend files. Build/qualification checks therefore correctly
reject current source drift; the mocked image-build test also exits at that
preflight before reaching its fake Docker call. This is NOT a green overall gate.
Historical manifests, reports and selectors are untouched. A separately identified
and qualified post-U8 build is required before merge/deployment; this slice does
not weaken the check or rewrite historical certification.

## Chrome MCP / real Product API

Fresh isolated project `byq-ci-r1-history-20260907` built this frontend and unchanged
dependencies from the worktree. Frontend 18261 / Gateway 18262; separate database,
trace/session volumes and network. Six services, no model/provider keys or workers.
No production data, model call, training, or production deployment.

Synthetic messages used the real ConversationCatalogStore; normalized lifecycle
fixtures used the real TraceStore. These are injected test fixtures, NOT evidence
that a model executed research or that the watchdog/continuation defects are fixed.
Browser requests were not mocked: durable login and same-origin Product API.

Chrome checks passed:

- Initial timeout visible as “运行记录”, not assistant content.
- Later start/cancel/discard/success and reload retained three outcomes.
- Product replay HTTP 200; zero assistant messages introduced by the fixtures.
- Gateway/Runtime restart, logout/login and reopen retained all three records.
- Desktop and 390×844 mobile: no horizontal overflow; timestamps/labels visible.
- Final inspected console: no errors; fetch/XHR origin only `http://127.0.0.1:18261`.
- Second synthetic user: login 200; other owner's conversation 404.

Fixture setup corrections: the first create used user_id instead of username
principal and correctly rolled back; second-user creation initially omitted
actor_role and was correctly forbidden. Both were corrected using existing contracts.
The first timeout fixture predates corrected message insertion; ordering correctly
follows persisted timestamps. No real chronological model run is claimed.

## Limits

Cleanup completed: six test containers, four synthetic data/session/trace volumes,
one network and five project-scoped images removed; exact project-filtered Docker
queries confirmed zero remaining resources. Synthetic fixture data is discarded;
production containers, data, backups and browser contexts were not changed.

R2 unanswered-subject restoration, R3/R4 watchdog/domain lifecycle, R5 progress,
F-series receipts/reconciliation/continuation and S-series pools remain open.
No model input, authorization, timer or DSH behavior changes. Deployment has a
separate gate; CI classification optimization and data expansion remain deferred.
