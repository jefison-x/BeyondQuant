# U6 Community review and feature checklist

Status: VERIFIED for U6 isolated acceptance; production deployment is NOT_RUN.

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

Final retained-artifact evidence: full CI 26/26, frontend 150 unit / 20 mocked /
nine real Product browser checks, [actual desktop/mobile Chrome MCP review](CHROME_REVIEW.md),
maintenance input preservation, same-origin requests, durable approval continuation
exactly once and truthful Plugin Center active identity. Logical restore, full
old→new→old and namespace checks passed; [model review](MODEL_REVIEW.md) preserves
the rejected G2 sample separately from its successful context requalification.
See [validation](VALIDATION.md). This is not U7 deployment or U8 observation.
