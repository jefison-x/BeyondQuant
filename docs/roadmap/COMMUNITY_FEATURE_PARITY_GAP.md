# Community Feature Parity Gap Audit

Status: current after Phase 33. This document compares the BeyondQuant
frontend with the read-only Community reference and tracks the product-depth
work that remains. It exists because the original V2 matrix overstated release
parity. The current state is a working contract-first product with incomplete
parity, not a v1.0 release candidate.

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

1. Agent workbench has real sessions, WorkflowTrace, approvals and context,
   but structured cards, assistant drawer, and deeper tool visualization are
   missing.
2. Strategy workspace depth is delivered; remaining items are bounded Phase
   40 hardening/profile-field decisions (D-0009–D-0012).
3. Backtest result/wizard depth is delivered, but the strategy-source →
   `signal_snapshot` producer is blocked on a dedicated ADR (D-0002).
4. Stock Pool has create/list/catalog basics but lacks persisted member edits,
   lifecycle actions, index/filter semantics, and historical snapshots.
5. Paper Trading has accounts/orders/positions/fills/ledger but lacks order
   detail, import/export, snapshots, settlement, and explicit risk controls.
6. Models/Assets/Agent Policy remain reduced compared with Community model
   management, re-import, preset, and rule workflows.
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

Current BYQ: `PARTIAL` sessions, conversation composer, normalized
WorkflowTrace/approval/context panels; no assistant drawer or generated
strategy/stock/optimization card flows.

### Strategy

Community: list/detail split, Python editor, templates/snippets, validation,
save, delete, backtest counts, version history.

Current BYQ: `PARTIAL` list/editor split with templates/snippets, static
validation, durable draft save/delete (immutable `strategy_draft` artifacts
with soft-supersede), immutable version creation/export/approval banner,
version-history list, and per-strategy backtest counts. Community deep profile
fields (description/parameters/parameter_schema/status enable-disable) and the
non-artifact strategy CRUD model are intentionally not replicated; BYQ keeps
strategy code as auditable artifacts with validation/approval semantics.

### Backtest

Community: task table/mobile cards, search/status filters, pagination, two-item
comparison, create wizard, engine/benchmark/parameters, equity/trades/daily
positions/logs/metrics, preflight, and strategy snapshot.

Current BYQ: `PARTIAL` only because the end-to-end producer remains missing.
The result workspace, real equity/trades/positions/logs/snapshot/manifest,
create wizard, comparison, delete, and mobile flows are delivered. A newly
authored strategy cannot yet produce the immutable `signal_snapshot` selected
by the wizard (D-0002).

### Stock Pool

Community: catalog, type filters, create dialog with candidate filters,
final membership tab, custom/index/dynamic branches, historical snapshots,
weights, and mobile cards.

Current BYQ: `PARTIAL` create/list with custom/index/dynamic type, description,
initial membership/weights, type/search filters, detail, and mobile cards;
missing persisted member/weight editing, lifecycle actions, index/filter
semantics, and snapshot history.

### Paper Trading

Community: account selection, overview/positions/orders/ledger/snapshots/
strategy tracking/risk controls, and create/import/order/settlement dialogs.

Current BYQ: `PARTIAL` create account, submit order, and list accounts/orders/
positions/fills/derived ledger; missing snapshots, settlement, risk controls,
import/export, and order detail dialog.

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

Current BYQ: `PARTIAL` platform policy, durable personal approval preferences,
and approval history; missing presets and rule CRUD.

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

Do not treat the current branch as v1.0 RC. Continue the active product-depth
sequence one worktree/branch/PR at a time, each with Chrome MCP evidence and a
Community feature checklist. The next gate is the Phase 34 Stock Pool domain
decision, followed by its persisted Product API workflow. Phase 35 then
deepens Paper Trading; ADR/shared-component gates control Phases 36–40.
