# Phase 38 Chrome MCP Review

Review date: 2026-08-22

Target: isolated real Product stack at `http://127.0.0.1:18765`

Browser: Chrome DevTools MCP, authenticated durable bootstrap admin

## Scope and result

- Reviewed the PostgreSQL/database, budget, runtime, graph, and access/audit
  workbenches against the real Gateway, Backend, Runtime Adapter, and
  PostgreSQL stack.
- Verified the remaining operations routes use the same real bounded
  `operations.v1` projection through frontend/unit/E2E coverage.
- Performed an actual budget-threshold write in the UI. The Product API
  returned `200`, the page reported that an append-only audit was written,
  and the access workbench displayed `budget.threshold.updated` for the
  authenticated administrator.
- Verified the runtime page reports the pinned DSH SDK/runtime version and
  normalized session/usage counts without raw DSH events.
- Verified the graph page is an AgentRun/WorkflowTrace projection and does not
  expose Community checkpoints or raw runtime nodes.
- Reviewed desktop and 390 x 844 mobile layouts. The first mobile pass found
  that hiding the operations sidebar also removed all workbench navigation.
  Phase 38 added an accessible mobile drawer; the second pass opened it,
  navigated to Database Operations, and confirmed it closes after selection.

## Browser boundary evidence

The final preserved Chrome request list contained only same-origin requests:

| Method | Path | Result |
|---|---|---|
| `GET` | `/api/auth/me` | `200` |
| `GET` | `/api/product/settings/status` | `200` |
| `GET` | `/api/product/operations/status` | `200` |
| `PUT` | `/api/product/operations/budget` | `200` |
| `GET` | `/api/product/operations/status` | `200` |

No browser request targeted Backend, MCP, Runtime Adapter, PostgreSQL, Redis,
Tushare, or a DSH endpoint directly. Chrome reported no console errors,
warnings, or browser issues in the final desktop/mobile review.

## Integration defect found and fixed

The first real-Product E2E run returned `503` from the operations overview
when the optional PostgreSQL market-cache table had not yet been provisioned.
Unit tests had created every registered DDL table and masked that startup
state. The operations projection now detects the optional table explicitly,
reports a real empty cache when absent, and has a regression test for that
case. All three real Product API E2E journeys passed after the fix.

## Screenshots

- `01-database-desktop.png` — bounded PostgreSQL facts and domain counts.
- `02-budget-write.png` — real monitoring-threshold write confirmation.
- `03-runtime-desktop.png` — normalized DSH runtime/session diagnostics.
- `04-access-audit.png` — durable administrator group and append-only write
  audit.
- `05-mobile-menu.png` — accessible operations navigation drawer.
- `06-database-mobile.png` — selected workbench after mobile drawer
  navigation.

## Verdict

Chrome MCP review passed. Phase 38 maintains the Product API boundary,
secret-safe/RBAC semantics, real persistence, normalized runtime boundary, and
desktop/mobile operability required by the phase acceptance criteria.

## Local CI

`./scripts/ci/local-ci.sh --base=origin/main --all --with-e2e --with-smoke`
passed all 13 checks after the browser-found fixes. This included the complete
Backend/Gateway/Runtime Adapter/MCP suites, frontend production build, 43
Vitest tests, dependency audit, 10 mocked browser tests, isolated Compose
smoke, and three no-mock real Product API browser journeys.

The same full gate passed remotely in GitHub Actions run
[`32547803282`](https://github.com/jefison-x/BeyondQuant/actions/runs/32547803282)
before merge. The remaining `actions/checkout@v4` Node 20 deprecation message
is a non-failing runner annotation and is outside the Phase 38 product scope.
