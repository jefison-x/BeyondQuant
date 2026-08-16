# Community Feature Parity Gap Audit

This document re-compares the current BeyondQuant frontend with the read-only
Community reference after the Phase 7/8 release work. It exists because the
previous V2 matrix marked the surface as release-parity complete while many
Community product-depth features are still missing. The current state is an
honest contract-first skeleton, not a final Community feature parity release.

## Method

- Community source: `/home/jefison/projects/BeyondQuant-community/frontend`
- Current source: `apps/frontend`
- Compared page-by-page: routes, components, dialogs, tabs, tables, filters,
  editors, and Product API capabilities.
- Read-only Community source was inspected; no Community file was modified.

## Legend

- `PRESENT`: equivalent BYQ/DSH-native capability is implemented through the
  Product API.
- `PARTIAL`: a reduced projection or skeleton exists, but the Community
  product-depth workflow is missing.
- `MISSING`: no equivalent capability is implemented.
- `DROP`: permanently excluded by accepted architecture decisions.

## Executive summary

The current BYQ frontend restores the main information architecture and basic
list/status projections, but it does not yet restore most Community product
workflows. The largest gaps are:

1. Agent workbench is a trace viewer, not the Community conversation/tool/
   approval/artifact orchestration surface.
2. Strategy is list/validate/export only; the full draft editor, templates,
   version history, and approval flow are not restored.
3. Backtest is list/metric/empty-chart only; create wizard, comparison,
   trades, daily positions/returns, logs, and strategy snapshot are missing.
4. Stock Pool is create/list only; catalog types, member editing, index
   constituents, filters, weights, and historical snapshots are missing.
5. Paper Trading is create/order/positions/fills only; order dialog,
   import/export, ledger, snapshots, settlement, and risk controls are missing.
6. Profile/Models/Assets/Agent Policy are reduced settings status pages, not
   the Community configuration and import/export workflows.
7. Operations pages are mostly status/admin-user views; database, source,
   cache, model, agent, budget, runtime, graph, access-control, data-sync, and
   maintenance workbenches are missing or placeholders.

## Per-surface gap detail

### Home / Dashboard

Community: strategy/backtest/stock-pool/cache/system summary cards, recent
results, resource bars, quick actions, and partial-failure messaging.

Current BYQ: `PRESENT` for resource status and recent research/backtest lists;
`PARTIAL` for Community card depth and quick-action parity.

### Agent Research Workbench

Community: session history, streaming messages, thinking steps, strategy/
stock-candidate/optimization cards, approval cards, backtest context, assistant
drawer, and multi-step tool visualization.

Current BYQ: `PARTIAL` normalized WorkflowTrace/approval/context panels; no
Community conversation depth, assistant drawer, or generated strategy/stock
card flows.

### Strategy

Community: list/detail split, Python editor, templates/snippets, validation,
save, delete, backtest counts, version history.

Current BYQ: `PARTIAL` list + textarea validation + export; missing full editor,
templates/snippets, durable draft save/delete, and version-history UX.

### Backtest

Community: task table/mobile cards, search/status filters, pagination, two-item
comparison, create wizard, engine/benchmark/parameters, equity/trades/daily
positions/logs/metrics, preflight, and strategy snapshot.

Current BYQ: `PARTIAL` list/search/status + empty chart + raw projection; missing
create wizard, comparison dialog, trades/positions/logs/snapshot, and real
equity data.

### Stock Pool

Community: catalog, type filters, create dialog with candidate filters,
final membership tab, custom/index/dynamic branches, historical snapshots,
weights, and mobile cards.

Current BYQ: `PARTIAL` create/list only; missing catalog types, member editing,
index constituents, filters, weights, and snapshot history.

### Paper Trading

Community: account selection, overview/positions/orders/ledger/snapshots/
strategy tracking/risk controls, and create/import/order/settlement dialogs.

Current BYQ: `PARTIAL` create account, submit order, list accounts/orders/
positions/fills; missing ledger, snapshots, settlement, risk controls, import/
export, and order detail dialog.

### Profile

Community: nickname, preferences, default prompt, and durable save through
auth session.

Current BYQ: `PRESENT` for the core profile form and owner-scoped save.

### Models

Community: user model credentials, provider/model profiles, and Agent bindings.

Current BYQ: `PARTIAL` masked provider/configured status only; missing
credential/profile/binding management.

### Assets

Community: strategy/stock-pool/backtest asset panels, import/export workspace
bundle, and asset summaries.

Current BYQ: `PARTIAL` asset index and export/import config assets; strategies
and backtests are export-only and not re-importable.

### Agent Policy

Community: personal approval preferences, presets, rule CRUD, and approval
history.

Current BYQ: `PARTIAL` platform policy + approval history; missing personal
preferences, presets, and rule CRUD.

### Operations and Administration

Community: database, data-source, cache, model, agent, budget, runtime, graph,
access-control, data-sync, and maintenance workbenches with role protection.

Current BYQ: `PARTIAL` safe status and admin user/approval projections; most
workbenches are placeholders or missing.

### Data Center / Data Sync

Community: data-source configuration, test connection, cache status, sync jobs,
and coverage.

Current BYQ: `PARTIAL` provider/migration/quality status; missing source
configuration, sync job, and coverage detail.

### Shared components

Community: AppStateBlock, EntityPagination, ChartWrapper, GlobalApprovalCenter,
ApprovalManagementPanel, XiaobaAssistantDrawer, AgentThinking, StockPoolDialog,
UserModelSettingsPanel, SystemAnalytics, and others.

Current BYQ: `PARTIAL` shell, chart wrapper, metric cards, loading/empty/error,
and navigation; missing the deeper Community component set.

## Next-step recommendation

Do not treat the current branch as v1.0 RC. Re-open the Community parity work
as a sequence of product-depth phases, one worktree/branch/Draft PR at a time,
each with Chrome MCP evidence and Community feature-checklist evidence. The
first priority should be the high-value quant workflows: Backtest, Strategy,
Stock Pool, Paper Trading, then Agent workbench, then My Space/Operations.
