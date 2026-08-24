# Phase 45 acceptance evidence

Phase 45 implements ADR-0024's route-backed administrator System Settings
surface without changing ADR-0022's Product/Engineering ownership boundary.
The relevant Community operations and data pages were inspected read-only and
classified in `docs/migration/COMMUNITY_MIGRATION_INVENTORY.md`. Grouped
navigation, status-card density, refresh behavior and responsive interaction
were used as evidence; Community APIs, storage, Redis, database switching,
arbitrary provider controls and raw runtime/graph state were not copied.

## Product and boundary evidence

- One `/settings/system/*` route family provides twelve sections: Overview,
  Data, Sources, Cache, Database, platform Models, Agents, Budget, Runtime,
  Workflow diagnostics, Access and Audit.
- Desktop uses a large two-column modal; 390x844 uses a full-screen surface
  and keyboard-operable section selector. Each section is refresh/deep-link
  safe and closing returns to a validated local source route.
- Existing `/admin/*`, `/operations`, `/system-status` and `/data-center`
  entry points redirect explicitly. Unknown and old Graph sections fail safe
  to Overview or normalized Workflow diagnostics.
- The account menu exposes exactly one administrator System Settings entry.
  Normal users neither see it nor pass the direct-route guard.
- Browser inspection showed only same-origin `/api/auth/*` and
  `/api/product/*` requests. No Backend, MCP, DSH, PostgreSQL, Redis, Tushare
  or raw-event endpoint crossed the browser boundary.
- The dialog has an accessible name, makes its background inert, preserves
  focus semantics, and audit records use semantic captioned tables.

## Automated verification

- Frontend production build: passed.
- Frontend unit tests: 64 passed across 22 files.
- Mocked Chromium Product journeys: 13 passed, including administrator menu,
  legacy redirect, source-route restoration and normal-user denial.
- Desktop and mobile Lighthouse snapshot audits: Accessibility 100 and Best
  Practices 100.
- Clean isolated Compose smoke: passed.
- Real Product API Chromium journeys: 3 passed, including the complete My
  Space credential/binding/policy/asset flow followed by Database and Runtime
  System Settings navigation.
- Complete local CI: all 13 checks passed.

## Chrome DevTools MCP review

- `system-settings-desktop.png`: 1440x900 grouped two-column Overview using
  live Product API service, PostgreSQL, data and runtime projections.
- `database-desktop.png`: real `byq_domain`, PostgreSQL version, migration and
  bounded resource-count diagnostics.
- `system-settings-mobile.png`: 390x844 full-screen modal with section selector
  and stacked content.
- `lighthouse-desktop.*` and `lighthouse-mobile.*`: accepted production
  Compose accessibility reports.
- Console review found no warnings or errors. Legacy `/admin/graphs` resolved
  to `/settings/system/workflow`, and closing restored `/agent`.

## Community feature checklist

| Capability | Result |
|---|---|
| Grouped administrator navigation | PASS — twelve closed BYQ sections in one route-backed surface. |
| Overview, data, storage and runtime status | PASS — real bounded Product API projections. |
| Refresh and deep-link behavior | PASS — section URLs, browser history and legacy redirects preserved. |
| Access and audit separation | PASS — distinct views with semantic tables and append-only records. |
| Desktop and mobile interaction | PASS — two-column dialog and full-screen mobile selector. |
| Administrator authorization | PASS — hidden entry plus direct-route guard for normal users. |
| Internal API/runtime isolation | PASS — same-origin Gateway/Product API traffic only. |
| Community infrastructure controls | REPLACED/DROPPED — no Redis, arbitrary SQL/provider, database switching or raw DSH state. |
