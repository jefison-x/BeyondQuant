# ADR-0045: Agent Data Demand and Readiness Notification

- Status: Accepted
- Date: 2026-08-30
- Decision owners: BeyondQuant Product and Data Planes
- Phase: 80

## Context

Product Agent research reads only durable BYQ market data. That invariant is
correct, but the current contract stops at telling a user to visit Data Center.
It cannot express which frozen universe, date window, or declared datasets are
missing, cannot ask the trusted Data Plane to prepare them, and cannot discover
that preparation later completed.

The production conversation inspected for this phase also exposed an unrelated
automation-channel defect. DSH registers MCP tools under names such as
`mcp__byq__byq_ml_strategy_create`, while delegated child filters still named
the old unqualified form. `tools.restrict()` therefore rejected every child at
creation time before any model or BYQ domain call ran.

BYQ already owns the required execution primitives: `market-data-requirement.v3`,
durable repair requests, calendar refresh, per-session jobs, Data Worker
claim/lease/retry, readiness verification, and Product Data Center projections.
A second synchronization engine or generic workflow would duplicate authority.

The read-only Community DataSync page contains an unfinished local TODO and the
old Agent service contains request/approval ideas coupled to obsolete runtime
and persistence. Their useful invariant is only the user sequence “describe a
bounded need → run a durable task → expose completion”. Their APIs, Provider
paths, runtime and storage are not reusable.

## Decision

### 1. Add a BYQ-owned data-demand facade

Introduce `data-demand.v1` as an owner/workspace/session-scoped coordinator over
existing market readiness and repair jobs. A request contains one immutable
stock-pool snapshot, an inclusive date window of at most five years, a closed
purpose (`research`, `backtest`, or `machine_learning`), bounded declared data
requirements, an idempotency key and trusted Agent context.

Backend resolves pool membership and partitions the window into bounded
requirements. Each partition stays below readiness cell/session limits and
submits the existing durable repair request. Only the trusted Data Worker calls
Tushare or writes authoritative market data.

The facade derives `queued`, `syncing`, `ready`, `partial`, or `failed` from the
repair records and current readiness evidence. It does not invent a second job
state machine and does not claim readiness from enqueue completion alone.

### 2. Keep Provider and privilege boundaries

The first release permits creation only from an active administrator-owned
personal workspace. Product DSH never receives credentials, Provider endpoints,
raw responses, PostgreSQL access, or Data Worker commands.

The orchestrator authorizes and audits the exact `byq_data_demand_create`
action. Creation is bounded and idempotent; it signals an explicit user need but
does not grant general Data Center administration.

### 3. Deliver durable notification to Xiaoba

Ready or failed demands associated with the current runtime session are exposed
as bounded notifications in `byq_agent_context` and through
`byq_data_demand_get`. This makes the result visible to Xiaoba on the next turn
or resumed research run without Backend calling DSH, Gateway depending on raw
runtime events, or Browser calling MCP.

The Product Data Center lists the same durable status. Notifications contain no
raw rows, Provider payload, credentials, internal paths, or DSH event schema.

### 4. Repair delegated tool filtering at the composition boundary

Every MCP entry in a DSH child `toolFilter` uses the runtime-qualified
`mcp__byq__<tool>` name. DSH-local tools retain their registered names. A
contract test compares child filters with the known runtime tool namespace so
drift fails CI before deployment.

## Consequences

- Xiaoba can request preparation and later discover verified completion, but it
  still cannot call a Provider directly or fabricate missing data.
- Long ranges create several existing repair requests; Data Worker scheduling,
  leases, retries and rate limiting remain authoritative.
- Repair expansion is not readiness. Only current readiness verification may
  produce `ready`.
- Non-admin Product users receive a stable forbidden result and can ask an
  administrator to submit the same bounded demand.
- Proactive model execution while the user is absent is out of scope. The
  durable notification is consumed on the next/resumed Agent turn.

## Rejected alternatives

- Let Product DSH call Tushare or Data Worker directly: violates Agent-to-Domain
  and Provider ownership boundaries.
- Reuse `data_sync_jobs` alone: it cannot prove the declared readiness needed by
  strategy, backtest and ML.
- Push an unsolicited Backend prompt into DSH: introduces reverse runtime
  coupling and can execute research without an active user turn.
- Copy Community Agent/DataSync code: it is incomplete and coupled to deprecated
  runtime, database and Provider architecture.
