# Product Agent Run Guards

Product DSH remains the only generic Agent runtime. Runtime Adapter owns only
the lifecycle safety policy for its one-process-per-session boundary, while
BeyondQuant MCP enforces bounded Agent-to-Domain reads.

## Runtime limits

Each accepted prompt has three monotonic wall-clock limits:

- `run_timeout_seconds` (default 300): maximum duration of the whole prompt;
- `subagent_timeout_seconds` (default 180): maximum duration between an
  observed `byq_delegate_*` call and its matching result;
- `no_progress_timeout_seconds` (default 120): maximum duration without a new
  public `agent.activity`, `agent.output.delta`, or `turn.completed` event.

The first exceeded guard atomically detaches the active run, emits one safe
`session.failed` event with a stable code, and closes only that session's owned
DSH process. A late result is discarded. Existing failed-session resume creates
a fresh private runtime generation and restores only bounded public context.

Stable failure codes are `runtime-run-timeout`, `runtime-subagent-timeout`, and
`runtime-no-progress-timeout`; all are retryable. Raw DSH event, tool argument,
child-session state, stack trace, and credentials are never projected.

## Backtest analysis page budget

BeyondQuant MCP allows at most six `byq_backtest_analysis_get` calls for the
same workspace, Product session, DSH correlation, and Backtest job in a rolling
five-minute window. The budget is process-local and fail-closed for a request;
it resets naturally after the window or MCP restart and never changes business
data. Calls beyond the limit return `analysis_page_budget_exceeded` with
`retryable=false`; no Backend request is made.

The analyst must read summary once, select only relevant evidence sections,
never enumerate `has_more`, and answer from already collected evidence when the
budget is exhausted. The runtime wall-clock and no-progress guards remain the
hard process-level ceiling if a child ignores this result.
