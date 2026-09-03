# Phase 90 Acceptance Evidence

Phase 90 closes the built-in Product Feedback program through the real Product API. Normal users need no GitHub account,
token, repository, or permission. The independently deployed publisher remains optional and unconfigured by default.

## Delivered journey

- Owner UI: paged catalogue, draft editor, opt-in coarse diagnostics, server preview, explicit confirmation, status and Issue link.
- Admin UI: paged moderation inbox, lazy submitted snapshot/audit, triage/accept/reject/duplicate and safe publisher status.
- Xiaoba: seven owner-only BeyondQuant MCP tools plus a skill that must show the exact preview and wait for a later explicit
  confirmation before submission. No moderator, publisher, repository, GitHub credential, source, PR, CI or deploy tool exists.
- Performance: initial owner load is exactly options plus first summary page; detail/audit are lazy; filtering is server-paged,
  debounced and aborts stale requests. Production chunks are independently route-loaded.

## Automated verification

- Frontend production build, 48 Vitest files / 134 tests, dependency audit and 20 mocked Playwright journeys.
- Real PostgreSQL/Product API browser journey covers draft, preview without submit, explicit submit, admin triage/accept,
  `publisher_unconfigured`, desktop/mobile layout, same-origin requests and empty authenticated-page browser console.
- Phase 90 golden script covers idempotency, unsafe security rejection, submitted snapshot, moderator projection, second-user
  isolation and persistence across Backend restart.
- Full Compose smoke covers MCP contracts, durable authentication, Runtime Adapter and existing Product regressions. Backend,
  Gateway, MCP, Runtime and architecture suites remain green; required tests make no real GitHub request.

See [browser review](CHROME_MCP_REVIEW.md) and [Community checklist](COMMUNITY_FEATURE_CHECKLIST.md).
