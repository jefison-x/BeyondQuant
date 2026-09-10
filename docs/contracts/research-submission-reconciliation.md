# Research submission reconciliation v1

Scope: Accepted ADR-0062, existing ResearchTask/Experiment/Artifact creation receipts.
This is an exact read contract, not a new queue, write retry or background continuation.

- Backend GET `/v1/research/submissions/reconcile` requires trusted active owner/workspace context,
  a closed `entity_type` and the original bounded `idempotency_key`.
- ResearchTask keys are owner-scoped; no task ID is accepted. Experiment/Artifact keys require
  the original task ID and that task's verified owner/workspace. Never search another task or a list.
- Return `research-submission-reconciliation.v1`, `confirmed` and the existing public entity only
  when the exact persisted mapping exists. The entity's domain status is independent of confirmation.
- Otherwise return `outcome_unknown`, without an entity or a claim of absence/failure. Query failure
  is not evidence that the creation failed. No read path computes, creates, replays or changes an entity.
- Persistent database mappings survive Backend restarts; a late commit becomes visible on a later
  exact read. This slice does not implement a persistent watch, automatic polling or budget reset.
- Extend existing `byq_research_get` with exactly one of entity_id or idempotency_key; task_id is
  accepted only for Experiment/Artifact key lookup. No new tool/role privilege is added.
- A matching key confirms the committed request's result, not a modified replacement payload.
  Existing create conflict rules remain authoritative. Projection never includes private request hashes.

Required evidence: all three kinds, missing then late commit, database connection/store reinitialization, exact task/key scope,
foreign owner/workspace, disabled identity, malformed/ambiguous selectors and no writes on lookup.
Unbounded retry, lists used as absence proof, and automatic downstream model/worker actions are prohibited.
