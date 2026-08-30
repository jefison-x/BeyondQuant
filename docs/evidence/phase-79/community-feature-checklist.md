# Phase 79 Community feature checklist

The BeyondQuant-Community repository was inspected read-only before Phase 79
implementation. No Community source, database, cache, credential, runtime or
Git history was changed or copied.

| Community evidence | Classification | Phase 79 result |
|---|---|---|
| User intent to predict and then validate a model by Backtest | `PORT_UX` / `REFACTOR` | Expose prediction create/status followed by a derived `backtest-task.v1` identity. |
| Model `predict` embedded in arbitrary strategy/Backtest source | `DROP` / `REPLACE` | Trusted ML Worker creates immutable prediction and signal artifacts before native Backtest execution. |
| Direct model/runtime objects and feature rows | `REFERENCE_ONLY` / `DROP` | MCP and Product projections return bounded metadata only. |
| Legacy Agent/internal API execution | `REFERENCE_ONLY` / `REPLACE` | Least-privilege ML role uses BYQ MCP with owner/workspace trace and per-action approval. |
| VectorBT, BaoStock and AKShare paths | `DROP` | No dependency, adapter, fallback or compatibility layer was added. |

The new flow reuses existing BYQ domain states and Product UI language; it does
not copy Community architecture or create a parallel Agent/workflow runtime.
