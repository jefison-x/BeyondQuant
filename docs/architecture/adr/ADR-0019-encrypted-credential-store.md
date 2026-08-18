# ADR-0019: Encrypted Credential Store for Models and Data Sources

- Status: Proposed
- Date: 2026-08-18
- Decision scope: Phase 37 Models / Phase 39 Data Center credential management
- Related: ADR-0004, ADR-0005, ADR-0016

## Context

Community exposes provider/model credential CRUD (ModelOperationsView,
UserModelSettingsPanel) and data-source configuration (DataSourceConfig).
BYQ currently keeps all credentials as environment variables
(`DEEPSEEK_API_KEY`, `TUSHARE_TOKEN`, `BYQ_MCP_TOKEN`, `BYQ_PRODUCT_TOKEN`)
injected by compose. There is no database-backed credential store, so browser
CRUD is impossible and the Models/Data Center pages can only show masked
status.

BYQ rules forbid BaoStock/AKShare; the supported data provider is Tushare.
Credentials must never be echoed to the browser and writes must be audited.

## Decision

1. Add a PostgreSQL credential store (new table via
   `services/backend/app/db.py`) with application-layer encryption. Stored
   values are encrypted at rest; plaintext is never persisted and never
   returned by any API.
2. Credential scopes:
   - `system`: Tushare token, system DeepSeek key, and future system-level
     provider credentials. Managed only by an admin role; write-only and
     masked read.
   - `user`: personal model API keys. Managed by the owning user; write-only
     and masked read.
3. Reads return only a boolean `configured` flag and a masked descriptor
   (for example `sk-…abcd`), never the secret. Writes are idempotent and
   recorded in an audit event with actor, scope, and timestamp.
4. The existing environment-variable path remains a bootstrap fallback
   (ADR-0004 / ADR-0005). At startup, a missing DB credential falls back to
   the environment value; a DB credential takes precedence once written.
5. Data-source configuration is Tushare-only. AkShare, BaoStock, Yahoo, and
   other providers are not added. Data-source credentials use the `system`
   scope.
6. DSH and the browser never receive provider credentials. Backend and the
   Runtime Adapter continue to hold secrets only in their process
   environment at call time (ADR-0003).

## Consequences

- Models and Data Center pages gain real CRUD through the Product API with
  masked read and audit.
- Requires a small encryption-key management decision at implementation time:
  a per-deployment key delivered via environment (recommended) until a KMS is
  justified.
- Existing env-based deployments keep working unchanged as the fallback.

## Rejected alternatives

- Env-only credentials with UI status: cannot satisfy Community-level CRUD.
- Plaintext storage: unacceptable for provider secrets.
- Adding non-Tushare providers: violates AGENTS rules 23/24 and ADR-0005.

## Rollback

Disable the credential-store-backed reads and return to env-only; the table
can be dropped after confirming no active references. No domain-data
migration is required.
