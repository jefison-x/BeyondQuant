# Phase 10 — Adapter field ownership audit

This audit distinguishes one live DSH process handle from a BYQ Agent
harness. It applies to the pinned 0.1.5rc1 root-scoped transport and is
checked against [ADR-002](adr/ADR-002-dsh-boundary.md). It does not grant
cross-process Agent attach or replay.

| Adapter state | Actual use | Owner / Phase 10 disposition |
|---|---|---|
| `RuntimeSession.session_id`, `trace_id`, `boot_id`, principal, workspace | Correlate one live Adapter boot and authenticate Product requests. | BYQ transport identity; keep in memory. A missing boot cannot be rebuilt from historical state. |
| `model_resolution` | Supply configured provider/model to DSH at process start. | Thin configuration translation; keep for the live binding. |
| `pending_conversation_context` | Hold bounded completed public Product messages until the next explicit root input is sent. | Product transcript input correlation; keep only within this live Adapter boot. The former `pending_conversation_recovery` and failed-turn inference were removed. No private DSH state is restored. |
| `status`, `active_run`, `process_used`, `process_closed`, `process_closing` | Observe one owned process call; reject duplicate prompt; close/cancel and discard late result. | Transient transport safety. Retain only while needed for exact at-most-once call admission; no durable Agent status store or restart path. DSH owns the actual run and context. |
| `RuntimeGeneration` current pointer, native ID, `executor_epoch` | Bind callbacks and MCP credentials to one dedicated DSH process/root; fence stale callbacks. | Current process handle, not a persisted generation ledger. Retain the single live pointer for root-scoped authority; do not add history/takeover/rebind. |
| `ActiveRun` child progress/watchdog | Bound a stalled delegated call in the pinned release and close its dedicated process. | Temporary ADR-002 process-safety exception; no child rebind, scheduling or recovery. |
| `prompt_idempotency` | Return the original accepted run receipt for repeated delivery of the same Product message. | BYQ external-action safety; retain only within one Adapter boot. Unknown receipt remains `outcome_unknown`; no prompt replay. |
| `terminal_receipts`, `pending_terminal_receipts`, domain-call evidence/sequences, `release_finalized` | Deliver exact Backend root close and domain evidence before next admission. | BYQ business authority, not Agent execution; retain until exact acknowledgement. Phase 14 may normalize storage and Phase 17 may reduce delivery indirection. |
| `budget_receipts`, continuation deadline | Ensure bounded business continuation reservation and terminal settlement. | BYQ business admission; keep only for current live root and exact receipt reconciliation. |
| `interrupted_run_id`, `continuity` | Explain an interrupted live call without restarting it. | Bounded status projection only. Failure without an interrupted run must remain a failure. No same-session new process after either terminal state. |
| `sequence`, `history`, `subscribers`, normalization | Project DSH notifications into bounded Product trace and live SSE. | Transport notification projection, not checkpoint or replay truth. Product DB state remains current truth. Trim residual trace delivery in Phase 17. |

The Adapter must not add persistent Agent session/run/generation rows, a
generic recovery coordinator, child takeover or old-session compatibility.
Healthy next-root admission is a new explicit Product call. A failed or
interrupted root is never reconstructed under the same session ID. The
remaining in-memory record exists solely while this Adapter boot owns the
DSH process and exact BYQ business call evidence.
