# Phase 65 Community inspection and classification

Read-only inspection covered Community `SystemMaintenanceWorkbench.vue`, `RuntimeOperationsView.vue`,
`packages/byq-plugin-sdk/.../registry.py` and the private plugin-registry design note.

| Community capability | Classification | Phase 65 decision |
| --- | --- | --- |
| grouped administrator operations, status cards, table/detail affordance | `PORT_LAYOUT` / `PORT_UX` | Reuse the current BYQ System Settings hierarchy, responsive cards, table and drawer language. |
| local-path plugin install/remove and mutable registry file | `DROP` | It accepts operator paths and persists a mutable registry; incompatible with ADR-0038/0040. |
| runtime/database/Redis configuration write controls | `DROP` | Browser receives no infrastructure credentials, runtime control, SQL or service-switch authority. |
| bounded runtime diagnostics and empty/loading/detail states | `PORT_UX` / `REPLACE` | Use normalized Product API Registry/readiness projection, not Community runtime schemas. |
| strategy/data/backtest extension mechanisms including BaoStock/AKShare/VectorBT | `DROP` | They are not DSH Product plugins and remain prohibited by `AGENTS.md`. |
| dedicated Plugin Center page | `REPLACE` (new BYQ surface) | Community has no safe equivalent; build inside existing admin shell over Phase 63 contracts. |

No Community source was copied or modified. Only its operational information hierarchy and generic responsive UX
were treated as evidence.
