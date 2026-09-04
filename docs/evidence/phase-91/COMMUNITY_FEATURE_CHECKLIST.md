# Phase 91 Community Feature Checklist

| Feature / invariant | Community evidence | Decision | Phase 91 result |
|---|---|---|---|
| Global approval inbox and badge | `frontend/src/components/agent/GlobalApprovalCenter.vue` | `PORT_UX` / `REFACTOR` | Header-only pending inbox, server paging, focus/visibility/event refresh. |
| Localized action summary and resource context | `GlobalApprovalCenter.vue`, `ApprovalManagementPanel.vue` | `PORT_UX` | Closed labels, reason, exact resource and public conversation title. |
| Approval controls inside assistant drawer/business context | `XiaobaAssistantDrawer.vue` | `DROP` | Approval buttons exist only in the global center. |
| “Approve and execute” coupled endpoint | `api/agent.js`, approval components | `REPLACE` | Durable decision and conversation continuation are separate; domain state is re-read through MCP. |
| Raw arguments and runtime/session IDs in browser | approval detail helpers | `DROP` | Product allowlist projection exposes only public conversation identity and exact resource identity. |
| Polling/focus invalidation | `GlobalApprovalCenter.vue` | `PORT_UX` / `REFACTOR` | Pending-only 15-second visible polling plus current WorkflowTrace invalidation. |
| Direct Backend/Agent API | `api/agent.js` | `REPLACE` | Browser uses same-origin Gateway/Product API only. |

The Community repository and database remained read-only. No source, runtime, storage, credentials, or Git history were copied or modified.
