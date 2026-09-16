# Agent data-demand contract

`data-demand.v1` is an owner/workspace/session-scoped facade over the existing
`market-data-requirement.v3`, repair request and per-session Data Worker jobs. It is not a
second synchronization engine or a provider API.

The first version accepts an immutable Stock Pool snapshot of at most 500 symbols, a date
range of at most five years, a closed declared-data requirement and one of `research`,
`backtest` or `machine_learning`. Backend resolves the frozen members and current Security
Master snapshot, partitions the request below the readiness matrix bound and idempotently
queues the existing repair flow. Only an administrator-owned personal workspace may create
a demand.

Status is derived from fresh readiness assessments and existing worker state:

- `queued` — the repair plan is durable and waiting for the Data Worker;
- `syncing` — at least one partition or trading session is in progress;
- `ready` — every partition satisfies the declared requirement;
- `partial` — processing terminated with some usable coverage and some missing data;
- `failed` — processing terminated without usable coverage.

Repair coordinator records may additionally remain internally
`waiting_for_sessions` while durable per-session jobs are queued or running. The public demand
continues to project this as `syncing`; a repair is `completed` only after a fresh readiness
assessment is `ready`. Session failures become bounded `partial|failed` diagnostics rather than
an enqueue-time success.

`byq_data_demand_create` and `byq_data_demand_get` are the MCP surface. Terminal notifications
are also projected through `byq_agent_context`, allowing Xiaoba to resume research on a later
turn without Backend injecting an unsolicited DSH prompt. MCP and DSH never receive provider
credentials, call Tushare directly, write market tables or redefine readiness rules.

The Data Center uses the existing Product API status projection to show recent demands. Browser
code does not call Backend, MCP, Data Worker or provider endpoints directly.

## Community migration classification

Community `DataSync.vue` progress and task intent are `PORT_UX`; its fake progress, TODO service
calls and direct synchronization shape are `DROP`. No Community code, schema or provider path is
copied.

## Historical single-snapshot preparation (H5)

The closed alternative request is `{purpose, scope_kind:"index_snapshot", index_symbol,
requested_as_of, idempotency_key}`. It accepts only the six canonical catalogue indexes and
an explicit non-future date. It needs no pre-existing Stock Pool snapshot; the existing nullable
snapshot column is empty only for this scope. It uses the existing repair coordinator and
Data Worker, fetching only index weights for at most three monthly partitions spanning the
62-day snapshot window. It does not download trading-calendar or daily-price datasets.

Readiness requires intact Tushare provenance, row/snapshot hashes, weights and evidence retrieved
after each required complete day. It selects the latest verified snapshot inside the frozen
window, never after the requested date. The final notification explicitly says that a single
snapshot does not establish historical rebalancing-series coverage or market-price readiness.
A request for today may remain unready until complete-day evidence is available.

Demand identity and repair references commit together. Same-key retries reuse the original
frozen plan before mutable readiness planning; changed input conflicts. `byq_data_demand_get`
accepts exactly one of `demand_id` and `idempotency_key`, with owner/workspace-scoped original-key
lookup for unknown writes. Browser access uses `/api/product/data-center/demands` and its exact
ID/key reads only. Administrator-owned workspace requirements remain unchanged.
