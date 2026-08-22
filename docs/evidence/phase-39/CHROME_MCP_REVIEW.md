# Phase 39 Chrome MCP Review

Review date: 2026-08-22

Target: isolated real Product stack at `http://127.0.0.1:8767`

Browser: Chrome DevTools MCP, authenticated durable bootstrap administrator

## Scope and result

- Created the Tushare system credential through the UI and verified the page
  showed only mask `…oken`, active state and version 1.
- Executed the bounded connection test. Backend reached a controlled Tushare
  protocol fixture and returned `passed`, one row and endpoint metadata without
  exposing the Token.
- Submitted a real asynchronous range sync for `000001.SZ`, observed the
  durable job transition to `completed`, and inspected its per-symbol outcome.
- Verified the PostgreSQL coverage projection reported one row, one symbol,
  observed range `20240102 — 20240102`, and zero source/OHLC issues.
- Verified the page explicitly declines to claim historical completeness
  without a trading-calendar basis.
- Reviewed desktop and 390 x 844 mobile layouts. Summary cards, tabs and the
  configured-source/coverage content remained readable and operable without
  horizontal viewport overflow.

The protocol fixture replaced only the external Tushare network dependency.
Authentication, Product API, Backend credential encryption/resolution,
background execution, PostgreSQL persistence and frontend projections were
real and unmocked.

## Browser boundary evidence

The Chrome request log contained the Phase 39 calls below, all same-origin:

| Method | Path | Result |
|---|---|---|
| `GET` | `/api/product/data-center/status` | `200` |
| `POST` | `/api/product/data-center/source/credentials` | `201` |
| `POST` | `/api/product/data-center/source/test` | `200` |
| `POST` | `/api/product/data-center/sync-jobs` | `201` |
| `GET` | `/api/product/data-center/sync-jobs/{job_id}` | `200` |

No browser request targeted Backend, MCP, DSH, PostgreSQL, Redis or Tushare
directly. Chrome reported no console messages after the complete journey. The
initial unauthenticated `/api/auth/me` request returned the expected `401`
before durable login; authenticated requests returned `200`/`201`.

## Screenshots

- `screenshots/01-source-configured.png` — configured source with masked Token.
- `screenshots/02-sync-completed.png` — completed job and per-symbol result.
- `screenshots/03-coverage-audit.png` — honest observed coverage and quality.
- `screenshots/04-mobile-coverage.png` — responsive mobile coverage review.

## Verdict

Chrome MCP review passed. Phase 39 satisfies the real Product API, durable
persistence, RBAC, secret-safety, provider-boundary and responsive browser
acceptance criteria.

## Local CI

`./scripts/ci/local-ci.sh --base=origin/main --all --with-e2e --with-smoke`
passed all 13 checks after the browser and self-review fixes. This included 43
architecture tests, the complete Backend/Gateway/Runtime Adapter/MCP suites,
frontend production build, 44 Vitest tests, dependency audit, 10 mocked browser
tests, isolated Compose smoke, and three no-mock real Product API journeys.
