# ML submission reconciliation v1

Status: implementation in progress under Accepted ADR-0062; not release acceptance.

- MCP and Product Gateway register a receipt watch before attempting a training POST.
  Registration binds trusted owner/workspace and the exact task, experiment, immutable
  strategy artifact, pool snapshot and original idempotency key. It never starts training.
- A registration failure prevents the training POST. An existing unresolved watch is
  queried, not dispatched again automatically. Explicit 4xx rejection remains distinct
  from a missing or malformed receipt.
- The existing trusted ML Worker checks due watches in bounded batches, using only
  exact owner/workspace/idempotency lookup. No model, provider, list inference or new
  workflow executor is involved. Registration and reconciliation do not grant approval.
- Maximum eight scheduled checks, with persistent deadlines and next-check timestamps;
  backoff delays are 5, 15, 60, 180, 600, 1800 and 3600 seconds after successive misses.
  Overall observation deadline is 24 hours. Restarts never reset either budget.
- States: `awaiting_receipt`, `confirmed`, `rejected`, `needs_attention`. Only an
  explicit Backend 4xx submission rejection records `rejected`. Exhaustion is unknown,
  never proof of rejection or absence. A later exact committed receipt may still
  confirm the watch without initiating any downstream action.
- Training receipt commit links matching watches atomically. Workers serialize watch
  checks in short database transactions. Frozen request mismatch is a conflict.
- Public watch projection includes identity, state, attempts, next check/deadline and
  confirmed training run ID only; no raw input, secrets or worker claim credentials.
- These watches do not claim that training, prediction, backtest or the user's complete
  research goal is finished. Task continuation and action authorization remain separate.

Required evidence: late commit, restart, duplicate registration, changed request,
cross-owner denial, check-budget exhaustion, post-exhaustion genuine receipt and
no automatic resubmission. Current paid-model acceptance remains separately gated.
