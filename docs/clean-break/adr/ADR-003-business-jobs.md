# ADR-003 — Business jobs and workers

- Status: Accepted under ADR-0088 (2026-09-25)
- Acceptance: maintainer's explicit long-compute Job/Worker specification, recorded by [ADR-0088](../../architecture/adr/ADR-0088-clean-break-baseline-activation.md).

## Decision

Backtest, training, factor compute, optimization and data import are durable BYQ Jobs executed by specialized workers, not by Agent sessions. A Job has `job_id`, `workspace_id`, type, `QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED`, progress, input reference, result Artifact reference, error and timestamps. A Job persists when an Agent session disappears; an authorized new Agent session can query it by stable ID without reattaching the old DSH session. Worker-specific checkpoint and GPU/process handling remain with the relevant Worker, including ML restart. An Agent uses MCP to start/query/cancel authorized Jobs, then fetches Artifacts.

Existing specialized Job tables may be retained behind a common contract when consolidation would add no value; schema unification must not create a generic workflow engine. Input refs and idempotency prevent duplicate side effects. Job retry rules distinguish safe deterministic work from unknown external outcomes.

## Acceptance

New workspace can run long backtest and ML jobs; session interruption does not cancel them; duplicate commands resolve to one business result; result identity is an Artifact ID.

## Alternative and consequence

Keeping a DSH session or generic workflow alive for long compute would couple compute lifetime to Agent runtime and is rejected. Workers need independent lifecycle, persistence and restart tests.
