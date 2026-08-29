# Phase 68 — Dynamic stock pools

Phase 68 implements ADR-0041's closed declarative rule, point-in-time preview,
deterministic evaluation, trusted materialization and exchange-calendar cadence.

Evidence gates:

- pure evaluator and real PostgreSQL store/API regression;
- Product API OpenAPI and same-origin frontend client contracts;
- frontend type-check/build, 120 unit tests and dependency audit;
- real Product API Playwright desktop/mobile journey with preview and immutable
  snapshot materialization;
- independent Chrome DevTools MCP review of accessibility tree, desktop/mobile
  composition, console and Network requests.

The preview is explicitly non-authoritative. Only active definitions enqueue
trusted Data Worker runs. Missing inputs leave the previous current snapshot
unchanged; stale-definition work is cancelled; runtime failures preserve the
last valid pointer.
