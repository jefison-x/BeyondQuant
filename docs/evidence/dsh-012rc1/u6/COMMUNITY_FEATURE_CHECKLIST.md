# U6 Community review and feature checklist

Status: IN_PROGRESS; no U6 completion or production deployment claimed.

Read-only reference: BeyondQuant-community frontend `AgentView.vue`, composer
lines 335–375 and `submitMessage` lines 862–918. The Community composer preserves
the familiar multiline/Ctrl+Enter interaction, but clears input before its raw
Agent stream has accepted the request. Its raw runtime/stream context is not a
BYQ Product contract.

| Feature | Classification | U6 decision / acceptance |
|---|---|---|
| Multiline input and Ctrl+Enter | PORT_UX | Preserve existing BYQ interaction. |
| Clearing input before acceptance | REPLACE | Maintenance rejection must retain input and remove only its unaccepted optimistic bubble. |
| Raw stream/context and direct Agent coupling | DROP | Use existing Gateway Product API and normalized WorkflowTrace only. |
| Global approval center | PORT_UX, existing Phase 91 classification | Decisions remain durable; maintenance does not claim or submit queued continuation. |
| Product deployment controls | DROP | No browser/DSH gate writer or deployment button. Operator alone writes gate state. |

Completed partial evidence: unit/API tests; desktop/mobile Chrome MCP maintenance
review; same-origin request checks; first diagnostic logical backup/actual restore,
old→new approval continuation and cleanup; corrected full old→new→old journey,
public follow-ups and namespace integrity. See [validation](VALIDATION.md).
Still pending: final artifact identity/CI freeze. This checklist does not mark
U6 complete.
