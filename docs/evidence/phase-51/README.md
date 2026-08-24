# Phase 51 — Trusted workspace context and contract evidence

Date: 2026-08-24

## Result

Phase 51 closes the trusted personal-workspace authorization path without
adding team features. Durable login/session responses carry a bounded personal
workspace projection. Gateway ignores browser workspace headers and derives
the private service context from the durable session. Runtime Adapter places
that context in the Product DSH SDK environment, the DSH composition sends it
to BeyondQuant MCP, and every MCP domain tool fails closed without the complete
context and forwards trusted headers to Backend.

Backend validates the active user/workspace/owner membership before any
workspace-owned Product or Agent operation. Existing domain contracts retain
`owner_principal` only as creator/audit compatibility after this check. Database
write triggers derive `workspace_id`, reject owner/parent mismatches, and keep
parent/child rows in the same workspace. The verified contract migration makes
all 31 classified workspace columns non-null and installs workspace-scoped
idempotency/uniqueness indexes.

## Security evidence

- A browser-supplied `x-byq-workspace-id` is ignored; the session workspace is
  forwarded instead.
- A valid owner combined with another user's valid workspace is rejected.
- New root and child writes receive the trusted workspace, while a mismatched
  explicit workspace update is rejected by PostgreSQL.
- MCP research, factor, strategy, signal/backtest, Stock Pool, Paper Trading,
  Agent, learning, and market-data calls all require the complete trusted
  context at the server registration boundary. DSH still has no PostgreSQL
  access.
- The no-mock Phase 48 two-user journey passed with the secondary user's owner
  resources hidden and administrator routes returning 403.

## Migration evidence

- Pre-contract backup: `/tmp/byq-phase51-pre-contract.dump`
- Backup size: `160537` bytes
- Backup SHA-256:
  `ee7674e653e817348e87349534fd07c44d8dc0b9815f9e2197fc950ad8094d9b`
- Dry-run and contract manifest SHA-256:
  `989eaf593bd4646cc4a8a304b1815a618ab0f5c4968d2386256ba589ab385fc7`
- Quarantine rows: `0`
- Parent/reference checks: `22`, all `0`
- Contract result: `31/31` classified `workspace_id` columns are `NOT NULL`

The contract command was:

```text
python -m app.migrate_personal_workspaces --contract
```

It returned `personal-workspace.v1`, `status=enforced`, `tables=31`.

## Verification

- Backend: `126 passed, 1 skipped` (full isolated PostgreSQL suite; the exact
  count includes the new login/session, spoof-denial, trigger, and contract
  tests).
- Gateway: `52 passed`.
- Runtime Adapter: `28 passed`.
- MCP TypeScript build and all 12 contract scripts passed.
- Frontend: build passed; `31` Vitest files / `77` tests passed; dependency
  audit reported `0` vulnerabilities; mocked Playwright `15 passed`.
- Corrected full Compose smoke passed after replacing its obsolete Product
  Token Agent bootstrap with durable user login.
- Real Product API Playwright: `3 passed`.
- Phase 48 no-mock two-user Product coherence: `status=passed`.

No frontend visual surface changed in Phase 51. Phase 52 owns the bounded shell
orientation and fresh Chrome desktop/mobile evidence.
