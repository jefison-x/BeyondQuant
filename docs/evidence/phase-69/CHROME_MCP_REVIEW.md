# Chrome DevTools MCP review

Date: 2026-08-29
Target: isolated full Compose frontend at `http://127.0.0.1:32777`

## Desktop

- Authenticated as the CI admin through durable browser login.
- Opened the real custom pool with two persisted immutable snapshots.
- Confirmed readiness `current`, current version `v2`, and two snapshot rows.
- Compared the latest two snapshots: added 1 (`300750.SZ`), removed 1, changed weight 0, retained 1.
- Console warning/error/issue query returned no messages.
- Network inspection showed readiness and snapshot-diff returning 200 through same-origin `/api/product/...`; no direct Backend, MCP, DSH, PostgreSQL or provider request was observed.

## Mobile

- Emulated `390x844`, DPR 3, mobile and touch.
- Confirmed responsive catalogue/detail presentation and the same snapshot diff values.
- Lighthouse snapshot: Accessibility 100, Best Practices 100, SEO 80, Agentic Browsing 50.

## Restart recovery

- Restarted the exact Phase 69 Backend and Gateway containers without replacing PostgreSQL.
- Logged in again and read the same pool: readiness remained `current`; both snapshots remained present; diff remained added 1, removed 1 and retained 1.

Screenshots are `03-chrome-closure-desktop.png` and `04-chrome-closure-mobile.png`.
