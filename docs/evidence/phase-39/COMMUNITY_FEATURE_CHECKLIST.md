# Phase 39 Community Data Center Checklist

> 本文记录该 Phase 的验收与审计证据。中文负责说明和结论；文件名、路径、命令、字段、状态码、测试计数及原始观察值保持英文原样。

检查日期: 2026-08-22. The Community repository 全程只读。

| Community evidence | Classification | BYQ decision | Status |
|---|---|---|---|
| `DataSourceConfig.vue` provider cards and connection-test feedback | `PORT_UX` + `REFACTOR` | Preserve scannable configuration/test feedback; support only Tushare through BYQ Product API | Implemented |
| Generic provider type, editable Base URL, BaoStock and AKShare paths | `DROP` | Fixed Tushare protocol endpoint; unsupported providers never enter the runtime or UI | Implemented |
| Plain configuration form and returned connection metadata | `REPLACE` | Admin-only write-only Token lifecycle backed by ADR-0019 AES-256-GCM storage; only mask/status/version return | Implemented |
| `DataSync.vue` bounded symbol/date controls and progress/history UX | `PORT_UX` + `REFACTOR` | Canonical symbols, 20-symbol/366-day bounds, durable asynchronous job and per-symbol outcomes | Implemented |
| Static stock pools, fake progress and local-only job history | `DROP` | Real Backend execution and PostgreSQL persistence; no frontend fixture data | Implemented |
| Community cache status and coverage tables | `PORT_LAYOUT` + `REPLACE` | BYQ PostgreSQL market-data rows, source/OHLC validation and observed date bounds replace Redis/cache assumptions | Implemented |
| Scheduler leases/retries and broad multi-dataset sync runtime | `REFERENCE_ONLY` | Keep Phase 39 to a bounded daily-bar execution seam; do not copy the old scheduler/runtime | Boundary preserved |
| Community database/cache connection management | `DROP` | Browser cannot configure or contact PostgreSQL, Redis, Tushare or internal services directly | Implemented |

## Product 验收清单

- [x] Tushare Token create/replace/disable/revoke is administrator-only and
  never returns plaintext or ciphertext.
- [x] The effective provider credential is resolved dynamically inside Backend;
  rotation does not require a service restart.
- [x] Connection test uses one canonical symbol and one date and returns only
  bounded metadata.
- [x] Sync jobs are bounded, idempotent and persisted with per-symbol outcomes.
- [x] Market rows use canonical BYQ schema, explicit units and deterministic
  keep-existing conflict semantics.
- [x] Coverage reports only observed PostgreSQL facts and explicitly does not
  claim calendar completeness.
- [x] Browser calls Gateway Product API only.
- [x] Desktop and 390 x 844 Chrome MCP review completed with no console errors.
- [x] BaoStock, AKShare, arbitrary providers, Redis and Community storage remain
  absent.
