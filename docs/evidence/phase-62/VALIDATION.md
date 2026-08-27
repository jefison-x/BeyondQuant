# Phase 62 validation evidence

Date: 2026-08-27 (Asia/Shanghai)

## Scope and boundaries

- Branch: `phase/62-user-experience-polish`
- Base: `c0c6068490d19b871fc023f054461cfcbf4fcaeb`
- Browser frontend: real Vite 8 application from the isolated worktree at
  `http://127.0.0.1:15174`
- Product services/data: healthy local production Gateway and restored PostgreSQL, reached only
  through the frontend same-origin `/api` proxy
- Community repository was inspected read-only; no Community code, data or Git history changed.

## Closed P3 findings

- `BQ-UX-011`: Data Center can now load an owner-scoped persisted Stock Pool, resolve current
  direct/snapshot members, and let the user choose at most 20 symbols before readiness. A larger
  pool is never silently represented as fully checked.
- `BQ-UX-012`: the ordinary dashboard and navigation no longer lead with Backend, Artifact ID,
  Job ID, Product API, Gateway, WorkflowTrace or the mixed-language “Agent 策略” label. Admin
  diagnostics retain precise engineering nouns.
- Frontend bundle warning: ChartWrapper now uses the official modular ECharts entry and Vite 8
  Rolldown `codeSplitting`. The largest JS chunk is `ui-components` 435.55 kB; chart chunks are
  279.82 kB and 207.58 kB. The default 500 kB warning is no longer emitted.

## Automated verification

- Architecture: 50 passed (`python3 -m unittest discover -s tests -p 'test_*.py'`).
- Frontend: 36 files / 88 tests passed.
- TypeScript + Vite production build: passed with no chunk-size warning.
- Mock Playwright: 15 passed.
- Phase 62 real Chromium: 1 passed.

## Real browser verification

The real browser selected persisted pool “Phase58 复验银行池”, populated its two members, sent a
bounded readiness Product request and received HTTP 200 with an honest `部分受限` result. The same
journey verified the ordinary Dashboard lacks the six blocked engineering labels and opened an
existing completed Backtest whose modular ECharts canvas rendered. After login there were zero
Console errors and zero HTTP 5xx responses. The expected pre-login `/api/auth/me` 401 was excluded
under the existing acceptance rule.

- [Stock Pool readiness](screenshots/01-stock-pool-readiness.png)
- [Modular Backtest chart](screenshots/02-modular-chart.png)

## Acceptance

Phase 62 closes the remaining acceptance-report P3 items in scope. It does not add strategy-driven
automatic simulation, live brokerage, a new Provider or a new runtime/domain contract.

