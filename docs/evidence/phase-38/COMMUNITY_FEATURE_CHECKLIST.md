# Phase 38 Community Operations Checklist

Inspection date: 2026-08-22. Community repository was read-only.

| Community evidence | Classification | BYQ decision | Status |
|---|---|---|---|
| `SystemMaintenanceWorkbench.vue` tabbed layout, status cards, coverage tables | `PORT_LAYOUT` + `PORT_UX` + `REFACTOR` | Keep scannable workbenches and refresh UX; use BYQ Product API and PostgreSQL topology | Implemented |
| Community database/Redis credential forms, init/migration/rebuild controls | `DROP` + `REPLACE` | No browser connection config, Redis, arbitrary SQL, or destructive default; show bounded PostgreSQL facts | Implemented |
| `ModelOperationsView.vue` provider/model/binding grouping | `PORT_UX` + `REFACTOR` | Metadata-only system health; ADR-0019 remains write-only and arbitrary Base URLs stay rejected | Implemented |
| `RuntimeOperationsView.vue` status/run drill-down | `PORT_UX` + `REFACTOR` | Runtime Adapter session counts and normalized DSH token usage; no raw diagnostics/events | Implemented |
| `GraphOperationsView.vue` run/checkpoint visualization | `REPLACE` | BYQ AgentRun/WorkflowTrace correlation replaces Community Graph/checkpoint runtime | Implemented |
| `AccessControlOperationsView.vue` role cards and audit filters | `PORT_UX` + `REPLACE` | Durable BYQ roles/status counts plus bounded Agent/operations audit | Implemented |
| `DataSourceConfig.vue` generic provider/Base URL form | `REFERENCE_ONLY` + `DROP` | Tushare-only readiness in Phase 38; credential CRUD/test belongs to Phase 39; BaoStock/AKShare dropped | Implemented boundary |
| `DataSync.vue` sync controls and fixture stock pools | `REFERENCE_ONLY` | Real Tushare sync jobs/coverage belong to Phase 39; no fake data or disabled controls in Phase 38 | Deferred to Phase 39 |
| `SystemAnalytics.vue` compact metric cards | `PORT_STYLE` + `REFACTOR` | Responsive phase-owned metric cards using real operations projections | Implemented |

## Product acceptance checklist

- [x] Nine admin routes have real Product API projections and no placeholder.
- [x] Normal users cannot access the operations workbenches or rich endpoint.
- [x] PostgreSQL market-data status explicitly replaces Redis.
- [x] Model/source reads expose metadata only; secrets and envelopes are absent.
- [x] DSH token usage is exact-field normalized and deduplicated in Runtime Adapter.
- [x] Budget threshold writes are RBAC-protected, versioned, idempotent, and audited.
- [x] Browser calls Gateway Product API only.
- [x] Real Product API desktop/mobile Chrome MCP review recorded.
- [x] Full local CI recorded: all 13 checks passed, including Compose smoke
  and three real Product API E2E journeys.
- [x] PR CI green before merge: GitHub Actions run `32547803282` passed the
  complete self-hosted local-CI job in 3m44s.
