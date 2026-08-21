# WorkflowTrace structured projection contract

This contract is normative for ADR-0018 and Phase 36. It defines BYQ-owned
browser projections, not DSH notifications, Community message objects, or
Domain mutation requests.

## Envelope and sources

Cards use the existing `WorkflowTraceEvent` envelope. Accepted `source` values
remain `dsh` and `runtime-adapter`, with `byq-domain` added for a Gateway-
hydrated, owner-scoped Domain projection. A `byq-domain` event MUST NOT contain
any field taken only from model output.

Every serialized payload is finite JSON and at most 65,536 bytes. Exact schema
validation occurs before Gateway persistence and streaming. Unknown fields,
NaN/infinity, arbitrary URLs, HTTP request descriptors, credentials, raw
runtime objects, and tool arguments/results are rejected.

## Common card fields

Every `agent.card.*` payload contains:

| Field | Rule |
| --- | --- |
| `schema_version` | Exact string `workflow-card.v1`. |
| `card_id` | BYQ allocated; `card_` plus 32–64 lowercase hex characters. Never accepted from model content. |
| `revision` | Integer 1–2,147,483,647. Same card must increase monotonically. |
| `authority` | `proposal` or `domain`; only Gateway hydration may produce `domain`. |
| `title` | 1–160 Unicode characters after trimming. |
| `summary` | Optional, at most 2,000 characters. |
| `truncated` | Boolean; true when an allowed display field was safely shortened. |

Proposal IDs are derived from `(trace_id, sequence, kind)`. A Domain-backed
card ID is derived from `(trace_id, kind, canonical_resource_id)`. Clients use
`card_id + revision`, never array position, as render identity.

No card carries executable action data. Frontend actions are fixed mappings
implemented in BYQ source and re-read the current Product resource.

## Card schemas

### `agent.card.strategy_draft`

Additional fields:

- `name`: required, 1–160 characters;
- `summary`: required;
- `artifact_id`: optional canonical BYQ artifact reference;
- `strategy_id`: optional, at most 128 characters;
- `validation_status`: optional `unknown|draft|valid|invalid|superseded`.

Source code, scripts, credentials, validation evidence, and full artifact
content are excluded. Detail is fetched through the owner-scoped Product API.
Only a hydrated Domain card may claim a status other than `unknown|draft`.

### `agent.card.stock_candidates`

Additional fields:

- `items`: 1–50 unique items in stable order;
- each item has exact fields `symbol`, optional `name`, optional `reason`;
- `symbol` is canonical `NNNNNN.SH|SZ|BJ`;
- `name` is at most 80 characters and `reason` at most 500 characters;
- optional `as_of` is `YYYYMMDD`;
- optional `pool_id` is a canonical BYQ Stock Pool reference.

A proposal list is research guidance, not a persisted pool. Pool creation uses
the Product API and its validation/lifecycle contract.

### `agent.card.optimization`

Additional fields:

- `objective`: required, 1–1,000 characters;
- `changes`: 1–20 exact objects with `area` (1–80), optional `before`
  (0–500), `after` (1–500), and `reason` (1–500);
- optional `strategy_artifact_id` and `baseline_job_id` references;
- optional `metrics` permits only finite numeric `total_return`,
  `max_drawdown`, `sharpe_ratio`, `volatility`, and `win_rate`.

An optimization card is a proposal unless every referenced resource is
owner-resolved. It never claims that a strategy was saved or a comparison
backtest executed.

### `agent.card.backtest_context`

This kind requires `authority = domain` and `source = byq-domain`.

Additional fields:

- canonical `job_id`;
- `status`: `queued|running|completed|failed|cancelled`;
- optional finite metrics using the optimization metric allow-list plus
  `trade_count` and `blocked_trade_count` non-negative integers;
- optional canonical `strategy_artifact_id` and `result_artifact_id`.

All values are replaced from the current owner-scoped Backtest projection.

### `agent.card.approval`

This kind requires `authority = domain` and `source = byq-domain`.

Additional fields:

- canonical `approval_id`;
- `action`: a BYQ approval action identifier, at most 128 characters;
- `status`: `pending|approved|rejected`;
- `execution_outcome`: `not_started|authorized|not_authorized`;
- optional `risk_level`: `low|medium|high|critical`;
- optional `decided_by_display`: safe display label, at most 160 characters.

The card contains no decision endpoint or mutation arguments. Before a human
decision, the frontend fetches the current approval and uses the existing
Product Approval API. Approval status and `execution_outcome` remain distinct;
`approved` means authorized, not successfully executed. Expanding execution
outcomes requires a reviewed contract update.

## Public answer and activity

`agent.output.delta` payload:

```json
{
  "schema_version": "workflow-answer.v1",
  "channel": "answer",
  "delta": "public assistant text",
  "truncated": false
}
```

Each fragment is at most 8,192 UTF-8 bytes. The adapter emits only public
assistant answer blocks and deduplicates cumulative DSH updates.

`agent.activity` payload:

```json
{
  "schema_version": "workflow-activity.v1",
  "activity_id": "activity_<hex>",
  "phase": "strategy",
  "state": "started",
  "label": "校验策略草稿",
  "capability": "byq_strategy_validate"
}
```

`phase` is `understand|select|strategy|backtest|review|tool`; `state` is
`started|progress|completed|failed|waiting_approval`. `label` is 1–240
characters. Optional `capability` is a known BYQ MCP capability name, never a
DSH tool identifier. There are no reasoning, prompt, argument, raw result, or
stack-trace fields.

## Budgets and degradation

One turn may emit at most 32 cards and 256 activity events. Excess activity is
coalesced into one `session.progress` event with only a semantic reason and
`truncated: true`. Invalid or unauthorized cards also become bounded
`session.progress` at their allocated sequence. The projector never falls back
to stringifying or forwarding the rejected input.

## Replay and compatibility

Gateway keeps contiguous session sequence semantics. A reconnect replays the
same accepted snapshots; it does not re-run hydration. Within one trace,
`card_id` revisions are strictly increasing. An identical retry is accepted
only under the existing identical-envelope rule.

Optional additive fields require a reviewed v1 contract update. Removing or
renaming a field, changing authority semantics, expanding action capability,
or accepting a new card kind requires a new schema version and ADR review.
