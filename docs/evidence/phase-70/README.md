# Phase 70 — Index catalogue coverage closure

Phase 70 closes the single-index Product gap under ADR-0042:

- six canonical BYQ index candidates with alias deduplication;
- trusted Data Worker synchronization over a bounded 62-day window;
- per-index failure isolation and persisted bounded run summaries;
- exact `(index_symbol, snapshot_date)` member/weight/hash evidence;
- forward verification of existing monthly data;
- Product API, Data Center and Stock Pool selectable/waiting projections.

Validation on 2026-08-29:

- `scripts/ci/local-ci.sh --only=backend,gateway,frontend`
- Backend, Gateway, frontend build, 42 frontend suites / 121 tests and dependency audit passed.
- `scripts/ci/local-ci.sh --all --with-e2e --with-smoke --no-cleanup`
- 16 checks passed: Backend, Gateway, Runtime Adapter, MCP, frontend build/tests,
  mocked E2E, isolated Compose smoke, five real Product API browser journeys and
  the two-user coherence journey. The initial architecture check correctly failed
  because the repository phase marker had not yet been advanced; it was rerun after
  this evidence was complete.
- Chrome MCP independently verified that the index selector contains six enabled
  canonical identities, the Data Center reports `6/6 可用`, and all observed browser
  API traffic stayed on the frontend/Gateway origin with no 5xx response.
- Backend and Gateway were restarted in the isolated stack; the authenticated Data
  Center projection still reported `6/6 可用`, proving PostgreSQL-backed recovery.
- A single exact evidence row was then removed only from the disposable test database.
  Chrome showed `5/6 可用`, retained all six candidates, disabled 创业板指 with
  `等待可信数据同步`, and preserved the five selectable identities. This did not
  remove raw weights or touch any real/runtime database.
- Desktop and 390×844 mobile Chrome views were reviewed. Screenshots:
  `chrome-index-selector.png`, `chrome-data-center.png`,
  `chrome-index-selector-waiting.png`, and `chrome-index-selector-mobile.png`.
