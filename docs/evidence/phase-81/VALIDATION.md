# Phase 81 Validation

Validated on 2026-08-30 against merged `main` and the production Compose stack.

## Automated checks

- Runtime Adapter: 53 tests passed.
- Gateway: 75 tests passed.
- Frontend: production build passed; 43 files / 124 unit tests passed.
- Mocked Playwright: 18 journeys passed.
- Selective local CI: all 10 selected checks passed.
- PR #190 full risk-selected CI: all checks passed, including Backend PostgreSQL, Gateway, Runtime
  Adapter, MCP, frontend, 18 mocked browser journeys, six real Product browser journeys, full Compose
  smoke, worker restart persistence, two-user isolation and run-scoped resource cleanup.
- `git diff origin/main --check` passed after the documentation whitespace correction.

## Real durable-conversation journey

1. The merged stack started with all ten services running; every service that declares a healthcheck
   reported healthy. Frontend `/healthz` and Gateway `/readyz` returned success.
2. A temporary administrator-owned Product conversation sent: `请记住校验词“海棠七号”，只回复“已记住”。`
   Xiaoba completed the first turn with `已记住`.
3. Chrome navigated away, closing the Product event stream. After the configured 30-second idle window,
   an exact internal release probe returned 404, proving that the original Runtime session/process was
   already absent.
4. Chrome reopened the same durable Product conversation and sent: `刚才的校验词是什么？只回复校验词。`
   A fresh Runtime generation completed normally with `海棠七号`; the previous instant
   `model-run-failed` regression did not recur.
5. The exact temporary conversation was deleted through owner-authenticated Product API after review.
   Existing user conversations and domain data were not changed.

The journey proves stable Product identity, fresh private DSH generation, bounded public-context
rehydration, successful contextual follow-up and owned process cleanup without reading raw DSH state.
