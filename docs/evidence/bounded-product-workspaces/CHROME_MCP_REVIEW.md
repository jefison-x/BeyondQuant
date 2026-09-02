# Bounded Product Workspaces — Chrome MCP Review

Date: 2026-09-02 (Asia/Shanghai)

## Scope

- `/model-research`
- `/strategy`
- `/settings/system/data`

The review used an isolated real Compose stack built from
`perf/bounded-product-workspaces`, durable login, real Product API data, and
Chrome DevTools MCP. The production stack was not modified.

## Before baseline (production, read-only)

| Product request | Decoded bytes | Wall time |
|---|---:|---:|
| `GET /api/product/ml/workspace` | 38,959 | 2,711.3 ms |
| `GET /api/product/research/artifacts` (Strategy page hidden preload) | 13,997,598 | 850.9 ms |
| `GET /api/product/data-center/status` | 59,615 | 2,552.2 ms |

The data-center delay was isolated to `MLTrainingRunStore.list_recent`: its
old `SELECT *` took 3,480.4 ms because PostgreSQL returned large frozen input
JSON that the public projection discarded afterward.

## Real browser result

| Surface | Observed Product requests | Result |
|---|---|---|
| Model Research overview | one `GET /api/product/ml/workspace` | 24.6 ms in the isolated seeded stack; no prediction-row request occurred on the overview tab. |
| Model Research prediction tab | `GET /api/product/ml/prediction-runs/{id}/rows?query=&limit=50&offset=0` | Request appeared only after clicking the tab; rows were filtered/paged in PostgreSQL. |
| Strategy | paged `/strategies`, bounded `/research/task-options`, then exact selected artifact/approval/history/count requests | 15.7 ms for the 10,183-byte catalogue and 15.3 ms for the 832-byte task options; the generic Artifact collection was absent. |
| Data Management initial coverage tab | `GET /api/product/data-center/status?view=summary` plus bounded pool options | 4,859 decoded bytes, 34.6 ms. |
| Data Management sync tab | `GET /api/product/data-center/status?view=full` | Full activity projection appeared only after opening the tab; 25.1 ms in the isolated seeded stack. |

No console warning, error, or browser issue was reported. All browser traffic
remained same-origin Gateway/Product API traffic.

## Community checklist

| Read-only Community reference | Classification | Verified disposition |
|---|---|---|
| `frontend/src/views/StrategyView.vue` | `PORT_UX` | Server-paged catalogue and selected detail retained; legacy `/api/v1` binding and broad preload are not used. |
| `frontend/src/views/system/DataSync.vue` | `PORT_UX` + `REFERENCE_ONLY` | Task/progress UX retained; fake progress, hard-coded pools, TODO calls, and legacy provider assumptions remain dropped. |
| `frontend/src/views/system/DataSourceConfig.vue` | `PORT_UX` | Secret-safe source states remain behind Product API/admin authorization. |
| Community model settings pages | `REFERENCE_ONLY` | They are not an auditable ML workspace; ADR-0043 BYQ contracts remain authoritative. |

## Automated evidence

- Architecture: 81 tests passed.
- Backend: complete clean-PostgreSQL suite passed.
- Gateway: complete suite passed.
- Frontend: build passed; 47 files / 131 tests passed; dependency audit found
  zero vulnerabilities.
- Isolated real Product smoke: 11 checks passed, including 6 Playwright flows,
  MCP contracts, ML prediction, worker restart persistence, and two-user
  isolation.
