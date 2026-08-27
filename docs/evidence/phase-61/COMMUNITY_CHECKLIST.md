# Phase 61 Community checklist

Read-only source: `/home/jefison/projects/BeyondQuant-community`.

| Surface | Classification | Phase 61 result |
|---|---|---|
| `LoginView.vue` labels and autocomplete | `REUSE_AS_IS` semantics / `REPLACE` auth | BYQ fields use labels, ids, names and standard username/current-password autocomplete; durable Product login remains authoritative. |
| `AgentThinking.vue` collapsed progress | `PORT_UX` / `REFACTOR` | Main conversation shows normalized current phase and elapsed time. Tool names/reasoning/control mechanics are `DROP`. |
| Xiaoba current-page backtest intent | `PORT_UX` / `REFACTOR` | Completed Backtest offers analysis/optimization drafts with current job context; no navigation-time execution. |
| Strategy catalogue/detail | `PORT_LAYOUT` / `PORT_UX` / `REFACTOR` | Name, description, status, approval, counts and next action lead. Source, JSON and internal references are collapsed technical detail. |
| Backtest overview/results | `PORT_STYLE` / `PORT_UX` / `REFACTOR` | Metrics and input-readiness language are localized; immutable BYQ result and lineage remain unchanged. |
| Data Sync/Data Source status/query | `PORT_UX` / `PORT_TESTS` / `REFACTOR` | Task readiness is a bounded Product query over durable data. Legacy internal API, fake/static progress and destructive cache controls are `DROP`/`REPLACE`. |
| Paper Trading hand-off | `PORT_UX` / `REFERENCE_ONLY` | Only Stock Pool context is carried; UI explicitly says the simulation is manual and independent of Backtest. |
| Community runtime, ORM, direct API/cache/provider/DB access | `REPLACE` / `DROP` | DSH + BeyondQuant MCP + Gateway/Product API + BYQ PostgreSQL boundaries remain authoritative. |
| BaoStock / AKShare / VectorBT / PydanticAI / Hermes | `DROP` | No code, dependency, adapter or compatibility path is introduced. |

No Community file, database, cache, credential, runtime or Git history was
modified, imported or copied.
