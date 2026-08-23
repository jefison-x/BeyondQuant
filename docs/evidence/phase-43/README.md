# Phase 43 acceptance evidence

Phase 43 implements ADR-0024's durable Product conversation catalog and
centered Xiaoba workspace. The Community repository was inspected read-only;
its title/pin/rename/history UX and anti-crossover behavior were classified in
`docs/migration/COMMUNITY_MIGRATION_INVENTORY.md`. No Community API, runtime,
storage or message schema was copied.

## Contract and persistence evidence

- Backend PostgreSQL tests cover deterministic bounded first-turn titles,
  owner isolation, restart-safe catalog/message reads, pin ordering, search,
  pagination, archive and restore.
- Gateway tests prove browser replay excludes the private runtime session ID
  and emits only validated BYQ WorkflowTrace envelopes.
- Frontend store tests atomically replace the selected conversation and reject
  event crossover; streams are generation-guarded and abortable.
- The isolated Compose smoke passed after runtime restart with named DSH and
  WorkflowTrace volumes. A Product conversation remained addressable through
  its public conversation ID while the runtime identifier stayed private.

## Automated verification

- Architecture tests: 44 passed.
- Backend PostgreSQL suite: passed.
- Gateway suite: 50 passed.
- Frontend production build: passed.
- Frontend unit tests: 59 passed.
- Mocked Chromium Product journeys: 12 passed, including durable replay and
  mobile history-drawer navigation.
- Full isolated Compose smoke: passed.
- Real Product API Chromium journeys: 3 passed.
- `npm audit --audit-level=high`: zero vulnerabilities.

## Chrome DevTools MCP review

- `desktop-conversation.png`: 1440x900 production Compose page at
  `http://127.0.0.1/agent`, showing deterministic first-turn title in the
  sidebar and header, centered user/assistant timeline, inline Product shell,
  and bounded activity entry.
- `mobile-history.png`: 390x844 emulation showing the full-screen conversation
  surface and route-backed history drawer behavior.
- Browser network inspection showed only same-origin Gateway/Product routes;
  no Backend, MCP, DSH, PostgreSQL or raw runtime endpoint was requested.
- Browser console contained no errors after the production reload and tested
  interactions.

## Community feature checklist

| Capability | Result |
|---|---|
| Durable human-readable title | PASS — deterministic first turn plus rename. |
| Recent history and pin ordering | PASS — owner-scoped persisted catalogue. |
| Search and bounded pagination | PASS — Backend enforced limits. |
| Archive and restore | PASS — non-destructive lifecycle. |
| Message and structured-result restoration | PASS — user turns plus normalized WorkflowTrace/card replay. |
| Session switching isolation | PASS — generation guard, abort and atomic hydration. |
| Centered conversation-first layout | PASS — permanent three-column workbench removed. |
| Mobile conversation/history flow | PASS — Chrome emulation and Playwright. |
| Community API/runtime coupling | REPLACED — BYQ Product API and ADR-0024 boundary. |
