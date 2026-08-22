# Phase 38 Operations Projection Contract

Status: **Implemented contract** under Accepted ADR-0022.

## Boundary

All browser operations requests use `/api/product/operations/*` on Gateway
and require a durable BYQ administrator session. Gateway reads bounded Backend
aggregates and the Runtime Adapter's normalized process-local metrics. The
browser never calls Backend, Runtime Adapter, DSH, MCP, PostgreSQL, Redis, or a
provider directly.

The contract must not contain database connection strings, environment values,
credential envelopes, plaintext secrets, arbitrary URLs, raw SQL, process
control commands, raw DSH notifications, hidden reasoning, prompts, tool
arguments, or tool results.

## `GET /api/product/operations/status`

Returns `schema_version = "operations.v1"` with these bounded sections:

- `services`: Gateway, Backend, and Runtime Adapter readiness labels;
- `database`: PostgreSQL identity/version/size, aggregate table/row estimates,
  and a closed list of BYQ domain resource counts; no physical table names,
  host, port, role, password, or connection string;
- `cache`: canonical `market_daily_bars` coverage grouped by source and asset
  type, capped at 50 groups; `redis = "not_used"` is explicit;
- `sources`: Tushare-only credential metadata/readiness; Phase 39 owns CRUD,
  connection tests, and sync jobs;
- `models`: model credential status groups, profile/binding counts, and an
  explicit no-secret projection;
- `agents`: status groups and at most 30 recent BYQ AgentRun identities;
- `graphs`: the same BYQ-owned AgentRun/WorkflowTrace correlations, never DSH
  graph/checkpoint/event objects;
- `access`: durable user role/status counts, at most 30 Agent audit events, and
  at most 30 operations audit events;
- `budget`: the current versioned monitoring-threshold policy;
- `runtime`: normalized current-process session counts and DSH token usage;
- `observability`: normalized WorkflowTrace and append-only audit declarations.

Runtime Adapter failure is represented by `runtime.status = "unavailable"`
and zero usage with `source = "unavailable"`. Backend projection failure fails
closed because authorization, durable audit, and storage facts would otherwise
be unverifiable.

## Runtime usage normalization

Runtime Adapter recognizes only the documented DSH `assistant/message.usage`
shape and maps these non-negative integer fields:

| DSH field | BYQ field |
|---|---|
| `inputTokens` | `input_tokens` |
| `outputTokens` | `output_tokens` |
| `cacheReadTokens` | `cache_read_tokens` |
| `cacheWriteTokens` | `cache_write_tokens` |
| `reasoningTokens` | `reasoning_tokens` |

Counts are deduplicated by message ID. Invalid or out-of-bound usage is dropped
atomically. `total_tokens` is the sum of uncached input, output, cache read, and
cache write counts; reasoning is a diagnostic subset and is not added again.
The initial scope is explicitly `adapter_process_lifetime`: it resets on
adapter restart and is not presented as durable billing evidence.

Raw notifications and provider-specific objects are discarded. The Runtime
Adapter internal projection reports `raw_dsh_events = false`.

## `PUT /api/product/operations/budget`

This endpoint updates alerting/observation thresholds only. It does not cancel
DSH work, change model configuration, impose provider billing limits, or grant
runtime authority.

The exact request fields are:

- `enabled`: boolean;
- `alert_total_tokens`: integer 1,000–100,000,000;
- `alert_requests`: integer 1–1,000,000;
- `expected_version`: positive current policy version;
- `idempotency_key`: 1–128 safe characters.

Unknown fields are rejected. A stale version or conflicting idempotency replay
returns conflict. A successful update increments the version and appends a
secret-free `budget.threshold.updated` operations audit. An identical retry
returns the recorded response.

## Authorization and errors

- Gateway verifies the durable user role before requesting Backend or Runtime
  projections.
- Backend independently requires `x-byq-actor-role: admin` for overview and
  writes; the actor principal is recorded for writes.
- Product errors use the existing BYQ error envelope.
- The API has no arbitrary query, shell, migration, backup/restore, restart,
  cache rebuild, credential read, or deployment control endpoint.
