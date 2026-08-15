# ADR-0007: Phase 11 Strategy Artifact, Validation, and Approval Boundary

- Status: Accepted
- Date: 2026-08-15
- Decision scope: Phase 11 Quant Domain strategy artifacts
- Supersedes: no prior strategy-artifact decision

## Context

Phase 10 produces reproducible research artifacts, but the repository does
not yet have a safe BYQ-owned representation for strategy code/configuration.
Community has useful evidence for content-addressed strategy snapshots,
static source checks, export hygiene, and the distinction between approval and
execution. Its SQLAlchemy models, Pandas runtime, Agent Service workflow, and
optional engines are not compatible with the current architecture.

Phase 11 must make a generated strategy auditable data without making it
application source or giving Product DSH execution or filesystem privileges.

## Decision

1. A strategy draft is a BYQ `Artifact` with a bounded, normalized strategy
   snapshot and retained validation evidence. A draft is immutable; a revised
   draft is a new artifact linked by lineage.
2. A validated `StrategyVersion` is represented by a content-addressed BYQ
   Artifact. Its semantic snapshot excludes mutable timestamps and Agent
   runtime state. The version identity is a SHA-256 of the canonical strategy
   identity; the source fingerprint is a separate SHA-256 of the strategy
   source. Repeating the same version request resolves to the same version
   artifact for the task.
3. BYQ performs deterministic static validation before a strategy version can
   be materialized. Validation rejects unsafe imports/calls, invalid Python
   structure, unsupported categories, oversized or malformed parameters, and
   invalid strategy method contracts. Arbitrary code execution is not part of
   this phase; execution belongs to a later BYQ-owned worker boundary.
4. Export is an explicit BYQ operation. It contains only the strategy version
   contract and semantic snapshot. Credentials, runtime settings, DSH/Agent
   internals, prompts, and application-source paths are rejected or omitted.
5. Approval is a separate immutable `strategy_approval` Artifact linked to a
   validated StrategyVersion. It records actor, decision, rationale, trace,
   and idempotency evidence. An approved record authorizes a future attempt;
   it does not claim that execution or a business mutation succeeded.
6. Backend owns all strategy validation, versioning, export, approval, and
   provenance. Agent-to-Domain calls use normalized BeyondQuant MCP tools.
   Product DSH cannot write the repository, execute strategy code, or access
   Backend storage directly.

## Consequences

- Existing Phase 9 Artifact content hashing, lineage, state transitions, and
  idempotency are reused rather than creating a second persistence model.
- Strategy history is replayable from the stored version artifact even after a
  later draft is created.
- Static validation evidence is durable and explicit, while Phase 12 can add
  an isolated native execution/preflight worker without changing version
  identity.
- Approval and execution outcome remain separate, so a failed later attempt is
  not represented as a successful business mutation.

## Rejected alternatives

- Storing strategy source in the application repository: violates the strategy
  data/artifact boundary and Product DSH source protection.
- Copying Community SQLAlchemy/Pandas/Agent Service strategy runtime: couples
  the new architecture to the old repository ownership and runtime.
- Treating the mutable current strategy record as historical truth: breaks
  reproducibility and historical replay.
- Executing generated code during a Backend API request: creates an unsafe
  execution boundary and belongs in a future BYQ-owned worker.
- Reintroducing VectorBT, BaoStock, or AKShare: explicitly excluded by the
  current architecture and migration inventory.

## Exit evidence

Phase 11 must test invalid source rejection, deterministic version identity,
immutable historical snapshots, secret-free deterministic exports, approval
audit records, idempotent retries, and separation of approval from execution
outcome through Backend and MCP contracts.
