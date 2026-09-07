# Approval continuation reliability

Status: Post-U8 implementation slice under Accepted ADR-0062; not full F5/F6 acceptance.

The approval decision, continuation transport receipt, domain action and user goal
are separate facts. `submitted` means a valid Adapter acceptance receipt only.

- Backend persists the continuation attempt before Gateway sends a prompt. Exact
  attempt matching fences every acknowledgement. At most eight attempts known to
  have been unaccepted may be dispatched; exhaustion is `needs_attention`.
- A 30-second stale `submitting` claim becomes `outcome_unknown`, not a new claim.
  Neither unknown nor exhausted state authorizes automatic resubmission. A late
  genuine acknowledgement for the same attempt can change unknown to submitted.
- Gateway requires `accepted=true` and a nonempty BYQ run identity. Timeout, 5xx
  and malformed acceptance do not become ordinary retryable failures.
- Gateway performs one exact read of the original Adapter prompt receipt using
  the original session, idempotency key and SHA-256 of the original instruction.
  No instruction text is placed in the query. The read never starts or restores
  a DSH process. A matching receipt can confirm acceptance without another POST.
- Runtime's `prompt-receipt.v1` is an operational observation, not business data.
  It returns accepted plus the BYQ run ID, or outcome_unknown. Lost/recreated
  in-memory state proves neither rejection nor absence. A content mismatch is 409.
- The UI stops retrying unknown/exhausted continuations, limits an open view to
  eight checks, and ignores late responses after conversation switch/unmount.
  The Backend attempt limit survives restart; the UI limit is per mounted view.

These eight transport attempts are not the eight task-granted background model
turns in ADR-0062. They neither grant new actions nor implement task continuation
permission. Persistent Adapter prompt receipts, task-stage evidence and task-bound
notification consumption remain separate open work. Historical production approvals
are not replayed or migrated by this slice.
