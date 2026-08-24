# ADR-0026: Security Master and Bounded Market-Data Orchestration

- Status: Accepted
- Date: 2026-08-24
- Accepted: 2026-08-24
- Decision scope: Beta Data Plane security master, catalogue Product API, and
  daily-bar synchronization orchestration
- Related: ADR-0005, ADR-0013, ADR-0016, ADR-0019, ADR-0020, ADR-0025

## Context

Phase 39 delivered durable Tushare daily-bar jobs, but every job requires the
operator to already know 1-20 canonical symbols. The coverage projection lists
only symbols that already have bars, so it cannot bootstrap a complete A-share
catalogue. This makes the Data Center internally consistent but not usable for
initial market-data acquisition.

The read-only Community implementation calls Tushare `stock_basic` for listed,
paused, and delisted securities and stores a mutable stock universe. Its useful
evidence is the need for canonical identity, lifecycle dates, searchable basic
metadata, and a security-master-first synchronization sequence. Its provider
registry, ORM, Pandas/Tushare SDK, background threads, broad multi-dataset
runtime, and frontend-to-internal API coupling are not compatible with BYQ.

BeyondQuant remains in Beta until the maintainer explicitly authorizes a formal
release. This capability closes a Beta product gap and does not authorize a
release, a new provider, or arbitrary Tushare access.

## Decision

1. BYQ owns a framework-neutral `security-master.v1` contract for canonical
   A-share stock identity. Records include canonical symbol, local symbol,
   display name, exchange, market/board, area, industry, listing status,
   listing/delisting dates, Stock Connect flag, asset type, and bounded
   provenance. Only `.SH`, `.SZ`, and `.BJ` stocks are accepted.
2. The Backend-owned Tushare adapter gains one explicit `stock_basic`
   capability. It requests the closed status set `L`, `P`, and `D` with an
   explicit field list, translates raw envelopes inside Backend, rejects
   duplicate/conflicting identities, and never exposes arbitrary endpoint or
   parameter passthrough. Tushare's `T`-prefixed historical aliases (for
   example `T600018.SH`) are not canonical A-share identities and cannot be
   normalized without colliding with a different six-digit security. A
   bounded set of otherwise valid aliases is therefore persisted as
   quarantine evidence and excluded from the authoritative catalogue.
3. PostgreSQL owns platform-scoped current security records plus immutable,
   content-addressed security-master snapshots. Each successful full sync is
   atomic and records provider, request fingerprint, dataset fingerprint,
   status coverage, row count, retrieval time, actor, and snapshot members.
   Rows absent from a later snapshot remain historical evidence but are not
   presented as members of the latest catalogue.
4. Security master is platform data under ADR-0025. It has no `workspace_id`
   and is never exported in personal workspace bundles. Synchronization is
   administrator-only; authenticated Product users may receive only the
   bounded searchable catalogue where a Product workflow needs it.
5. Browser access remains same-origin Gateway/Product API. Product responses
   contain normalized records and job metadata only; no credential, raw
   Tushare envelope, database schema, MCP surface, or DSH event is exposed.
6. Daily-bar jobs may resolve a frozen symbol selection from one of four
   bounded sources: explicit canonical symbols, selected catalogue symbols,
   the latest security-master snapshot filtered by listing status/exchange, or
   an authorized immutable Stock Pool snapshot. The resolved symbols and
   selection provenance are persisted before execution, so later catalogue or
   pool changes cannot alter a job.
7. Explicit/selected requests remain bounded. Catalogue and Stock Pool
   orchestration may resolve at most 6,000 symbols. Public job projections
   return counts and bounded previews/results rather than unbounded symbol
   arrays. Provider calls retain bounded retries and durable per-symbol
   progress.
8. `range` sync requests the declared inclusive range. `incremental` sync
   starts after each symbol's latest persisted bar, bounded by the requested
   range, and records a no-op result when coverage already reaches the end.
   Existing authoritative bars continue to use `KEEP_NEW` and are never
   overwritten by last-write-wins.
9. The Data Center provides basic-data synchronization, status counts,
   searchable/paginated stock catalogue, explicit selection, all-listed and
   exchange filters, Stock Pool selection, and daily-bar job progress. It does
   not imply live quotes, fundamentals, ETF/index masters, or complete market
   coverage.

## Security and domain invariants

- Tushare plaintext remains inside Backend and is resolved under ADR-0019.
- Canonical `stock_basic` results must match the requested status and
  symbol/exchange relationship; malformed dates, empty names, conflicts, and
  unknown out-of-contract identities fail the whole snapshot. Only bounded,
  fully validated `T`-prefixed historical aliases may be quarantined; their
  count and identity evidence are stored with the immutable snapshot and they
  never enter `market_securities` or a daily-bar selection.
- A successful security-master sync is atomic. Partial provider status results
  never replace the latest catalogue.
- Dataset identity excludes mutable timestamps and actor metadata.
- A daily job freezes its exact symbols and source snapshot before provider
  execution. A client-supplied workspace or ownership field grants no access.
- Stock Pool resolution requires the trusted durable workspace/owner context
  and an existing immutable snapshot; guessed cross-workspace IDs fail as not
  found.
- BaoStock and AKShare remain `DROP`. No compatibility provider or fallback is
  introduced.

## Consequences

- A fresh BYQ deployment can bootstrap a real A-share catalogue before asking
  an operator to synchronize daily bars.
- Full-market historical refresh remains expensive but explicit, bounded,
  observable, resumable at symbol-level through incremental jobs, and subject
  to the configured Tushare account's permissions and rate limits.
- Security metadata becomes a shared platform dependency. Future ETF, index,
  calendar, valuation, or corporate-action datasets require their own mapped
  contracts rather than piggybacking on this endpoint.

## Required evidence

- provider translation/retry/duplicate/status/date tests with secret-free
  fixtures, including bounded historical-alias quarantine and fail-closed
  unknown identities;
- atomic snapshot, idempotency, latest-catalogue, search/filter/pagination, and
  historical-retention tests against PostgreSQL;
- daily selection freezing, bounds, incremental semantics, Stock Pool
  authorization, Product API RBAC, and response-bounding tests;
- frontend component/API tests and real Product API Chrome DevTools review for
  desktop and mobile;
- Community classification and architecture tests proving no excluded
  provider, raw Tushare, Backend, MCP, DSH, or PostgreSQL browser path.

## Rejected alternatives

- Derive the catalogue from distinct daily bars: omits suspended, not-yet-
  traded, and historical lifecycle records and cannot bootstrap itself.
- Fetch one recent `daily` market snapshot: returns codes without authoritative
  basic identity/lifecycle and omits non-trading securities.
- Let the frontend or DSH call `stock_basic`: exposes provider schema and
  credentials and bypasses Product API/MCP boundaries.
- Copy the Community stock-universe stack: reintroduces incompatible ORM,
  provider registry, SDK, scheduler, and mutable-current-row assumptions.
- Submit thousands of symbols from the browser: creates unbounded request and
  replay payloads and makes the client authoritative for catalogue identity.

## Rollback

Disable the new Product routes and security-master job creation. Existing
daily jobs continue to accept the legacy explicit-symbol contract. Additive
platform tables and immutable snapshots may remain as audit evidence; no
workspace row or Community source is modified. A failed schema/data rollout is
repaired forward or restored from the normal PostgreSQL backup boundary.
