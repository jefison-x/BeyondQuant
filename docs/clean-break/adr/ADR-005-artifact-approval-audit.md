# ADR-005 — Artifact, approval and audit

- Status: Accepted under ADR-0088 (2026-09-25)
- Acceptance: maintainer's explicit Artifact, three-level Approval and structured Audit specification, recorded by [ADR-0088](../../architecture/adr/ADR-0088-clean-break-baseline-activation.md).

## Decision

Artifact is the stable persistent result reference for research reports, backtests, charts, datasets, models, evaluations, comparisons and exports. Its minimum identity is `artifact_id`, `workspace_id`, type, URI/ref, metadata and creation time; provenance and integrity fields are added where needed.

Approval policy has exactly `AUTO`, `DECISION`, `ACTION`. AUTO covers authorized read/research/compute; DECISION requests a user choice; ACTION gates consequential or irreversible actions. `ApprovalPolicy`, `ApprovalRequest` and `ApprovalResult` are the maximum generic approval concepts. Exact resource, parameters, actor, workspace and idempotency binding remain domain safety invariants. No generic approval workflow engine is introduced.
An ACTION classification is a safety gate, not permission to implement an otherwise prohibited capability. Current BYQ licensing forbids live trading; no approval result overrides that ban.

Audit observation uses `AuditEmitter`, a structured schema and a sink, with timestamp, workspace/user/actor, action, resource, result, request/job IDs and metadata. Audit events are not the source of business truth. Financial orders, approvals and other legally or operationally authoritative records remain explicit business facts in BYQ storage, not disposable log entries. Events notify; DB state is current truth.

## Acceptance

Each Golden Scenario produces Artifact IDs, correct policy decisions and structured audit evidence. No UI or recovery path treats event replay as authoritative state.

## Alternative and consequence

A generic approval engine or event-sourced state store would add a second workflow authority and is rejected. Existing authoritative financial and approval facts require explicit classification before any audit-table deletion.
