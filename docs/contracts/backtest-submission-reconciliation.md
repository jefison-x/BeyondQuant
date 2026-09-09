# Backtest submission reconciliation v1

Accepted ADR-0062/0025; exact read of an existing durable backtest creation identity.

- GET `/v1/research/backtests/reconcile` requires a trusted active owner/workspace,
  the original owned ResearchTask `task_id`, and original `idempotency_key` (1–128 trimmed characters).
- Read the exact task/key mapping, restricted to that owner/workspace. No list scan,
  request replay, input validation/preparation, approval mutation, worker execution or new queue.
- `backtest-submission-reconciliation.v1` returns `confirmed` plus the existing job summary,
  or `outcome_unknown` without a job. Confirmation describes receipt identity, independent
  of queued/running/completed/failed/cancelled domain state. Unknown never authorizes a write.
- Projection matches the existing summary endpoint; no raw input manifest, result object
  reference or private request hash. Missing/deleted records are unknown, not failed submissions.
- Extend `byq_backtest_get`: either `job_id`, or both `task_id` and `idempotency_key`.
  Reject ambiguous/incomplete identities without Backend calls. Existing ID reads are compatible.
- A matching key refers to the original committed input, not a replacement request's semantics.
  Existing create conflict and approval rules remain authoritative.
- Evidence: late commit, connection recreation and fresh-process durable read, exact parent/key,
  owner/workspace and disabled identity checks, malformed selectors, read-only summary projection.

This slice does not add persistent pre-submission registration, automatic polling, background
continuation or its budget. Higher-level backtest-task creation and execution remain separate contracts.
