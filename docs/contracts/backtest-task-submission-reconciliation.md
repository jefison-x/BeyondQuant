# Backtest task submission reconciliation v1

Accepted ADR-0044/0062/0025; derived signal-backed task receipt, without a second task table.

- GET `/v1/research/backtest-tasks/reconcile` accepts original `task_id` and
  `idempotency_key` (1–128 trimmed characters), with trusted active owner/workspace.
- Verify ownership of the original ResearchTask, then read the exact signal job
  restricted by owner/workspace/task/key. Existing keys are owner/workspace scoped;
  task_id is an additional guard, not a new independent key namespace.
- Return `backtest-task-submission-reconciliation.v1`, original task/key, and
  `confirmed` with a closed `receipt`: backtest_task_id, signal_producer_job_id,
  signal_status. The facade ID is derived using the existing reversible mapping.
- No match means `outcome_unknown` without a receipt; never prove absence from a list
  or permit repeat submission. Database errors remain unavailable, not confirmed.
- Confirmation proves the committed shared signal component identity, not which
  facade/producer endpoint created it or whether the later pool-reference write completed.
  Direct signal jobs share this namespace and already have derived task identities.
- The receipt does not include preparation, raw inputs, readiness, request hash or
  full task projection. Query the recovered task ID through the existing GET for
  current full state. This read never prepares data, requests repair, creates jobs,
  checks current approval, claims work or triggers execution.
- Extend existing `byq_backtest_task_get`: either backtest_task_id (including existing
  ML-derived IDs), or original task_id plus key for the signal-backed creation path.
  Reject ambiguous/incomplete selectors without Backend access. ML receipt lookup
  remains its existing contract; this key selector cannot identify an ML prediction.
- Matching the original key never validates a replacement payload or grants the next action.

Evidence: real task creation, late commit, exact key/task, fresh-process persistent read,
owner/workspace/disabled/anonymous isolation, malformed selectors, and no side effects.
Pre-submission durable registration, readiness-before-create repair, concurrent create
conflicts, persistent watch/budgets and automatic continuation remain separate remediation.
