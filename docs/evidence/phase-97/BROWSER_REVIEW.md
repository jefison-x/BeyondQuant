# Phase 97 Browser Review

Reviewed on 2026-09-05 with system Google Chrome 152.0.7977.82 and repository-pinned Playwright 1.62.1.

- The rebuilt isolated Compose stack supplied the real frontend, Gateway/Product API, Backend and PostgreSQL; the Phase 97 browser journey used no
  route mocks.
- The authenticated browser created a durable research task, validated strategy version, owner approval and named Backtest through
  `/api/product/*`, then queried the bounded catalogue using the Chinese name.
- Desktop showed the readable name as primary information, “回测 ID” as a separate column and the complete stable ID in the technical-detail tab.
- The creation dialog was separately exercised in the full mocked regression: the optional 1–120 character name is submitted with the frozen signal
  reference, and the UI explains that it does not change immutable inputs or results.
- Mobile `390×844` showed the name as the card title and short ID as secondary information; `documentElement.scrollWidth <= innerWidth` was true.
- All observed HTTP(S) requests remained on the frontend origin, no Backend/MCP/DSH/PostgreSQL direct browser request occurred, and the journey
  collected no HTTP 5xx response.
- All 20 mocked Product UI regressions and all 9 real Product API browser journeys passed. The environment does not expose a separate interactive
  Chrome MCP server, so the review truthfully records system Chrome driven by the repository browser harness.

Screenshots were inspected during browser execution but are not committed because the generated names and IDs are already asserted in the traceable
Playwright contract and contain only disposable isolated test data.
