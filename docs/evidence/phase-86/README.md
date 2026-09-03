# Phase 86 Evidence

Phase 86 closes ADR-0048 through the Product Plane and Xiaoba without exposing model objects,
raw feature data, worker requests, PostgreSQL or DSH internals.

## Product and Agent boundary

- Dynamic `ml-capability-registry.v2` metadata is served through Gateway/Product API; the frontend
  has no static capability list.
- The initial page requests only capabilities, bounded task/pool options and a 12-item server-side
  filtered catalogue. It does not request a study detail, Artifact collection or prediction rows.
- One selected study loads at most 20 runs/backtests and 20 safe Artifact metadata projections.
  PostgreSQL strips `rows`, `signals`, `bars` and `universe` before JSON materialization; Gateway
  independently excludes prediction rows and signal payloads.
- Prediction rows use a separate query/filter/page endpoint and are requested only when the user
  opens the prediction tab.
- BeyondQuant MCP exposes dynamic capabilities plus paged study catalogue/detail. Xiaoba reads the
  registry first, distinguishes supported/configured/succeeded, defaults an unspecified new study
  to one qualified learner with purged walk-forward, and never silently expands it to regime experts.
- Human strategy approval, prediction and Backtest actions remain separate. DSH never trains,
  predicts, reads PostgreSQL, receives model bytes or accesses GitHub/application source.

## Community frontend checklist

The read-only Community `UserModelsView.vue`, `userModels.js` and
`operations/ModelOperationsView.vue` were inspected before implementation and were not modified.

| Community item | Classification | Phase 86 decision |
|---|---|---|
| LLM provider/profile management | `REFERENCE_ONLY` | Keep it in personal model settings; it is not quantitative ML research. |
| Model catalogue/detail information hierarchy | `PORT_LAYOUT` / `PORT_UX` | Rebuild as a paged study catalogue and explicit lazy detail on BYQ Product API. |
| Direct legacy API and runtime model operations | `REPLACE` / `DROP` | Browser remains same-origin Gateway/Product API; no DSH/Backend/MCP direct call. |
| Quant ML workbench | `REPLACE` | Use ADR-0048 capability, Artifact, approval, trusted Worker, signal and Backtest contracts. |

## Automated verification

- Clean PostgreSQL Backend suite: **292 passed, 1 skipped**.
- Gateway suite, MCP TypeScript build/contract suite, frontend production build, dependency audit,
  **47 frontend files / 131 tests**, full Compose smoke and existing Product golden journey passed.
- Real Product API Playwright: **7 passed**, including compatible LightGBM and the Phase 86
  three-expert HS300 regime journey. The regime journey completed create → approve → train three
  independent models → route prediction → freeze signal → Backtest in 6.9 seconds in the isolated
  fixture environment.
- The completed regime ModelBundle, RegimeSnapshot, PredictionSnapshot and SignalSnapshot identities
  remained identical after ML Worker restart. A second durable user could not list or fetch them.
- Same-origin enforcement observed no unexpected network origin and no HTTP 5xx.

## Chrome MCP review

Review used the no-mock isolated stack at a 1920-class desktop viewport and a 390×844 mobile viewport.

- LCP **319 ms**, CLS **0.00**, no CPU/network throttling.
- Initial Product ML calls: capabilities 16.6 ms / 7.7 KiB decoded; options 47.3 ms / 8.6 KiB;
  12-item catalogue 12.7 ms / 1.1 KiB.
- Initial load made no detail or prediction-row request. Explicit study selection loaded a 25 KiB
  safe detail in 27.7 ms; opening the prediction tab then loaded 38 routed rows in 19.2 ms / 7.4 KiB.
- Desktop and mobile had no horizontal overflow. Console contained no errors, warnings or issues.
- Lighthouse snapshot: accessibility 94 before correcting an invalid `role=list` on button children;
  the incorrect ARIA role was removed. Best Practices scored 100. Generic `robots.txt`, `llms.txt`
  and agentic-browsing diagnostics are outside this authenticated workbench's Phase 86 scope.

No Community source/database, production data, model credential or provider credential was read or
modified during this isolated acceptance run.
