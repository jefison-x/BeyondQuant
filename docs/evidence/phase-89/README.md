# Phase 89 Acceptance Evidence

Phase 89 implements ADR-0049's isolated trusted GitHub Issue publisher. It does not expose feedback mutation to Browser or
Product DSH; Product UI, MCP, and Xiaoba remain Phase 90 scope.

## Delivered

- Backend internal service-token routes implement heartbeat, claim, complete and retry with bounded batches, leases, monotonic
  fences, expired-lease reclaim, stale-result rejection, safe error categories and a six-attempt ceiling.
- Publication mapping persists only the fixed repository, Issue number, canonical URL, provider identity and snapshot hash.
- The renderer uses a fixed section order, neutralizes mention storms, emits an exact event/hash marker and accepts no repository,
  URL, labels, assignee or milestone from feedback.
- The publisher prefers GitHub App installation credentials, supports a single-repository fine-grained fallback, reconciles
  before every create, and classifies 401/403/404/410/422/429/5xx/transport ambiguity without logging provider bodies/secrets.
- Compose keeps the publisher in an opt-in profile. Its image runs as UID 10006 with read-only root, dropped capabilities,
  no volumes, PostgreSQL URL, source, Git, Docker socket, DSH or browser exposure.

## Verification

- Complete Backend PostgreSQL tests cover configured/unconfigured heartbeat, claim, retry, terminal failure, expiry/reclaim,
  stale fence, successful mapping, canonical URL validation and owner/moderator projections.
- Fake GitHub tests cover exact fixed routes, renderer, existing marker, duplicate marker conflict, ambiguous create reconciliation,
  201, 401, 403, 404, 410, 422, 429 and 5xx. Required tests perform zero real GitHub writes.
- Architecture tests prove the GitHub credential variables occur only in the publisher service; DSH, MCP, Gateway, Backend and
  other workers receive none.
- Isolated Compose smoke starts the optional service unconfigured, proves UID 10006 and health, and confirms Backend records a
  secret-free unconfigured heartbeat while all existing Product flows remain healthy.

## Full-sequence regression

The first two remote CI runs exposed a repeatable Gateway stall only after the complete mocked-E2E, Compose-smoke and real-E2E
sequence. Backend login remained responsive (about 50–80 ms), PostgreSQL had no active lock wait (45/100 connections), while
Gateway calls stopped reaching Backend until the Gateway process restarted. The shared cross-thread `httpx.Client` was replaced
with bounded thread-confined keep-alive clients; the publisher probe no longer bootstraps DDL inside the running Backend and its
optional profile is stopped after isolation verification.

The exact failing sequence was rerun with:

```bash
./scripts/ci/local-ci.sh --base=origin/main --only=architecture,frontend --with-e2e --with-smoke
```

It passed all 16 selected checks, including 18 mocked browser tests, seven real Product API browser flows, the Phase 74 restart
and two-user isolation check, and the Phase 48 no-mock Product coherence check. Gateway unit coverage also verifies that a worker
reuses its own client and cannot share mutable pool state with another worker.

Formal deployment intentionally leaves the publisher profile disabled until an operator installs a least-privilege credential.
