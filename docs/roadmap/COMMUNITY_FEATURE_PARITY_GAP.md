# Community Feature Parity Gap Audit

Status: current after Phase 34. This document compares the BeyondQuant
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

1. Agent workbench depth is delivered: normalized actionable cards, bounded
   public progress, approval management, conversation starters, and the
   responsive assistant drawer are verified through real Product API.
2. Strategy workspace depth is delivered; remaining items are bounded Phase
   40 hardening/profile-field decisions (D-0009–D-0012).
3. Backtest result/wizard depth is delivered, but the strategy-source →
   `signal_snapshot` producer is blocked on a dedicated ADR (D-0002).
4. Stock Pool depth is delivered with immutable membership snapshots,
   lifecycle, index/filter semantics, weights, and historical projections.
5. Paper Trading depth is delivered with settlement, order audit, risk
   controls, persisted ledger, and validated asset-bundle transfer.
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

Current BYQ: `REDESIGNED_PASS` sessions, conversation composer, normalized
WorkflowTrace card/activity/approval/context projections, generated actionable
strategy/stock/optimization flows, local/global approval management, and the
responsive assistant drawer. Raw DSH schemas remain behind the Runtime Adapter
and Gateway boundary.

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

Current BYQ: `COMPLETE` for Phase 35: owner-scoped accounts, orders, fills,
positions, persisted ledger, immutable settlement snapshots, order detail,
versioned risk controls, frozen Stock Pool binding, and validated new-ID asset
bundle transfer are real Product API workflows with desktop/mobile evidence.

### Profile

Community: nickname, preferences, default prompt, and durable save through
auth session.

Current BYQ: `PRESENT` for the core profile form and owner-scoped save.

### Models

Community: user model credentials, provider/model profiles, and Agent bindings.

Current BYQ: `COMPLETE` for Phase 37: owner-scoped encrypted credential
lifecycle, separate model profiles, explicit Agent binding, private runtime
resolution, masked reads, and metadata-only audit.

### Assets

Community: strategy/stock-pool/backtest asset panels, import/export workspace
bundle, and asset summaries.

Current BYQ: `COMPLETE` for Phase 37: canonical digested workspace export and
validated new-owner import for strategies, Stock Pools and Paper accounts;
backtests import as honest durable research archives rather than executable
jobs.

### Agent Policy

Community: personal approval preferences, presets, rule CRUD, and approval
history.

Current BYQ: `COMPLETE` for Phase 37: platform policy, durable personal
preferences, atomic presets, effective ordered rule CRUD, rule audit, and
approval history with platform gates remaining authoritative.

### Operations and Administration

Community: database, data-source, cache, model, agent, budget, runtime, graph,
access-control, data-sync, and maintenance workbenches with role protection.

Current BYQ: `PARTIAL` safe status and admin user/approval projections; most
workbenches are placeholders or missing.

### Data Center / Data Sync

Community: data-source configuration, test connection, cache status, sync jobs,
and coverage.

Current BYQ: `REDESIGNED_PASS` for Phase 39: administrator-only encrypted
Tushare credential lifecycle and test, bounded durable sync jobs with
per-symbol outcomes, canonical PostgreSQL writes, and honest observed coverage
and quality detail are verified through Product API and Chrome MCP.

### Shared components

Community: AppStateBlock, EntityPagination, ChartWrapper, GlobalApprovalCenter,
ApprovalManagementPanel, XiaobaAssistantDrawer, AgentThinking, StockPoolDialog,
UserModelSettingsPanel, SystemAnalytics, and others.

Current BYQ: `PARTIAL` shell, chart wrapper, metric cards, loading/empty/error,
and navigation; missing the deeper Community component set.

## Next-step recommendation

Do not treat the current branch as v1.0 RC. Continue the active product-depth
sequence one worktree/branch/PR at a time, each with Chrome MCP evidence and a
Community feature checklist. Phase 34 closed the Stock Pool persisted Product
API workflow under ADR-0020. Phase 35 next deepens Paper Trading;
ADR/shared-component gates control Phases 36–40.
