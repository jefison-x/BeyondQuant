# Phase 74 Community frontend classification

Inspected read-only on 2026-08-30: `UserModelsView.vue`, `UserModelSettingsPanel.vue`,
`userModels.js`, and ML-related strategy/backtest text in `AgentView.vue`.

| Community surface | Classification | Phase 74 decision |
|---|---|---|
| User Models page framing and settings language | `PORT_LAYOUT`, `PORT_UX` | Preserve the Models destination and use a clear top-level tab. |
| LLM credential/profile/browser API | `REPLACE` | Retain BYQ's productized write-only credential flow; do not reuse Community API or auth code. |
| “ML v2” fitted inside backtest/rebalance | `REFERENCE_ONLY`, `REPLACE` | Treat as leakage/reproducibility risk evidence; use isolated durable training and out-of-sample prediction. |
| Quant ML workbench | `REPLACE` | Community has no equivalent product surface; implement through Gateway/Product API and BYQ artifacts. |
| BaoStock/AKShare/VectorBT paths | `DROP` | Do not introduce dependencies, adapters, fallbacks, or compatibility code. |

Implementation review checklist: real task and frozen-pool selectors; explicit approval;
durable training status; safe model metadata; ranked prediction; frozen signal and backtest
actions; loading/error/empty states; responsive layout; no Backend/MCP/DSH/provider browser calls.
