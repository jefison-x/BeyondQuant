# Phase 42 Conversation-First Shell Evidence

> 本文记录该 Phase 的验收与审计证据。中文负责说明和结论；文件名、路径、命令、字段、状态码、测试计数及原始观察值保持英文原样。

## Implemented surface

- `/` redirects authenticated users to `/agent` while `/dashboard` preserves
  the prior dashboard deep link.
- The desktop shell has exactly five primary actions: New Research
  Conversation, Stock Pool, Strategy, Backtest, and Conversation History.
- Current Product sessions are shown as bounded identifier fallbacks. No
  durable title/history capability is claimed before Phase 43.
- The bottom account menu reaches Profile, Assets, Paper Trading, Models,
  Agent Policy, research/approval, Data Center, status, and administrator-only
  System Settings.
- The mobile bottom bar was replaced with a labelled modal drawer; native
  buttons expose focus-visible states and the drawer receives modal focus.
- Vite development proxying now includes `/v1`, matching the deployed
  same-origin Gateway boundary used by agent sessions and WorkflowTrace SSE.

## Chrome DevTools MCP review

Reviewed against the running Product API on 2026-08-23.

- Desktop: default login destination `/agent`, flat sidebar, recent live
  session, compact toolbar, conversation workspace and user trigger visible.
- Mobile 390×844: sidebar absent until `打开产品导航`; modal drawer exposes all
  five primary actions, recent session and bottom user trigger.
- Admin account menu includes `系统设置`; automated E2E separately proves it
  is absent for a normal user.
- Console after reload: only Vite connection debug entries; no application
  errors or warnings.
- Network after reload: auth, settings, approvals, `/v1/agent/sessions`, and
  normalized WorkflowTrace SSE all returned 200 from the frontend origin. No
  browser request targeted Backend, MCP, DSH, PostgreSQL, Redis, or Tushare.

Screenshots: `desktop-shell.png` and `mobile-navigation-drawer.png`.

## Automated evidence

- frontend production build: passed;
- Vitest: 21 files, 57 tests passed;
- mocked Playwright: 12 tests passed, including default Xiaoba navigation,
  preserved deep links, mobile drawer, user destinations, and admin-only
  settings;
- repository architecture suite: 44 tests passed.
