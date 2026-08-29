# Phase 74 verification

Phase 74 closes the reliable LightGBM product journey through the Gateway/Product API:

`frozen pool → approved strategy → training → model artifact → out-of-sample prediction → frozen signal → backtest`

## Automated acceptance

- `BYQ_E2E_EVIDENCE_DIR=/tmp/byq-phase74-final-evidence scripts/ci/local-ci.sh --all --build --with-smoke --no-cleanup`
  passed all 18 checks from a clean isolated Compose stack.
- Frontend production build passed; all 43 test files and 124 unit tests passed.
- Six real-browser Product API journeys passed, including the Phase 74 LightGBM flow on desktop and mobile.
- The ML worker restart retained the same TrainingRun, ModelArtifact, PredictionRun,
  PredictionSnapshot, and SignalSnapshot identities.
- A second durable BYQ user received an empty ML workspace and `404` for the owner's direct run lookup.
- Gateway contract tests prove server-owned trace/idempotency and exclude model object references,
  feature snapshots, raw feature rows, and raw backtest manifests from browser projections.

## Browser evidence

- Chrome MCP reviewed the completed journey at desktop and mobile widths.
- Lighthouse snapshot scores were Accessibility `100` and Best Practices `100` on both device profiles.
- The final page had no console messages.
- All 73 preserved browser requests were same-origin through the frontend/Gateway origin; no browser request
  addressed Backend, MCP, DSH, PostgreSQL, Redis, or a market-data provider directly.

Artifacts:

- `01-lightgbm-desktop.png`
- `02-lightgbm-mobile.png`
- `lighthouse-desktop.json`
- `lighthouse-mobile.json`
- `community-feature-checklist.md`

The fixture and screenshots contain deterministic test-only market rows and transient IDs. They are evidence,
not production data or a source-of-truth manifest.
