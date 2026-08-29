# Post-Phase 74 model navigation and strategy labels — Community classification

Inspected read-only on 2026-08-30:

- `frontend/src/views/StrategyView.vue`
- `frontend/src/views/UserModelsView.vue`
- `frontend/src/components/settings/UserModelSettingsPanel.vue`
- Community router and application navigation components

| Community surface | Classification | BYQ maintenance decision |
|---|---|---|
| Strategy editor uses visible top-positioned labels for every field | `PORT_UX` | Add persistent visible labels and accessible names to BYQ's strategy editor; retain BYQ draft/version/approval contracts. |
| Personal model credentials and Agent bindings live in account settings | `PORT_LAYOUT`, `PORT_UX` | Keep only LLM credentials, profiles, and Agent binding under `模型配置`. |
| Community personal-model navigation | `REFERENCE_ONLY` | It configures LLM providers, not quant ML research, so it does not justify placing the LightGBM workbench in settings. |
| Quant ML research workbench | `REPLACE` | Community has no equivalent audited training/product flow; expose BYQ's existing Product API workbench as a primary business route. |
| Community strategy API/runtime | `REFERENCE_ONLY` | Do not copy its API, runtime, storage, or strategy execution architecture. |

Acceptance checklist:

- primary order is 股票池管理 → 策略管理 → 模型研究 → 回测管理 → 模拟操盘;
- desktop and mobile navigation reach `/model-research`;
- `/user/models` contains personal LLM configuration only;
- every strategy editor input has a persistent visible title and accessible name;
- no Product API, authorization, ML lineage, strategy lifecycle, or runtime boundary changes.
