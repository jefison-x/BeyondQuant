# Phase 88 Acceptance Evidence

Phase 88 implements the durable Product Feedback domain and bounded Product API required by ADR-0049. It intentionally
does not include a GitHub client, publisher credential, Product UI, MCP tool, or Xiaoba skill.

## Delivered boundary

- PostgreSQL owns feedback identity, immutable revisions, bounded audit, submitted/publication snapshots, idempotency commands,
  and transactional outbox rows.
- Owner operations are workspace scoped through trusted durable-user context. Moderator routes require the platform admin role
  but do not grant workspace membership or reveal workspace/user identity.
- Gateway Product API exposes options, paged summaries, lazy detail/revisions/preview, lifecycle actions, paged moderation, and
  read-only publisher status. Raw User-Agent, request headers, internal IDs, leases/fences, and credentials are excluded.
- The accept transition and immutable publication/outbox enqueue are atomic. The transaction rollback test injects an outbox
  failure and proves that no accepted state or publication survives.
- Unsafe security reports, credentials, identity/URL content, unbounded Markdown, unknown fields, and oversized requests fail
  closed with secret-free errors. Preview hashes and fingerprints are deterministic.
- With no publisher installed, internal feedback remains usable and reports `publisher_unconfigured`.

## Verification

- Architecture boundary tests prove feedback is durable/paged and the Backend domain has no GitHub HTTP client or API origin.
- Complete PostgreSQL Backend tests cover lifecycle, restart-safe DDL, two-workspace isolation, revisions, optimistic concurrency,
  idempotency, safety rejection, rate limits, pagination, duplicate flow, atomic accept/outbox, and transaction rollback.
- Gateway tests cover durable login context, same-origin paging, coarse browser/OS diagnostics, moderator role separation, and
  safe Backend error projection.
- Frontend contract types compile under the locked production build and the full Vitest suite remains green.
- Required tests make zero real GitHub writes.

Formal Compose smoke verifies the merged Backend/Gateway against the existing PostgreSQL volume before Phase 89 begins.
