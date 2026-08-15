# BeyondQuant Productization Gap Audit

Status: `PLANNED` evidence for Phases 16–23. This audit does not authorize
implementation of any future phase.

## Audit baseline

- BYQ baseline: `origin/main` at the time of this roadmap work, Phase 13
  complete, Phase 14 next.
- Community reference: `/home/jefison/projects/BeyondQuant-community` at
  `58dd99d` (`agent/workspace-community`); its working tree was clean.
- Community source and database were treated as read-only.
- Frontend source was inspected under `frontend/src`; schema evidence was
  inspected under `backend/alembic`, `backend/app/models`, and the data-domain
  documentation.
- The live Community PostgreSQL cluster was not running during this audit.
  `data/postgres` exists as an ignored directory with restrictive ownership
  (`0700 nobody:nogroup`) and was not read. No row counts, checksums, or live
  data provenance are inferred from the unavailable cluster.

## Detected Community frontend stack

Community uses Vue 3 (`3.2.13`), Vite (`8.1.4`), Vue Router (`4.0.3`), Pinia
(`2.1.7`), Element Plus (`2.14.3`), ECharts (`6.1.0`), Axios (`1.18.1`),
Playwright (`1.61.0`), and `openapi-typescript` (`7.10.1`). The frontend is a
Vue/Vite SPA with lazy routes, a Pinia app store, local browser auth tokens,
Element Plus tables/forms/dialogs, ECharts wrappers, and Playwright smoke
coverage.

The preferred BYQ direction is therefore to retain this family of tools. A
core stack replacement requires an ADR; the Product API and state ownership
must still be rewritten for BYQ.

## Product gap matrix

| Capability | Current BYQ core capability | Community product capability observed | Missing Product capability | Decision |
|---|---|---|---|---|
| Runtime boundary | Gateway → Runtime Adapter → pinned DSH → MCP; BYQ normalized WorkflowTrace and Phase 13 quant roles | Browser-facing Agent API, sessions, stream, graph/runtime diagnostics, approval cards | Browser Product API and safe projections over the accepted runtime seam | `REFACTOR` / Phase 16–18 |
| Authentication and user identity | Phase 7 authenticated product bootstrap and owner/actor context contracts | Login form, access/refresh token session, profile, role-based operations routing | Multi-page browser auth/session UX backed by Product auth/session contract | `PORT_UX`, `REPLACE` API / Phase 16–17 |
| Application shell | Headless core; no formal browser application | Header, collapsible desktop sidebar, mobile bottom navigation, user menu, ops shell | `apps/frontend`, responsive shell and typed Product API client | `PORT_LAYOUT`, `PORT_STYLE`, `REFACTOR` / Phase 17 |
| Dashboard | BYQ domain summaries and system/trace contracts exist without a browser dashboard | Home cards for strategies, backtests, stock pools, cache coverage, system health, recent assets and quick actions | Aggregated browser dashboard with partial-failure and loading states | `PORT_UX`, `REPLACE` API / Phase 17 |
| Agent research | Phase 13 roles, authorization, approval, audit, DSH correlation, WorkflowTrace | `AgentView.vue` conversation, session history, streaming, thinking steps, candidate/strategy/optimization cards, approval center | Full research workbench consuming normalized BYQ events and domain projections | `PORT_UX`, `PORT_COMPONENT`, `REPLACE` event/API / Phase 18 |
| Research entities | BYQ-owned ResearchTask, Experiment, Artifact, provenance, lineage, idempotency | Research workflow is presented through Agent conversation and artifact cards | Product views for task/experiment/artifact navigation and evidence lineage | `PORT_UX`, `REPLACE` state/API / Phase 18–19 |
| Factor research | BYQ factor input, lifecycle, calendar, coverage, point-in-time and artifact contracts | Research UI references data and backtest capabilities but has no new BYQ factor workspace | Factor definition, compute, coverage, metrics, evaluation and lineage UI | `PORT_UX`, `REDESIGN` / Phase 19 |
| Strategy | BYQ immutable Strategy Artifact/Version, validation and approval boundary | Split strategy list/detail, Python editor, templates/snippets, built-in read-only cards, static/execution validation calls | Product API versioning, provenance, approval and safe domain-artifact editor | `PORT_LAYOUT`, `PORT_UX`, `REFACTOR` API/domain binding / Phase 19 |
| Backtest | BYQ native deterministic worker, A-share rules, input/result manifests, immutable result objects | Task table/cards, filters, compare dialog, progress/preflight, ECharts equity curve, metrics, trades, positions, logs and data quality | Browser job lifecycle and complete result projection over BYQ contracts | `PORT_UX`, `PORT_COMPONENT`, `REPLACE` API/engine binding / Phase 19 |
| Stock pool | BYQ frozen-universe/backtest authorization semantics; no complete product pool surface | Custom/index/dynamic pool catalog, candidate filters, final membership, snapshots, weights, pagination and mobile cards | BYQ-owned stock-pool product contract, provenance and version history UI | `PORT_UX`, `REFACTOR` semantics/API / Phase 21 |
| Paper trading | Backtest only; no live broker contract and no paper-trading product surface | Paper accounts, positions, orders, fills, ledger, snapshots, strategy tracking, risk controls, import/export and manual settlement | Separate BYQ simulation state machine and Product API; no broker integration | `PORT_UX`, `REDESIGN` domain/API / Phase 21 |
| User profile | Authenticated principal and owner context; no browser profile page | Nickname, research preferences, default prompt form | Product profile/preferences resource and safe persistence | `PORT_UX`, `REPLACE` API / Phase 20 |
| User model settings | Secret boundary exists in backend/runtime contracts; no browser settings | Personal provider credential/profile forms, masked key status, agent bindings, platform permission view | Secret-safe model settings with write-only credentials and capabilities only | `PORT_UX`, `REFACTOR` / Phase 20 |
| User assets | BYQ Artifacts/results are durable domain data; no asset workspace | Strategies, stock pools, backtests, export/import asset bundle UX | Owner-scoped Product asset index, artifact/object references and import policy | `PORT_UX`, `REFACTOR` / Phase 20 |
| Agent policy and approvals | BYQ owner/actor authorization, approval and audit contracts | Personal policy settings, presets, approval history, global approval center and management panel | Product approval inbox, safe policy UX and auditable decisions | `PORT_UX`, `REPLACE` API / Phase 18–20 |
| Data settings | Tushare adapter contract and provider secret ownership | Operations data-source configuration, capability status, cache and sync controls | Normal-user provider status/capability page plus protected operations controls | `PORT_UX`, `REDESIGN` / Phase 20–22 |
| Operations | BYQ health/trace/audit foundations and target topology; no product operations UI | Database, source, cache, model, agent, budget, runtime, graph, access/audit workbenches | Secret-safe read-mostly Operations projection for BYQ topology | `PORT_UX`, `REDESIGN` / Phase 22 |
| Deployment | Architecture defines independently deployable target topology | Compose, volumes, migrations, backup/restore and maintenance workflows in Community | BYQ production deployment/runbook, backup/restore and migration verification | `REFERENCE_ONLY` semantics, `REDESIGN` topology / Phase 22 |
| Observability | BYQ WorkflowTrace, audit, run correlation and worker result contracts | Runtime/graph diagnostics, statuses, errors, usage and checkpoints | Product-safe trace/health/audit projections with no raw DSH payload | `PORT_UX`, `REFACTOR` / Phase 18 and 22 |
| Frontend testing | Backend/MCP/runtime/architecture contract tests; no Product SPA | Playwright smoke tests and component/browser interaction evidence | Product API contract tests, responsive smoke and golden journey | `PORT_TESTS`, `REFACTOR` / Phase 17 and 23 |

## Reference decisions

### Port

Port visual language, layout hierarchy, navigation labels, table/card/dialog
patterns, chart interaction, loading/error/empty states, responsive patterns,
and user workflows after they are mapped in
[`COMMUNITY_FRONTEND_MIGRATION.md`](../migration/COMMUNITY_FRONTEND_MIGRATION.md).

### Redesign

Redesign every API binding, auth/session integration, state owner, streaming
contract, domain state machine, migration target, and operations/deployment
boundary for BYQ. Product flow is always:

```text
Browser → BYQ Product API / Gateway → BYQ domain or Runtime Adapter
       → MCP / Backend / DSH behind their accepted boundaries
```

### Drop or replace

Drop Community PydanticAI/Hermes runtime ownership, direct Agent-to-database
access, raw Agent/DSH event coupling, BaoStock, AKShare, and VectorBT. These
may be mentioned as migration evidence but must not return as dependencies,
fallbacks, API choices, or compatibility layers. Strategy source remains a
BYQ domain artifact, never application-source write access.

## Data audit summary

Community source migrations/models confirm the following table families exist
in the legacy schema design: `market_data_daily`,
`market_adjustment_factors`, `market_trading_status`,
`market_corporate_actions`, `stock_universe`, `index_master`,
`index_constituent_weights`, and `security_name_history`, plus related sync
state and research-enhancement tables. The live cluster was unavailable, so
“discovered” means schema-source evidence only until Phase 16 performs a
read-only database audit.

The physical PostgreSQL directory is never a migration target. A future
logical migration may accept only rows with proven `tushare` provenance or
provider-independent canonical semantics, after schema/unit/coverage/data
quality validation. See
[`COMMUNITY_MARKET_DATA_MIGRATION.md`](../migration/COMMUNITY_MARKET_DATA_MIGRATION.md).

## Audit conclusion

BeyondQuant has the core quant and agent architecture required for a product,
but lacks the browser Product API/UI, durable data target and validated cache
migration, user/settings surfaces, paper-trading product boundary,
operations/deployment productization, and release-level E2E journey. The
correct path is Community UX parity plus BYQ/DSH architectural redesign; it is
not a repository, runtime, database, provider, or engine copy.
