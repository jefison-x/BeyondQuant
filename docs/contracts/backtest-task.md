# Backtest task contract

`backtest-task.v1` is a user-level projection, not a second workflow or persistence table.
Its stable `backtesttask_<uuid>` identity is derived from the existing owner-scoped
SignalProducerJob. The phase, allowed next actions, blockers and lineage are recomputed from
ResearchTask, strategy Approval, MarketReadiness, SignalProducerJob and BacktestJob.

The MCP surface is `prepare`, `create`, `get`, `execute` and `cancel`:

- `prepare` performs the shared domain preflight without requesting data repair or creating state.
- `create` requires an execution-approved strategy and creates the existing signal-preparation job.
- `execute` returns the current task while data/signals are pending. Once the trusted signal worker
  has produced a validated immutable snapshot, it idempotently creates and runs the existing BacktestJob.
- `get` is owner-scoped and read-only.
- `cancel` uses the active component's existing transition. A running signal sandbox cannot be
  force-cancelled because that would not be a safe cooperative boundary.

No task tool accepts raw bars, raw signals, arbitrary Python, provider credentials or object-store
references. Existing strategy approval, personal authorization policy, frozen-input validation,
worker retry, A-share execution and result lineage remain authoritative.

## Community migration classification

Community preflight, idempotency, progress, cancellation and date-default semantics are `PORT_UX`.
Its direct Agent API is `REPLACE`; VectorBT and legacy provider paths are `DROP`. No Community code,
schema, engine or frontend component is copied.
