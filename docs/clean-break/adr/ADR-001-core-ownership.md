# ADR-001 — Core architecture and ownership

- Status: Proposed
- Scope: BYQ 0.10+ Clean Break; supersedes earlier product runtime ownership decisions only on acceptance.

## Decision

The stable core concepts are `Workspace`, `ResearchTask`, `Job`, `Artifact`, `Approval`, and `AuditEvent`. BYQ owns quant domain state, identity, tenancy, RBAC, strategy and experiment facts. DSH alone owns Agent loop, session, context, compaction, subagent execution and generic Agent recovery. Job/Worker owns long deterministic computation. A persistent result is an Artifact. Every authoritative object has one owner and stable ID. The frontend uses Gateway/Product API and normalized projections; Agent-to-Domain calls use BYQ MCP. Product DSH never gets source write or direct business DB access.

No second generic harness, WorkflowEngine, RuntimeManager or event replay state machine is permitted. DB state is current truth, events are notifications and logs are observation. A business ResearchTask may have explicit domain transitions and idempotency, but not generic Agent execution semantics. Existing historical runtime/session/run/checkpoint/trace data are disposable and are not migration inputs. Current accepted safety invariants survive unless separately changed by an accepted decision.

## Acceptance

Ownership table has one owner for each concept; public contracts expose stable business IDs, not DSH process/schema internals; architecture tests reject direct DSH-to-business-DB and browser-to-internal calls.
