# Research Domain Contract — Phase 9

## Purpose

Define the BYQ-owned contract for durable research lineage. These entities are
business state in the Quant Domain Plane, not DSH session state.

## Entities

### ResearchTask

`ResearchTask` is the root research intent:

```text
task_id, owner_principal, title, objective, status,
trace_id, created_at, updated_at, version
```

Creation starts at `planned`. The allowed transitions are `running`,
`completed`, `failed`, and `cancelled` as defined by ADR-0006.

### Experiment

An `Experiment` belongs to exactly one ResearchTask:

```text
experiment_id, task_id, owner_principal, name, status,
input_snapshot, created_at, updated_at, version
```

`input_snapshot` is a bounded JSON object. Its `sources` list must contain
references with at least `provider`, `endpoint`, and
`request_fingerprint`, preserving the Phase 8 data-provider provenance needed
to reproduce the experiment input.

### Artifact

An `Artifact` is auditable domain data, never application source:

```text
artifact_id, task_id, experiment_id?, owner_principal, kind, status,
content, content_sha256, lineage, trace_id,
created_at, updated_at, version
```

`content` is bounded JSON. `content_sha256` is computed by BYQ from canonical
JSON and cannot be supplied by the caller. `lineage` contains typed references
to the task, experiment, data snapshot, or parent artifact. Artifact status is
`draft`, `validated`, or `superseded`; Phase 9 does not add business approval.

## Mutation semantics

Create and transition requests require a caller-provided `idempotency_key`.
Keys are scoped to the entity and owner. The same key with the same canonical
request returns the original result without creating a second entity. The same
key with different input returns a conflict.

All strings have explicit length bounds, JSON payloads are finite and bounded,
and unknown fields are rejected at the MCP schema boundary. Backend returns
domain validation errors without exposing SQL, filesystem paths, or internal
exceptions.

## MCP capabilities

The Phase 9 MCP surface is:

- `byq_research_task_create`
- `byq_research_get`
- `byq_research_transition`
- `byq_experiment_create`
- `byq_artifact_create`

The MCP layer translates these calls to Backend domain endpoints. It does not
expose SQLite, SQL, raw database records, or DSH event schemas.

## Ownership and security

Backend owns identity, validation, state, idempotency, provenance, lineage,
and persistence. The current trusted MCP service boundary carries the
immutable `owner_principal` metadata; a later multi-user authorization policy
must add an ADR rather than treating an agent-provided string as a new auth
system. Product DSH has no direct persistence or application-source access.
