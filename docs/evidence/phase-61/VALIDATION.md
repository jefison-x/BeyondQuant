# Phase 61 validation evidence

Date: 2026-08-27 (Asia/Shanghai)

## Isolated environment

- Branch: `phase/61-user-experience-closure`
- Base: `12224eb6a297f8b29283e5663efa33128d9c3547`
- Product URL: `http://127.0.0.1:18081`
- Network: `byq_phase61_clean_restore`
- Database: a new isolated PostgreSQL 16 volume restored into `byq_phase61_restored`
- Browser: real headless Chromium through Playwright; request origin, 5xx and Console errors observed
- The original damaged PostgreSQL volume was not mounted by this stack.

## Recovery and data integrity

- Pre-recovery physical archive: `/tmp/byq-postgres-pre-recovery-20260827T0817.tar.gz`
  - size: 111 MB
  - SHA-256: `c612497f7d80ab0854f688519ff98d7fb83c939decdf069924f94480637b9e02`
- Business logical backup: `/tmp/byq_domain_recovered_20260827.dump`
  - size: 40 MB
  - SHA-256: `4f62aaf6a808f072b817322df19961cfa000bd118482c4239ebb0a7ba173828f`
- Globals backup: `/tmp/byq_globals_recovered_20260827.sql`
  - SHA-256: `2ebf8cd3881b76068c9ec261d836306eee98859376f200661c8625d83d529a22`
- Domain/result-object archive: `/tmp/byq-domain-state-20260827T0900.tar.gz`
  - size: 16 KB
  - SHA-256: `e02bc60f8418c68757fb80d1afbef13ea9f75f7bc42d56c22f7f7d543c049285`
- Clean logical restore completed without `--clean` or overwrite. Restored counts equal the recovery source:
  - `market_daily_bars=127326`
  - `users=4`
  - `product_conversations=34`
  - `backtest_jobs=5`
  - `paper_accounts=8`
- A restored DB alone correctly failed to read immutable backtest result objects. Mounting the separately protected Domain object volume read-only restored the result endpoint to HTTP 200. Recovery documentation must therefore treat DB and result objects as one logical recovery set.

## Real data consistency

- PostgreSQL sample: `002737.SZ`, `20260826`, close `13.22`, source `tushare`.
- MCP real contract: `002737.SZ`, `20260727–20260826`, 23 persisted rows, cutoff `20260826`, latest close `13.22`.
- Backend log: exactly `POST /v1/data/research/daily HTTP/1.1 200 OK` for the MCP call.
- Contract asserted `source=persisted_byq` and `live_provider_called=false`.
- Product readiness for the same range returned `usable`, 23 required sessions, 23 ready items, zero missing items, complete calendar, and `checked_against=persisted_byq`.

## Automated verification

- Architecture: 50 passed.
- Backend: 169 passed, 1 skipped.
- Gateway: 60 passed after the browser-number manifest regression test was added.
- MCP: full contract suite passed; real persisted-market contract passed.
- Runtime Adapter/DSH static compatibility: 34 passed.
- Frontend: 34 files, 83 tests passed; production TypeScript/Vite build passed.
- Compose: two project names resolve to distinct project-scoped networks and all four named volumes.

## Real browser verification

Repository real Product suite on the isolated recovery copy:

- login + Stock Pool create: passed;
- Paper Trading settlement/risk/detail/export/import: passed;
- My Space credential/binding/policy/asset export/import/system pages: passed after fixing JSON-number-stable manifest hashing;
- final result: 3 passed.

Phase 61 UX suite without external model calls:

- task readiness + Backtest four next actions + reviewable Agent draft + browser Back: passed;
- Strategy user-first detail + collapsed technical evidence + approval + preselected Backtest dialog: passed;
- no post-login Console errors, HTTP 5xx or unexpected origins in the passing runs;
- screenshots: [readiness/backtest](screenshots/05-readiness-backtest-next-step.png) and [strategy/backtest](screenshots/06-strategy-backtest-handoff.png).

Maintainer-authorized real DeepSeek continuous research scenario:

- two natural turns comparing `600036.SH` and `601166.SH` passed in 46.0 seconds;
- conversation: `conversation_cb41f4cedee84fbc94d9d825f0b547ad`;
- both answers used persisted BYQ daily data, disclosed cutoff `20260826`, and made no live-provider claim;
- the follow-up created no ResearchTask, Experiment, or Artifact (`delta=0` for all three);
- the first run exposed a return-basis labeling defect. After the skill contract fix, the model distinguished
  five-session cumulative return (first row `pre_close` to final `close`) from first-to-final close change;
- verified values: CMB `+1.66%` / `38.86→39.80, +2.42%`; CIB `-0.16%` / `18.17→18.21, +0.22%`;
- screenshot: [continuous research](screenshots/04-agent-continuous-research.png).

The bootstrap `/api/auth/me` 401 before login is expected and was excluded only after login; it was not classified as a product failure. The Vite build still reports the pre-existing large-chunk warning (Backtest and shared Element Plus bundles); this is a P3 performance optimization, not an acceptance blocker.

## Explicitly pending

Production cutover was explicitly authorized after the clean restore and model evidence completed. Until the cutover verification is appended, the live `beyondquant-postgres-1` remains exited, the original damaged volume remains unchanged, and the isolated clean restore is evidence rather than a production switch.
