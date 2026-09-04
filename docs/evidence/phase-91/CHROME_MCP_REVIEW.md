# Phase 91 Chrome MCP Review

The approval-center and conversation-continuation journey was reviewed against the isolated real Product stack with Chrome DevTools MCP on 2026-09-04.

## Reviewed journey

- Authenticated as the bootstrap administrator and created a real durable Product conversation.
- Seeded one owner-scoped Agent approval bound to an exact `backtest_task` resource and the conversation's private runtime session.
- Confirmed the header bell changed from `待人工审批，无待办` to `待人工审批，1 项` without visiting a business page.
- Opened the desktop approval center at 1440×900 and confirmed the localized action, reason, exact resource and public conversation title were visible. `批准` and `拒绝` were the only decision controls.
- Rejected the request and confirmed the pending count changed to zero and navigation returned directly to `/agent?session=<public-conversation-id>`. No private runtime-session identifier was rendered or placed in the browser URL.
- Repeated the inbox review at 390×844 mobile emulation and confirmed the drawer, resource context and both decision controls remained reachable without a business-page approval step.
- Source and rendered-flow inspection confirmed Stock Pool, Strategy, Model Research and Backtest pages do not render approval decision buttons. Direct Product actions retain their own explicit confirmation dialogs and record domain approval internally where required.

## Browser boundary

- Chrome reported no console messages during the reviewed journey.
- All 18 preserved document/fetch/XHR requests used the isolated frontend origin.
- Approval polling used `GET /api/product/approvals?status=pending&limit=20&offset=0`; the browser did not request historical approval rows or call Backend, MCP, DSH, PostgreSQL, a provider, or GitHub directly.
- Conversation replay and WorkflowTrace requests used the public conversation identifier only.

The isolated review data was disposable and was not copied to or used by production.
