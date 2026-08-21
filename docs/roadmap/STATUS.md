# BeyondQuant Status

This file is the phase source of truth. It is intentionally short so a new
Codex session does not infer project state from commit history.

- Current completed phase: **Phase 34**
- Next phase: **Phase 35 — Paper Trading depth implementation** (see
  `docs/roadmap/COMMUNITY_FULL_PARITY_PLAN.md` and
  `docs/roadmap/COMMUNITY_FULL_PARITY_PHASE_DETAILS.md`)
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
- Accepted Stock Pool snapshot/lifecycle ADR: **ADR-0020**
- Open architecture decisions: ADR-0018 and ADR-0019 remain Proposed and
  block their dependent future phases; they do not block Phase 35.

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
  [ADR-0020](../architecture/adr/ADR-0020-stock-pool-snapshot-lifecycle.md)
  is Accepted.
- Phase 23 acceptance evidence established a Product Skeleton browser and
  parity baseline. Its mocked Playwright navigation smoke is not evidence of
  a real Product API golden journey and is not a v1.0 RC gate.
- Phase 23 produced a Product Skeleton release-parity baseline. It did not
  establish final Community feature parity. Phases 24–31 established the
  durable product/storage baseline; remaining product-depth work is tracked
  in Phases 32–40.
- Phase 30 produced the initial V2 parity matrix and browser surfaces, but its
  original RC conclusion was superseded by the gap audit and Phases 32–40.
  Real-Product-API, no-mock, multi-user golden-journey acceptance remains open.
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
  The end-to-end strategy-to-backtest journey remains D-0002 (transferred to
  Phase 40) pending a dedicated producer ADR; until then snapshots come from
  the keyless fixture/import path. Optional result-object sweep D-0003 was
  also transferred to Phase 40 and remains observation-triggered.
- Phase 33 (Strategy workspace depth) completed: durable `strategy_draft`
  save (tolerant of intermediate edits) and owner-scoped soft-supersede
  delete, per-strategy version history, and real backtest counts are exposed
  through Backend/MCP/Product API and the strategy workspace UI (PR #85);
  saved drafts stay editable, read-only version detail, and Chrome DevTools
  MCP evidence are recorded. Follow-up hardening/scope items are registered
  as D-0009 (superseded-draft visibility), D-0010 (version-history projection
  bound), D-0011 (StrategyView component tests), and D-0012 (Community deep
  profile fields) in the Deferred Items Registry; all four are assigned to
  Phase 40 rather than the completed Phase 33. The end-to-end
  strategy-to-backtest journey remains D-0002 (signal producer).
- Phase 34 (Stock Pool depth) completed: owner-scoped catalog/detail and five
  persisted projections now use immutable membership snapshots with stable
  version/fingerprint identity; weights are validated; custom edits create new
  snapshots; index pools use trusted Tushare provenance and no-look-ahead
  effective-date lookup; lifecycle/tombstone behavior and frozen Paper
  Trading/research/backtest references are auditable. Backend, Product API,
  MCP `byq_pool_*`, frontend, desktop/mobile Chrome MCP evidence, and the
  Community-derived checklist are complete.
- Community Parity Delivery Plan Phases 1-8 restored the product shell and
  Chrome MCP browser evidence, but
  `docs/roadmap/COMMUNITY_FEATURE_PARITY_GAP.md` records substantial remaining
  `PARTIAL`/`MISSING` product-depth workflows. The v1.0 RC review gate is not
  yet satisfied.
- Product-depth foundations delivered: Backtest result workspace, Strategy,
  Stock Pool, Paper Trading, Agent workbench, personal Agent Policy, and Data
  Center. These surfaces are not all parity-complete. Remaining items (signal
  producer for end-to-end
  strategy-to-backtest, model credential CRUD, asset re-import, agent policy
  presets/rule CRUD, operations workbenches, data sync jobs, paper
  snapshots/settlement) are recorded in the V2 parity matrix, Deferred Items
  Registry, and Phases 34–40. They must close before the RC review gate.
- Release reminder (ADR-0015): at the BeyondQuant Next v1.0 official release,
  disable GitHub auto-merge and restore the single-maintainer human merge gate.
- Active architecture blockers: **none for Phase 35.** ADR-0018 and ADR-0019
  remain later-phase blockers.

Git SHA is not phase state. The current clean baseline must always be derived
from `git fetch origin` followed by `git rev-parse origin/main`; this file must
not hard-code a SHA or describe a transient pull request/merge state.
