# BeyondQuant Productization Gap Audit

Status: Phases 16–23 的 `PLANNED` evidence；本文不授权实现未来 phase。

## Audit baseline

- BYQ baseline：roadmap 编写时的 `origin/main`，Phase 13 complete、Phase 14 next。
- Community reference：`/home/jefison/projects/BeyondQuant-community` 的 `58dd99d`（`agent/workspace-community`），working tree clean。
- Community source/database 均按 read-only 处理。
- Frontend 检查 `frontend/src`；schema evidence 检查 `backend/alembic`、`backend/app/models` 和 data-domain docs。
- Audit 时 live Community PostgreSQL cluster 未运行。`data/postgres` 是 owner 为 `nobody:nogroup`、权限 `0700` 的 ignored directory，未读取；不从不可用 cluster 推断 row counts、checksums 或 live provenance。

## 检测到的 Community frontend stack

Community 使用 Vue 3 `3.2.13`、Vite `8.1.4`、Vue Router `4.0.3`、Pinia `2.1.7`、Element Plus `2.14.3`、ECharts `6.1.0`、Axios `1.18.1`、Playwright `1.61.0`、`openapi-typescript` `7.10.1`。它是 Vue/Vite SPA，具 lazy routes、Pinia store、local browser auth tokens、Element Plus tables/forms/dialogs、ECharts wrappers 和 Playwright smoke。

因此 BYQ 首选保留该工具家族。替换 core stack 需要 ADR；Product API/state ownership 仍必须按 BYQ 重写。

## Product gap matrix

| Capability | 当前 BYQ core | Community capability | 缺失 Product capability | Decision |
|---|---|---|---|---|
| Runtime boundary | Gateway → Runtime Adapter → pinned DSH → MCP；normalized WorkflowTrace/quant roles | Browser Agent API、sessions、stream、runtime diagnostics、approval cards | accepted seam 上的 Browser Product API/safe projections | `REFACTOR` / Phase 16–18 |
| Authentication | Product bootstrap 与 owner/actor context | Login、token session、profile、role routing | Product auth/session 支持的 browser UX | `PORT_UX`、`REPLACE` API / 16–17 |
| Application shell | Headless core | Header/sidebar/mobile nav/user/ops shell | `apps/frontend`、responsive shell、typed client | `PORT_LAYOUT`、`PORT_STYLE`、`REFACTOR` / 17 |
| Dashboard | Domain summaries/system/trace contracts | Cards、health、recent assets、quick actions | 支持 partial-failure/loading 的 aggregate dashboard | `PORT_UX`、`REPLACE` API / 17 |
| Agent research | Roles、authorization、approval、audit、DSH correlation、WorkflowTrace | Conversation、history、streaming、cards、approval center | 使用 normalized events/domain projections 的 workbench | `PORT_UX`、`PORT_COMPONENT`、`REPLACE` / 18 |
| Research entities | ResearchTask/Experiment/Artifact/lineage | Conversation/artifact cards | Task/experiment/artifact/evidence views | `PORT_UX`、`REPLACE` / 18–19 |
| Factor research | Input/lifecycle/calendar/coverage/PIT/artifact contracts | 无新 BYQ factor workspace | Definition、compute、coverage、metrics、lineage UI | `PORT_UX`、`REDESIGN` / 19 |
| Strategy | Immutable Artifact/Version/validation/approval | List/detail、editor、templates、validation | Product versioning/provenance/approval/editor | `PORT_LAYOUT`、`PORT_UX`、`REFACTOR` / 19 |
| Backtest | Native deterministic worker、A-share rules、manifests/results | Tasks、compare、progress、charts、trades、quality | BYQ contract 上的 browser lifecycle/result projection | `PORT_UX`、`PORT_COMPONENT`、`REPLACE` / 19 |
| Stock pool | Frozen-universe semantics | custom/index/dynamic catalog、snapshots、weights | BYQ pool contract/provenance/history UI | `PORT_UX`、`REFACTOR` / 21 |
| Paper trading | 无 product surface/live broker | accounts、positions、orders、ledger、risk、transfer | 独立 BYQ simulation state/Product API | `PORT_UX`、`REDESIGN` / 21 |
| User profile/models/assets | Owner context、secret boundary、durable Artifacts | Profile、model settings、asset transfer | Safe Product resources/workspaces | `PORT_UX`、`REFACTOR`/`REPLACE` / 20 |
| Agent policy/approvals | Authorization/approval/audit contracts | Policy、presets、approval history | Approval inbox/safe policy/audit UX | `PORT_UX`、`REPLACE` / 18–20 |
| Data settings/Operations | Tushare contract、health/trace/audit | Sources、cache、sync、DB/runtime/access | Protected、secret-safe projections | `PORT_UX`、`REDESIGN` / 20–22 |
| Deployment | Independently deployable topology | Compose、volumes、migration、backup | BYQ runbook/backup/verification | `REFERENCE_ONLY` semantics、`REDESIGN` / 22 |
| Frontend testing | Contract tests，无 SPA | Playwright smoke | Product API contracts、responsive smoke、golden journey | `PORT_TESTS`、`REFACTOR` / 17/23 |

## Reference decisions

在 [`COMMUNITY_FRONTEND_MIGRATION.md`](../migration/COMMUNITY_FRONTEND_MIGRATION.md) 映射后，port visual language、layout hierarchy、navigation labels、table/card/dialog patterns、chart interaction、loading/error/empty states、responsive patterns 和 user workflows。

所有 API binding、auth/session integration、state owner、streaming contract、domain state machine、migration target、operations/deployment boundary 必须为 BYQ redesign：

```text
Browser → BYQ Product API / Gateway → BYQ domain or Runtime Adapter
       → MCP / Backend / DSH behind their accepted boundaries
```

Drop Community PydanticAI/Hermes runtime ownership、direct Agent-to-database、raw Agent/DSH coupling、BaoStock、AKShare、VectorBT；不得作为 dependencies、fallbacks、API choices 或 compatibility layers 返回。Strategy source 是 BYQ domain artifact，绝非 application-source write access。

## Data audit summary

Community schema-source evidence 包含 `market_data_daily`、`market_adjustment_factors`、`market_trading_status`、`market_corporate_actions`、`stock_universe`、`index_master`、`index_constituent_weights`、`security_name_history` 及 sync/research tables。Live cluster 不可用，所以“discovered”仅表示 schema-source evidence，直到 Phase 16 read-only database audit。

Physical PostgreSQL directory 永不作为 migration target。Future logical migration 只可接收具有已证明 `tushare` provenance 或 provider-independent canonical semantics 的 rows，并先验证 schema/unit/coverage/quality。见 [`COMMUNITY_MARKET_DATA_MIGRATION.md`](../migration/COMMUNITY_MARKET_DATA_MIGRATION.md)。

## Audit 结论

BeyondQuant 已具备产品所需 core quant/agent architecture，但当时缺 browser Product API/UI、durable data target/validated cache migration、user/settings、paper-trading boundary、operations/deployment productization 和 release-level E2E journey。正确路径是 Community UX parity 加 BYQ/DSH architecture redesign，而不是复制 repository、runtime、database、provider 或 engine。
