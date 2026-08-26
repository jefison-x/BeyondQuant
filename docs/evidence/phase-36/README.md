# Phase 36 — Agent workbench depth evidence

> 本文记录该 Phase 的验收与审计证据。中文负责说明和结论；文件名、路径、命令、字段、状态码、测试计数及原始观察值保持英文原样。

Date: 2026-08-22

## Reference and classification

The read-only Community baseline was inspected at commit
`58dd99d55fef9f1c982b4143374a7f67f3da8c78`. The reference server used a
temporary browser-only authentication shim and empty API collections solely to
render the existing Community UI. It is visual/interaction evidence, not
functional evidence, and neither the Community repository nor its data was
modified.

| Community element | Decision | BYQ result |
|---|---|---|
| Agent page information hierarchy and starters | `PORT_UX` / `PORT_LAYOUT` | Continuous session, starters, conversation and context rail |
| Strategy, stock-candidate and optimization cards | `REFACTOR` | Closed ADR-0018 WorkflowTrace discriminated unions with fixed actions |
| AgentThinking | `PORT_COMPONENT` | Bounded public activity panel; raw DSH events and hidden reasoning excluded |
| ApprovalManagementPanel | `PORT_COMPONENT` | Owner-scoped fresh approval reads and decisions |
| GlobalApprovalCenter | `PORT_COMPONENT` | App-shell approval drawer using Product API only |
| XiaobaAssistantDrawer | `PORT_COMPONENT` / `PORT_UX` | Responsive route-aware assistant with allowlisted page context |
| Community raw tool/event rendering | `REPLACE` | Curated capability/activity vocabulary at the Runtime Adapter boundary |

## Community-derived feature checklist

- [x] Session history, reload/replay, and new-session flow use durable Product
      API sessions; a card remains available after route changes and reload.
- [x] Conversation starters submit real turns.
- [x] Public answer deltas render without hidden reasoning or raw event data.
- [x] Strategy-draft, stock-candidates and optimization cards are normalized,
      revisioned and actionable.
- [x] Backtest-context and approval cards are hydrated from owner-scoped BYQ
      domain resources; rejected references become public projection notices.
- [x] Execution progress shows curated public stages only and is bounded.
- [x] Local and global approval surfaces fetch current state before decisions.
- [x] Xiaoba assistant works on desktop and mobile with allowlisted route
      context only.
- [x] Browser traffic uses same-origin Gateway/Product API routes only; there
      are no direct Backend, MCP, DSH, PostgreSQL, Redis or Tushare requests.

## Chrome DevTools MCP evidence

- [`community-agent/01-desktop-agent-workbench.png`](community-agent/01-desktop-agent-workbench.png)
  — read-only Community visual/interaction baseline.
- [`byq-agent/02-workflow-card.png`](byq-agent/02-workflow-card.png) — real BYQ
  Product API session producing an actionable strategy-draft card and curated
  activity projection.
- [`byq-agent/03-mobile-assistant.png`](byq-agent/03-mobile-assistant.png) —
  390×844 touch viewport with the responsive Xiaoba assistant drawer.
- [`byq-agent/04-stock-candidates.png`](byq-agent/04-stock-candidates.png) —
  real Product API turn and market-data research producing a bounded
  stock-candidates proposal card; its fixed action navigated to `/stock-pool`.
- [`byq-agent/05-optimization-card.png`](byq-agent/05-optimization-card.png) —
  optimization proposal based on an explicitly user-supplied frozen-summary
  review input. The card and answer identify that provenance and do not claim
  BYQ domain authority; its fixed action navigated to `/strategy`.
- [`byq-agent/06-domain-approval-card.png`](byq-agent/06-domain-approval-card.png)
  — a real pending `byq_backtest_submit` approval, owner-scoped and hydrated
  by Gateway as a domain-authority card. No backtest was submitted.
- [`byq-agent/07-global-approval-center.png`](byq-agent/07-global-approval-center.png)
  — the same pending approval loaded independently through the global Product
  API approval surface. The acceptance run intentionally left the decision
  pending; it did not grant execution authority.

The card action was exercised and navigated to the fixed `/strategy` route.
Returning to `/agent` and reloading replayed the same bounded normalized trace
and restored the card from sequence zero.
Chrome network inspection recorded only same-origin `/api/...`,
`/v1/agent/...`, and `/v1/workflows/...` calls. There were no console errors;
one unrelated Element Plus radio-label deprecation warning was observed on the
existing Strategy page.

## Contract and test evidence

- Shared Python contract tests reject unknown fields, invalid sources,
  oversized payloads, non-finite values and secret-shaped keys.
- MCP tests validate proposal card construction and role allowlists.
- Runtime Adapter tests cover DSH normalization, namespaced capabilities,
  hidden-event exclusion, UTF-8 splitting, deduplication and budgets.
- Gateway tests cover owner-scoped hydration, cross-owner/missing reference
  rejection, monotonic revisions and trace replay.
- Frontend unit tests cover strict parsing, revision folding and activity
  bounds; the production build succeeds.
