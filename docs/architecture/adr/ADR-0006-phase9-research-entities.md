# ADR-0006: Phase 9 Research Entities and Backend Persistence

- Status: Accepted
- Date: 2026-08-15
- Decision scope: Phase 9 Quant Domain research entities
- Supersedes: the ResearchTask, Experiment, and Artifact contract placeholders

## Context

Phase 9 needs durable BYQ business entities for agent-assisted research. The
repository currently has no PostgreSQL service, while the architecture already
requires that business state belongs to the Backend/Domain Plane and remains
inaccessible to DSH. The phase must therefore establish a small persistent
implementation without making storage details part of the MCP contract.

The entities also need explicit state transitions, idempotency, and lineage.
DSH WorkflowTrace may identify the originating run, but it must not own the
ResearchTask, Experiment, or Artifact state machines.

## Decision

1. BYQ owns framework-neutral contracts for `ResearchTask`, `Experiment`, and
   `Artifact`. Their identifiers, state transitions, idempotency behavior,
   provenance, and lineage are enforced by Backend domain code.
2. Phase 9 uses SQLite through the Python standard library as the Backend's
   durable repository. The database path is configured by
   `BYQ_DOMAIN_DB_PATH` and defaults to `/var/lib/byq/domain/byq.sqlite3` in
   Compose. The path is mounted only into Backend through the named
   `byq_domain_state` volume.
3. The repository is behind a Backend-owned interface. A future PostgreSQL
   implementation may replace SQLite without changing the domain or MCP
   contracts. Phase 9 does not claim horizontal-write scalability or perform a
   destructive migration.
4. Every create and transition mutation requires an idempotency key. Repeating
   the same key with the same canonical request returns the original result;
   reusing it with different input is a conflict. State transitions are
   allowlisted and cannot be bypassed by prompts or storage writes.
5. `ResearchTask` is the root entity. `Experiment` belongs to one task and
   records a bounded input snapshot. Each input source must retain a BYQ data
   provenance reference. `Artifact` belongs to a task, may belong to an
   experiment, stores bounded JSON content, and records lineage references and
   a deterministic content SHA-256.
6. Backend exposes the domain endpoints internally. BeyondQuant MCP exposes
   only normalized domain operations: create/get research entities and perform
   validated transitions. MCP does not expose SQL, database paths, raw rows,
   or DSH WorkflowTrace schemas.
7. Phase 9 does not implement business approval. An Artifact can be marked
   `validated` only through the BYQ transition contract; approval policy and
   consequential-action gates remain a later domain decision.

## State machines

```text
ResearchTask: planned → running → completed
                         ├→ failed
                         └→ cancelled
              planned ─────────→ cancelled

Experiment:   planned → running → completed
                         ├→ failed
                         └→ cancelled
              planned ─────────→ cancelled

Artifact:     draft → validated → superseded
                 └─────────────→ superseded
```

Repeating a transition to the entity's current state is idempotent only when
the transition key and request match. No other backward or terminal-state
transition is accepted.

## Consequences

- Keyless tests can exercise persistence, restart recovery, idempotency, and
  lineage with temporary SQLite files.
- The Backend owns all business state and DSH continues to reach it only via
  BeyondQuant MCP.
- SQLite is intentionally a single-Backend implementation. Multi-instance
  deployment, PostgreSQL migration, retention, and approval policy need a
  later ADR.
- Bounded JSON content and input snapshots prevent an agent call from becoming
  an unbounded storage or cost surface.

## Rejected alternatives

- In-memory dictionaries would not satisfy durable Phase 9 persistence or
  restart recovery.
- Direct DSH access to SQLite or PostgreSQL would violate the MCP and data
  ownership boundaries.
- Adding PostgreSQL before the domain contracts would expand topology and
  migration scope without improving the Phase 9 acceptance evidence.
- Treating DSH WorkflowTrace as business state would conflate Agent Plane and
  Domain Plane lifecycles.

## Stop conditions

Phase 9 must stop before widening scope if SQLite cannot provide the required
durability evidence, if the domain contracts require multi-writer semantics,
if provenance cannot be retained, or if an authorization/approval requirement
cannot be represented without a new ADR.
