# ADR-0009: Phase 13 Quant Research Agent Boundary

- Status: Accepted
- Date: 2026-08-16
- Decision scope: Phase 13 Product/Agent/Quant Domain integration
- Supersedes: the Phase 13 approval contract placeholder only

## Context

Phases 9–12 established BYQ-owned research entities, factors, strategy
artifacts, and deterministic backtest jobs. Phase 13 needs specialized quant
research roles without recreating a generic agent harness or moving domain
authority into DSH. The Community audit provides useful role/tool allowlist,
delegation, approval, and audit invariants, but its Agent Service persistence,
runtime coupling, and direct business APIs are not compatible with BYQ.

## Decision

1. DSH supplies the generic role mechanisms: the existing Product preset,
   filesystem skills, the official `dsh-subagent` seam, the official
   `dsh-subagent-spawn-in-process` provider, and `dsh-tool-subagent` instances
   with explicit child `toolFilter` allowlists. BYQ does not create a second
   agent loop, workflow engine, or runtime.
2. BYQ owns a versioned role catalogue with five roles: orchestrator, market
   researcher, factor researcher, strategy researcher, and backtest analyst.
   Role definitions include allowed MCP capabilities, delegation targets,
   approval-required actions, and evidence kinds.
3. Gateway passes the authenticated Product principal to the private Runtime
   Adapter at session creation. The adapter places only owner, actor, trace,
   session, and stable DSH correlation values into the DSH-owned MCP client
   headers. It never passes the Product bearer token or model credential.
4. MCP extracts those request headers and forwards them to Backend. Backend
   binds agent runs, approvals, and audit records to the trusted context and
   fails closed on identity mismatch. Agent arguments cannot override it.
5. Backend persists `agent_runs`, bounded `agent_audit` events, and
   `agent_approvals` in BYQ domain storage. DSH run/session identifiers are
   correlation metadata, not BYQ business state machines.
6. Consequential actions require a pending BYQ approval. The initiating actor
   cannot self-approve. Approval state and later execution outcome remain
   separate and both are auditable.

## Consequences

- Specialized children receive only the MCP tools needed for their role, and
  recursion is bounded at one delegation level in the Product composition.
- The role contract is observable through normalized MCP results and BYQ audit
  views without exposing DSH internal event schemas.
- Existing Phase 9–12 invariants remain authoritative; this phase does not
  add source execution, live trading, database access to DSH, or unreviewed
  evidence promotion.
- The stable DSH session is used as the per-session correlation value because
  rc.6's MCP composition does not expose a dynamic per-call header. A later
  ADR may add a per-turn signed correlation carrier.

## Rejected alternatives

- Copying Community Agent Service roles, SQL repositories, or PydanticAI/
  Hermes runtime: violates current ownership and runtime decisions.
- Building a BYQ orchestration loop: duplicates DSH generic capabilities.
- Trusting model-supplied owner/actor fields: permits cross-owner audit and
  approval access.
- Treating approval as execution success: loses failure and retry evidence.
- Giving Product DSH direct PostgreSQL/SQLite, provider, filesystem, or source
  access: violates the architecture boundary.

## Exit evidence

Phase 13 tests cover role allowlists, delegation targets, trusted context
binding, owner isolation, approval self-approval rejection, separate execution
outcomes, audit views, MCP context translation, DSH configuration, and the
absence of Product DSH source/engineering capabilities.
