# Phase 92 Chrome MCP Review

The central-feedback Product flow was reviewed against an isolated real BYQ stack with Chrome DevTools MCP on 2026-09-04.

## Reviewed journey

- Logged in as the bootstrap administrator and created a real owner-scoped feedback draft plus Backend-generated public preview.
- Seeded the same action Xiaoba requests: `byq_feedback_submit` bound to the exact `product_feedback/<feedback_id>` and its original durable conversation.
- Confirmed the header bell changed to `待人工审批，1 项` without visiting a business page.
- Opened the global center and confirmed `提交产品反馈`, the disclosure reason, exact feedback resource, source conversation, and only the
  `批准` / `拒绝` decision controls were visible.
- Opened `/feedback` and confirmed it explicitly says the official Hub is not yet connected, the draft remains locally queued, and the user does
  not need a GitHub account.
- At 390×844 the feedback dialog had no horizontal overflow (`scrollWidth === clientWidth === 390`).
- In a separate no-GitHub-credential integration pass, submitted a real Browser/Product API preview. The response first reported Hub state
  `queued`; the containerized relay delivered it to a standalone Hub and the next bounded read reported `received` with a receipt. The Hub
  admin projection contained the exact preview hash and public snapshot, and no Issue was created.

## Browser boundary

- Chrome reported no Console messages.
- All nine preserved document/fetch/XHR requests used `http://127.0.0.1:18080` and same-origin `/api/*` or `/v1/agent/*` routes.
- The browser did not call Backend, MCP, DSH, PostgreSQL, the central Hub, GitHub or any market-data provider directly.

Approval execution itself is covered by the Backend contract test that rejects mismatched approvals and accepts only the exact approved
action/resource/version/hash. The browser record was intentionally left pending so the manually seeded test conversation did not invoke an
unrelated live model continuation. All review data and volumes were disposable.
