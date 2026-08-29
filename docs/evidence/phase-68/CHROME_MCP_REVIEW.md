# Phase 68 Chrome DevTools MCP review

Reviewed on 2026-08-29 against the isolated real Product stack at a loopback
frontend origin. The review used a separate Chrome context from Playwright.

## Product journey

- Durable user login reached the Stock Pool workspace.
- The accessibility tree exposed Dynamic as a catalog filter and pool type.
- A persisted dynamic pool showed `succeeded`, two immutable members, active
  producer state, rule version, closed JSON definition, refresh, draft,
  activate and pause controls.
- A Chrome-originated `POST /api/product/paper/dynamic-pools/preview` returned
  HTTP 200, `authoritative=false`, cutoff `20260828`, and the deterministic
  symbols `300750.SZ`, `000001.SZ`.

## Responsive and accessibility review

- Desktop and `390x844@3` mobile accessibility trees retained headings,
  navigation landmarks, filters, tabs, form labels and dynamic rule actions.
- The initial Lighthouse snapshot identified low contrast on the selected
  dark-theme type filter. Phase 68 changed the active label to the theme's
  `--byq-on-brand` color; the rebuilt mobile snapshot then scored Accessibility
  100 and Best Practices 100.
- Screenshots: `05-chrome-dynamic-desktop.png` and
  `06-chrome-dynamic-mobile.png`.

## Console and network

- Chrome reported no console messages.
- All 24 inspected document/fetch/XHR requests used the same loopback frontend
  origin. Dynamic reads and preview used `/api/product/paper/*`; no browser
  request targeted Backend, MCP, DSH, PostgreSQL, Redis, Tushare, Community, or
  another origin.
