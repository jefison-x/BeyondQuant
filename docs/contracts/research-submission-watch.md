# Research submission receipt watch v1

Maintenance under Accepted ADR-0062 and ADR-0068; Product Phase 97 is unchanged.
This extends F2 for MCP ResearchTask, Experiment and Artifact creation only.
It is domain receipt bookkeeping, not a generic executor, retry queue or agent harness.

Before its single business POST, MCP registers the normalized original request hash
and immutable owner/workspace/conversation/session/trace/type/parent/key selector.
Registration performs one charged exact lookup. Existing matching receipts return
the original object; conflicting or previously registered requests never POST again.
If registration acknowledgement is lost, no business POST is sent. An abandoned
registration can therefore remain unknown, which does not prove business failure.

Gateway's existing durable conversation scan reconciles at most four due watches
per conversation. This read-only path remains enabled independently of F6 model
permission. It calls Backend; it never starts Runtime, invokes a provider or writes
business entities. Every lookup is charged durably before execution, with eight
checks total including registration, a 24-hour deadline, and persistent backoff.
Lookup failures consume checks. Concurrent consumers use row locks and attempt
fencing; restart never refunds attempts. At most 64 immutable watches may be
registered per conversation. Query SQL has a one-second statement timeout.

Closed states are awaiting_receipt, confirmed, conflict and needs_attention.
Confirmed means the exact creation receipt exists, not that research succeeded.
Missing, failed queries, expired deadline or exhausted attempts remain outcome_unknown.
A definitive business HTTP rejection is returned to the original caller; the watch
still checks within its original finite budget and never infers absence from it.
No list search, new idempotency key, automatic business replay or old-task replay.
Direct Product API creation and other non-ML write families are outside this slice.

MCP byq_research_get accepts an exclusive watch_id selector. Backend requires the
original durable identity and conversation. Background F6 reads additionally prove
that the watch belongs to the originally admitted task. Public browser reads use
GET /api/product/research/submission-watches?conversation_id= through Gateway and
normal durable login. No internal identity, payload, hash or raw diagnostic is
projected. Session switching discards stale responses; transport failure retains
the last known projection and offers only a read refresh.

Community source inspection is waived by ADR-0068. The feature checklist is the
BYQ behaviors above, with real Product API desktop/mobile verification required.
