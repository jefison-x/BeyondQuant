# Artifact Contract — Phase 9

## Purpose

Define ownership and lifecycle expectations for auditable research artifacts,
including evidence and experiment outputs. The complete Phase 9 request and
response contract is in [research-domain.md](research-domain.md).

## Ownership

BYQ owns artifact identity, provenance, validation, authorization, lifecycle, and retention semantics.

## Phase 9 contract

An Artifact belongs to a ResearchTask and may belong to an Experiment. It has
bounded JSON `content`, a BYQ-computed canonical `content_sha256`, typed
`lineage` references, a WorkflowTrace `trace_id`, and one of these states:

```text
draft → validated → superseded
  └─────────────→ superseded
```

Creation and transitions require idempotency keys. Repeated matching requests
are safe retries; a key reused with different input is rejected.

## Non-goals

- It does not treat generated strategy code as application source code.
- It does not grant Product DSH direct persistence access.
- It does not define business approval policy; validation is a domain state,
  not an approval grant.

## Stability guarantee

Artifact consumers SHOULD rely on BYQ artifact contracts and provenance rather than DSH session internals or storage details.
