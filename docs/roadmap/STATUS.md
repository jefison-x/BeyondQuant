# BeyondQuant Status

This file is the phase source of truth. It is intentionally short so a new
Codex session does not infer project state from commit history.

- Current completed phase: **Phase 47** — Interaction, responsive and
  accessibility closure with standardized semantic states, unsaved-edit
  protection, stable route focus, responsive content, accessible theme-aware
  charts and a complete light/dark accent contrast matrix.
- Next phase: **Phase 48 — Product coherence golden journey** as defined in
  `FRONTEND_EXPERIENCE_PLAN.md`. The v1.0 release-candidate review is postponed
  until the Phases 42-48 experience program is complete. The post-Phase 40 DSH
  Upgrade Lane remains separately scheduled.
- Accepted runtime ADR: **ADR-0003**
- Accepted Phase 7 authentication ADR: **ADR-0004**
- Accepted Phase 8 data-provider ADR: **ADR-0005**
- Accepted Phase 9 research-entities ADR: **ADR-0006**
- Accepted Phase 11 strategy-artifact ADR: **ADR-0007**
- Accepted Phase 12 backtest-worker ADR: **ADR-0008**
- Accepted Phase 13 quant-research-agent ADR: **ADR-0009**
- Accepted Phase 14 quant-learning-loop ADR: **ADR-0010**
- Accepted Phase 15 engineering-plane ADR: **ADR-0011**
- Accepted Phase 16 product-api ADR: **ADR-0012**
- Accepted Phase 16 durable-market-data-storage ADR: **ADR-0013**
- Accepted Phase 24 user-auth ADR: **ADR-0014**
- Accepted pre-release auto-merge ADR: **ADR-0015**
- Accepted PostgreSQL single-domain-store ADR: **ADR-0016**
- Accepted signal-snapshot ADR: **ADR-0017**
- Accepted WorkflowTrace structured-card ADR: **ADR-0018**
- Accepted encrypted credential-store ADR: **ADR-0019**
- Accepted Stock Pool snapshot/lifecycle ADR: **ADR-0020**
- Accepted Paper Trading account/lifecycle ADR: **ADR-0021**
- Accepted Phase 38 component-ownership ADR: **ADR-0022**
- Accepted Phase 40 isolated signal-producer ADR: **ADR-0023**
- Accepted conversation-first Product experience ADR: **ADR-0024**
- Open architecture decisions: **none from the Phase 48 entry gate**.

  Accepted decisions currently in force:
  [ADR-0003](../architecture/adr/ADR-0003-gateway-dsh-runtime-integration.md)
  is Accepted.
  [ADR-0004](../architecture/adr/ADR-0004-phase7-product-authentication.md)
  is Accepted.
  [ADR-0005](../architecture/adr/ADR-0005-phase8-data-provider.md) is Accepted.
  [ADR-0006](../architecture/adr/ADR-0006-phase9-research-entities.md) is Accepted.
  [ADR-0007](../architecture/adr/ADR-0007-phase11-strategy-artifact.md) is Accepted.
  [ADR-0008](../architecture/adr/ADR-0008-phase12-backtest-worker.md) is Accepted.
  [ADR-0009](../architecture/adr/ADR-0009-phase13-quant-research-agents.md) is Accepted.
  [ADR-0010](../architecture/adr/ADR-0010-phase14-quant-learning-loop.md) is Accepted.
  [ADR-0011](../architecture/adr/ADR-0011-phase15-engineering-plane.md) is Accepted.
  [ADR-0012](../architecture/adr/ADR-0012-phase16-product-api-bff.md) is Accepted.
  [ADR-0013](../architecture/adr/ADR-0013-phase16-durable-market-data-storage.md) is Accepted.
  [ADR-0014](../architecture/adr/ADR-0014-phase24-durable-user-auth.md) is
  Accepted.
  [ADR-0015](../architecture/adr/ADR-0015-phase-release-automerge.md) is
  Accepted until the BeyondQuant Next v1.0 release boundary.
  [ADR-0016](../architecture/adr/ADR-0016-postgresql-single-domain-store.md)
  is Accepted.
  [ADR-0017](../architecture/adr/ADR-0017-signal-snapshot-artifact.md)
  is Accepted.
  [ADR-0018](../architecture/adr/ADR-0018-workflow-trace-card-contract.md)
  is Accepted.
  [ADR-0019](../architecture/adr/ADR-0019-encrypted-credential-store.md)
  is Accepted.
  [ADR-0020](../architecture/adr/ADR-0020-stock-pool-snapshot-lifecycle.md)
  is Accepted.
  [ADR-0021](../architecture/adr/ADR-0021-paper-trading-account-lifecycle.md)
  is Accepted.
  [ADR-0022](../architecture/adr/ADR-0022-phase38-component-ownership.md)
  is Accepted.
  [ADR-0023](../architecture/adr/ADR-0023-isolated-signal-producer.md)
  is Accepted.
  [ADR-0024](../architecture/adr/ADR-0024-conversation-first-product-experience.md)
  is Accepted.
- Phase 23 acceptance evidence established a Product Skeleton browser and
  parity baseline. Its mocked Playwright navigation smoke is not evidence of
  a real Product API golden journey and is not a v1.0 RC gate.
- Phase 23 produced a Product Skeleton release-parity baseline. It did not
  establish final Community feature parity. Phases 24–31 established the
  durable product/storage baseline; remaining product-depth work is tracked
  in Phases 32–40.
- Phase 30 produced the initial V2 parity matrix and browser surfaces; its
  original RC conclusion was superseded by the gap audit and Phases 32–40.
  Phase 40 has now supplied the real-Product-API, no-mock, multi-user golden
  journey required to reopen RC review.
- Phase 31 (ADR-0016) completed: all eight domain stores run on PostgreSQL via
  `services/backend/app/db.py` (`BYQ_DATABASE_URL`); SQLite runtime code paths
  and `BYQ_DOMAIN_DB_PATH` are removed; the logical SQLite -> PostgreSQL
  migration was executed and verified idempotently against the dev volume; the
  `pg_dump`/`pg_restore` backup/restore drill passed; the ADR-0013 durable
  market-data target (`MarketDataStore`) and migration pipeline are ready.
  Formal ADR-0013 bulk Community market-data import still requires a live
  read-only Community audit snapshot (ADR-0013 decision 6); Community
  PostgreSQL remains read-only evidence and is untouched.
- Phase 32 (Community backtest workspace depth) completed: the create wizard
  submits a backtest referencing an immutable `signal_snapshot` artifact
  (ADR-0017 Accepted, PR #81) with version/owner/task matching (PR #82); the
  result workspace exposes all 8 detail tabs real (权益曲线/交易明细/拦截明细/
  公司行动/每日持仓&收益/日志输出/策略快照/输入清单); delete/compare/mobile
  work; Chrome DevTools MCP evidence recorded for both result depth and the
  wizard. D-0001 (create wizard) is CLOSED in the Deferred Items Registry.
  At Phase 32 closeout, the end-to-end strategy-to-backtest journey and the
  optional result-object sweep were transferred as D-0002/D-0003. Phase 40
  has now closed D-0002 under ADR-0023 and dropped D-0003 after its measured
  orphan trigger proved false.
- Phase 33 (Strategy workspace depth) completed: durable `strategy_draft`
  save (tolerant of intermediate edits) and owner-scoped soft-supersede
  delete, per-strategy version history, and real backtest counts are exposed
  through Backend/MCP/Product API and the strategy workspace UI (PR #85);
  saved drafts stay editable, read-only version detail, and Chrome DevTools
  MCP evidence are recorded. Follow-up hardening/scope items are registered
  as D-0009 (superseded-draft visibility), D-0010 (version-history projection
  bound), D-0011 (StrategyView component tests), and D-0012 (Community deep
  profile fields) in the Deferred Items Registry; all four are assigned to
  Phase 40 rather than the completed Phase 33; Phase 40 has now closed all
  four items together with D-0002 (signal producer).
- Phase 34 (Stock Pool depth) completed: owner-scoped catalog/detail and five
  persisted projections now use immutable membership snapshots with stable
  version/fingerprint identity; weights are validated; custom edits create new
  snapshots; index pools use trusted Tushare provenance and no-look-ahead
  effective-date lookup; lifecycle/tombstone behavior and frozen Paper
  Trading/research/backtest references are auditable. Backend, Product API,
  MCP `byq_pool_*`, frontend, desktop/mobile Chrome MCP evidence, and the
  Community-derived checklist are complete.
- Phase 35 (Paper Trading depth) completed: owner-scoped accounts now provide
  persisted ledger and settlement snapshots, manual immutable settlement,
  exact T+1 quantity partitions, order audit detail, versioned risk controls,
  frozen Stock Pool binding, and canonical digested asset-bundle transfer with
  new IDs and trusted-owner rebinding. Six real Product UI tabs, bounded
  read-only MCP projections, real Product API E2E, and desktop/mobile Chrome
  MCP evidence are complete. No live broker or Community runtime/storage path
  was introduced.
- Phase 36 (Agent workbench depth) completed: ADR-0018's closed WorkflowTrace
  card/activity vocabulary is enforced at the MCP, Runtime Adapter, Gateway,
  Product API, and frontend boundaries. Strategy-draft, stock-candidate,
  optimization, backtest-context, and approval cards use normalized public
  projections; answer text and curated activities exclude raw DSH schemas,
  hidden reasoning, tool arguments, and secrets. The Agent workbench now has
  actionable cards, bounded public execution progress, local/global approval
  panels, conversation starters, and the Xiaoba assistant drawer. Real Product
  API desktop/mobile Chrome MCP evidence and the Community-derived checklist
  are recorded under `docs/evidence/phase-36/`. D-0005 is CLOSED.
- Phase 37 (My Space depth) completed: owner-scoped write-only model
  credentials use AES-256-GCM envelope encryption, audited lifecycle and
  private Runtime Adapter resolution; model profiles and Product Agent
  binding are durable without exposing secrets. Workspace asset v2
  export/import validates manifest/item digests, produces new current-owner
  identities, revalidates strategies, preserves backtests as honest archives,
  and reuses canonical Stock Pool/Paper account import paths. Agent Policy now
  has atomic presets, effective ordered rule CRUD and audit while platform
  approval gates remain authoritative. Real Product API Chrome MCP evidence
  and the Community checklist are under `docs/evidence/phase-37/`. D-0006 is
  CLOSED.
- Phase 38 (Operations workbenches) completed: nine admin routes now use a
  real, bounded `operations.v1` Product API projection for PostgreSQL/cache,
  source/model readiness, Agent runs, normalized DSH runtime/usage, Graph,
  durable access groups and append-only audit. Monitoring-threshold writes are
  admin-only, versioned, idempotent and audited; secrets, raw DSH events,
  Redis controls, arbitrary SQL and direct runtime control do not cross the
  browser boundary. Desktop/mobile Chrome MCP evidence and the Community
  checklist are under `docs/evidence/phase-38/`. D-0007 is CLOSED.
- Phase 39 (Data Center / Data Sync depth) completed: Tushare-only write-only
  credential lifecycle and bounded connection testing use ADR-0019; durable
  asynchronous jobs persist per-symbol outcomes and import canonical daily
  bars into PostgreSQL with deterministic keep-existing semantics; coverage
  reports observed bounds and validation issues without claiming calendar
  completeness. Browser traffic stays on Product API, and desktop/mobile
  Chrome MCP evidence plus the Community checklist are under
  `docs/evidence/phase-39/`. D-0008 is CLOSED.
- Phase 40 (Shared components and final parity closure) completed: ADR-0023's
  trusted coordinator and credential-free bounded Pandas sandbox turn an
  approved immutable StrategyVersion plus frozen canonical bars/Stock Pool
  snapshot into a normalized content-addressed `signal_snapshot`; Product UI
  can create research tasks and complete strategy→approval→signal→backtest.
  Direct paginated strategy projections, archive visibility, deep immutable
  fields, owner approval, shared state/pagination components and accessibility
  fixes close D-0002 and D-0009–D-0012. D-0003 is explicitly DROPPED because
  the measured orphan trigger was false. A fresh Compose two-user golden flow,
  desktop/mobile Chrome MCP evidence, 100 Lighthouse accessibility score and
  the Community checklist are under `docs/evidence/phase-40/`.
- Phase 41 accepted the conversation-first Product direction after the
  maintainer postponed v1.0 RC review. It records the durable BYQ conversation
  catalog versus private DSH Session boundary, single-level navigation,
  user/settings consolidation, semantic global theme contract, Community
  read-only classification, Phases 42-48 delivery sequence, and post-merge
  `0.0.0.0:80` preview requirement. No Product runtime changed in Phase 41.
- Phase 42 implemented ADR-0024's conversation-first shell. `/` now resolves
  to Xiaoba; desktop uses one collapsible, single-level primary sidebar and a
  compact route toolbar; mobile uses a modal navigation drawer with keyboard
  focus; recent live Product sessions remain honestly identifier-labelled
  until Phase 43 adds the durable catalog. Profile, Assets, Paper Trading,
  personal Models/Agent Policy, research/approval, Data Center, status, and
  admin-only Operations remain reachable through the bottom user menu or
  preserved deep links. Chrome DevTools MCP verified desktop/mobile layout,
  same-origin Product API traffic, and a clean console under
  `docs/evidence/phase-42/`.
- Phase 43 implemented ADR-0024's durable conversation boundary. PostgreSQL
  now owns owner-scoped Product conversation metadata and user turns;
  Gateway composes restart-safe replay with only normalized WorkflowTrace and
  keeps the correlated DSH runtime session out of browser responses. First
  turns produce deterministic bounded titles; search, pagination, rename,
  pin, archive and restore are durable. The Agent view is a centered Xiaoba
  timeline with inline workflow cards and bounded activity/approval drawers;
  generation guards and abortable streams prevent cross-conversation replay.
  Compose restart, owner-isolation tests and desktop/mobile Chrome DevTools MCP
  evidence are under `docs/evidence/phase-43/`.
- Phase 44 consolidated Profile, Appearance, Assets, Paper Trading, Models,
  personal Agent Policy and research/approval entry points into one responsive
  route-backed user center. PostgreSQL owns versioned per-user appearance
  preferences behind the Product API; the browser cache contains only a
  validated non-authoritative paint hint. Global semantic tokens and chart
  themes now follow system/light/dark plus the closed accent palette. Compose
  restart persistence, exact-owner isolation, desktop/mobile Chrome review and
  Lighthouse accessibility evidence are under `docs/evidence/phase-44/`.
- Phase 45 consolidated System Overview, Data, Sources, Cache, Database,
  platform Models, Agents, Budget, normalized Runtime and Workflow
  diagnostics, Access and Audit into one route-backed administrator dialog.
  Desktop uses grouped two-column navigation; mobile uses a full-screen,
  keyboard-operable section selector. Legacy administrator deep links remain
  explicit redirects, closing restores a validated local source route, and
  non-admin users cannot see or directly enter the surface. Browser requests
  remain same-origin Gateway/Product API only; ADR-0022 RBAC, append-only audit
  and destructive-action limits are unchanged. Desktop/mobile Chrome review
  and Lighthouse Accessibility 100 evidence are under
  `docs/evidence/phase-45/`.
- Phase 46 unified Stock Pool, Strategy and Backtest around one responsive
  catalog/detail hierarchy while preserving the Phase 34/40 domain surfaces:
  immutable pool snapshots and references, draft/version/approval/signal
  lineage, and all eight Backtest result tabs plus comparison and creation.
  Normalized Workflow cards now map through a closed frontend route table;
  exact pool/artifact/job identifiers are rehydrated through Product APIs and
  carry the originating durable conversation for a verified return journey.
  Desktop/mobile Chrome review used real persisted Product data, found and
  removed duplicate mobile tables, observed only same-origin Gateway/Product
  requests, and finished with a clean console. Evidence is under
  `docs/evidence/phase-46/`.
- Phase 47 standardized semantic loading/empty/retry states, responsive
  pagination, localized display labels, dirty/busy/saved form behavior and
  unsaved-change protection across Profile, Appearance, Stock Pool and
  Strategy. Lazy route transitions now settle keyboard focus on the new
  content heading; unknown authenticated routes are recoverable. ECharts uses
  live semantic light/dark palettes, accessible names/summaries and reduced
  motion. All ten mode/accent combinations pass the measured text/chart
  contrast matrix, and authenticated desktop/mobile Lighthouse Accessibility
  both score 100. Real Product API Chrome evidence is under
  `docs/evidence/phase-47/`.
- Community Parity Delivery Plan Phases 1-8 restored the product shell and
  Chrome MCP browser evidence. The historical gaps recorded in
  `docs/roadmap/COMMUNITY_FEATURE_PARITY_GAP.md` were then classified and
  resolved by Phases 32–40. That parity-only RC conclusion is historical and
  was superseded when Phase 41 opened the Product experience program.
- Product-depth foundations and final parity closure are delivered: Backtest,
  Strategy and isolated signal production, Stock Pool, Paper Trading, Agent
  workbench, personal Agent Policy, Operations and Data Center. The final V2
  matrix has no unexplained `PARTIAL`/`MISSING` item and the Phase 40 D-items
  are closed or explicitly dropped with evidence.
- Release reminder (ADR-0015): at the BeyondQuant Next v1.0 official release,
  disable GitHub auto-merge and restore the single-maintainer human merge gate.
- Active phase blocker: **none**. Phase 48 is authorized by Accepted ADR-0024.
  The v1.0 RC gate is closed until Phase 48 reopens a separate human review.
  The post-Phase 40 DSH Upgrade Lane is scheduled separately in
  `DSH_UPGRADE_LANE.md` and does not alter the current DSH pin.

Git SHA is not phase state. The current clean baseline must always be derived
from `git fetch origin` followed by `git rev-parse origin/main`; this file must
not hard-code a SHA or describe a transient pull request/merge state.
