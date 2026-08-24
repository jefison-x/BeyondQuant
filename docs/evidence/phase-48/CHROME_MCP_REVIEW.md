# Phase 48 Chrome DevTools MCP review

Date: 2026-08-24 (Asia/Shanghai)

Environment: isolated Compose project, fresh durable users/data, real frontend
and Gateway endpoints. The reviewed owner was the bootstrap administrator;
the golden journey had already persisted conversation, strategy, signal and
Backtest evidence.

## Desktop — 1440 × 1000

- `/agent` exposed exactly the single-level navigation, recent titled
  conversations, durable user turn, activity/approval affordance and composer.
- `/strategy` displayed real immutable versions, strategy source, parameters,
  validation and lineage from the golden journey.
- Lighthouse snapshot on authenticated `/agent`: Accessibility **100**, Best
  Practices **100**.
- Screenshot: `screenshots/desktop-agent.png`.

## Tablet — 1024 × 768

- `/backtest` retained the catalog/detail hierarchy without losing the real
  completed result.
- The selected result showed total return, drawdown, trade count, final value
  and accessible equity chart summary; all eight result tabs remained
  reachable.
- Screenshot: `screenshots/tablet-backtest.png`.

## Mobile — 390 × 844, DPR 3

- `/user/appearance` used the compact section selector and restored the
  durable dark/indigo choice. Display modes, all five accents and semantic
  preview remained operable.
- `/settings/system/overview` became a full-screen modal with a labelled
  section selector, close action and bounded Product status.
- The initial audit caught black selected text on the dark System Settings
  selector (contrast 1.05). The local color override was replaced with the
  global semantic `--byq-text` token, the frontend was rebuilt, and the audit
  was repeated.
- Final Lighthouse snapshot on authenticated mobile System Settings:
  Accessibility **100**, Best Practices **100**.
- Screenshots: `screenshots/mobile-appearance.png` and
  `screenshots/mobile-system-settings.png`.

## Boundary and runtime observations

- Preserved document/fetch/XHR requests were same-origin only. The reviewed
  System Settings load used `/api/auth/me`,
  `/api/product/settings/appearance`, `/api/product/settings/status`,
  `/api/product/operations/status` and `/api/product/data/status`.
- No browser request targeted Backend, MCP, Runtime Adapter, DSH, PostgreSQL,
  Redis or Tushare directly.
- The post-fix console had no warnings or errors.
- The Product operations projection explicitly reported normalized
  WorkflowTrace and did not expose raw DSH events.

## Non-accessibility Lighthouse findings

SEO scored 80 because the authenticated SPA does not currently publish a
dedicated `robots.txt`; Agentic Browsing scored 50 because it does not publish
an `llms.txt`. These are recorded as optional deployment/discoverability work
in the Product gap register, not hidden accessibility or Product-flow
failures.
