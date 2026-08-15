# BeyondQuant MCP Boundary Contract

## Purpose

Define the stable capability boundary between Agent Plane and Quant Domain Plane.

## Ownership

BYQ owns domain capabilities, invariants, authorization, validation, and business idempotency exposed through BeyondQuant MCP. DSH owns generic MCP client infrastructure.

## Phase 8 data capability

The `byq_market_daily` tool is the Agent-to-Domain entry point for the Phase 8
daily market-data contract. It accepts the normalized request fields described
in [the data-provider contract](data-provider.md) and returns BYQ daily bars
plus provenance metadata.

The MCP service may call the Backend Domain/Data endpoint to fulfill this
capability. It must not receive or forward `TUSHARE_TOKEN`, and it must not
pass through arbitrary Tushare endpoint names, raw parameters, or raw provider
response envelopes.

## Phase 9 research capabilities

The Phase 9 tools `byq_research_task_create`, `byq_research_get`,
`byq_research_transition`, `byq_experiment_create`, and
`byq_artifact_create` are the Agent-to-Domain entry points for durable
research state. Backend owns validation, state transitions, idempotency,
provenance, lineage, and persistence. MCP forwards only the normalized domain
fields and returns normalized domain records.

MCP must not expose SQL, SQLite paths, database rows, DSH WorkflowTrace
schemas, or Backend implementation exceptions. DSH may request a domain
operation through MCP, but it cannot mutate research state by accessing the
Backend database or filesystem directly.

## Phase 13 agent capabilities

The `byq_agent_*` tools expose a BYQ-owned role catalogue, trusted runtime
context, owner-scoped agent runs, action authorization, bounded audit views,
and human approval state. MCP derives owner/actor/session/trace headers from
the authenticated Runtime Adapter path; model-supplied identity fields cannot
override them. DSH may delegate through its native subagent seam, but it
cannot bypass BYQ authorization or approval with a prompt or a direct storage
call.

## Phase 14 learning capabilities

The `byq_learning_*`, `byq_evaluation_signal_*`, `byq_experiment_compare`,
and `byq_lesson_*` tools expose bounded learning runs, ordered iteration
history, deterministic evaluation-signal comparison, and evidence-backed
lesson promotion. Backend owns budgets, stopping rules, idempotency,
validation, human review, and promotion history. MCP forwards only normalized
domain fields and never exposes SQLite paths, raw rows, DSH event schemas,
provider credentials, or Backend implementation exceptions.

## Non-goals

- This document does not define a complete tool schema.
- It does not permit direct DSH access to BYQ PostgreSQL, Redis business state, or backend internals.
- It does not define a generic second agent harness.

## Stability guarantee

Agent-to-domain calls MUST use this boundary. Storage and backend implementation changes SHOULD remain invisible to DSH clients when the domain contract remains compatible.
