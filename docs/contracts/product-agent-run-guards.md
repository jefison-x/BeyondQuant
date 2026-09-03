# Product Agent Run Guards

Product DSH remains the only generic Agent runtime. Runtime Adapter owns only
the lifecycle safety policy for its one-process-per-session boundary, while
BeyondQuant MCP enforces bounded Agent-to-Domain reads.

## Runtime limits

Each accepted prompt has three monotonic wall-clock limits:

- `run_timeout_seconds` (default 900): maximum duration of the whole prompt;
- `subagent_timeout_seconds` (default 180): maximum duration between an
  observed `byq_delegate_*` call and its matching result;
- `no_progress_timeout_seconds` (default 120): maximum duration without a
  validated DSH execution activity from the owned root runtime or one of its
  observed descendants. Activity includes turn/step boundaries, non-empty
  text or reasoning chunks, committed assistant messages, and valid tool
  calls/results. This private liveness clock does not make hidden content
  public.

The first exceeded guard atomically detaches the active run, emits one safe
`session.failed` event with a stable code, and closes only that session's owned
DSH process. A late result is discarded. Existing failed-session resume creates
a fresh private runtime generation and restores only bounded public context.

The whole-run timeout is always the final hard ceiling. While a tracked
delegated child is active, its dedicated timeout owns the quiet interval so the
shorter root no-progress guard cannot misclassify legitimate child work. An
unknown, empty, or malformed notification never refreshes liveness. Raw
reasoning, descendant identity, tool arguments/results, and
unrecognized DSH events remain absent from WorkflowTrace, persistence, and the
Browser boundary.

The 15-minute ceiling accommodates bounded multi-stage research that continues
to emit validated private runtime activity. It does not extend either the
two-minute inactivity deadline or the three-minute delegated-child deadline,
so an actually stalled run still terminates promptly.

Stable failure codes are `runtime-run-timeout`, `runtime-subagent-timeout`, and
`runtime-no-progress-timeout`; all are retryable. Raw DSH event, tool argument,
child-session state, stack trace, and credentials are never projected.

## Backtest analysis page budget

BeyondQuant MCP allows at most six `byq_backtest_analysis_get` calls for the
same workspace, Product session, DSH correlation, and Backtest job in a rolling
five-minute window. The budget is process-local and fail-closed for a request;
it resets naturally after the window or MCP restart and never changes business
data. Every successful read includes an `analysis_page_budget` projection with
the call limit, remaining calls and whether the current response accessed
Backend. The last allowed read sets `remaining_calls=0` and
`must_answer_from_collected_evidence=true`.

Calls beyond the limit do not access Backend. They return a normal, non-error
bounded-completion result with `analysis_page_budget_exceeded`,
`retryable=false`, `backend_accessed=false` and
`must_answer_from_collected_evidence=true`. Budget exhaustion is a control
result that tells the analyst to synthesize the evidence already held; it is
not a tool failure and must not be retried or waited on.

The analyst must read summary once, select only relevant evidence sections,
never enumerate `has_more`, track the returned remaining-call count, and answer
from already collected evidence when the budget is exhausted. The runtime
wall-clock and no-progress guards remain the hard process-level ceiling if a
child ignores this result.
