# Product Agent Run Guards

Product DSH remains the only generic Agent runtime. Runtime Adapter owns only
the lifecycle safety policy for its one-process-per-session boundary, while
BeyondQuant MCP enforces bounded Agent-to-Domain reads.

## Runtime limits

Under Accepted ADR-0072, each accepted prompt has separate liveness checks and optional deadlines:

- `run_timeout_seconds` defaults to 0: no whole-run wall-clock ceiling. A positive explicitly configured value is still enforced.
- `progress_check_interval_seconds` defaults to 900: inspect the existing run guards and publish the bounded waiting observation when due. A checkpoint never renews activity or launches a model call.
- `subagent_timeout_seconds` defaults to 180: an unassociated delegation must resolve within this interval; an associated child renews its own inactivity lease only with validated new sequence evidence.
- `subagent_hard_cap_seconds` defaults to 0: no total child duration ceiling. A positive explicit value remains binding.
- `no_progress_timeout_seconds` defaults to 120: inactivity protection based on validated owned-runtime activity, not absence of public text. Liveness is not proof of business progress.

Explicit Backend continuation reservations retain absolute expiry and token limits. New reservations may last up to the human permission's remaining validity (at most 24 hours), while existing short reservations keep their original deadlines. The earlier deadline wins. The Gateway hold and native model gate use the same admitted lifetime with monotonic protection against clock rollback.

A due failure guard atomically detaches the active run, emits one safe `session.failed` event, and closes its owned DSH process. Late results cannot reopen it. Domain jobs remain independent; recovery preserves the original public context and still needs current authorization. A running child owns its own quiet interval rather than inheriting the shorter root inactivity guard. Unknown, malformed and duplicate notifications do not renew its lease.

The periodic checkpoint does not claim business completion or durable task checkpoint creation. Existing domain progress/receipts remain authoritative. No raw reasoning, descendant identity, tool arguments/results or unrecognized DSH events enter WorkflowTrace.

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
inactivity guards and explicit deadlines remain enforced. This read budget is not a universal persistent tool-loop stop; the wider F7 coverage gap is unchanged.
