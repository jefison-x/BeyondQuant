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

## Backtest analysis reads

`byq_backtest_analysis_get` is an owner-scoped read of a completed immutable
Backtest. Each request returns one bounded section page using the existing
section and page-size schema. The summary is sufficient for a normal review;
request additional sections only when their evidence is needed to answer the
user. `has_more` reports that the Backend has more rows available; it is not an
instruction to enumerate every page. Raw daily-return/equity series and
object-store results remain outside the Agent surface.

Accepted ADR-0111 supersedes the former fixed default of six calls in five
minutes that was recorded by historical ADR-0003. The tool does not add a
session-level call-count or wall-clock budget. Its bounded response schema,
owner/workspace/job checks, trusted request context, authorization and audit
requirements remain in force. Runtime liveness guards and any explicitly
configured execution options remain separate controls.
