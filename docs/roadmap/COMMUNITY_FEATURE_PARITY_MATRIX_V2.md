# Community Feature Parity Matrix V2

这是 Phase 40 后的最终 Community feature parity 状态。每个 surface 标记为 `PASS`、`REDESIGNED_PASS`、`PARTIAL`、`MISSING`、`INTENTIONAL_DROP` 或 `FAIL`。Browser observations 见 [`COMMUNITY_FEATURE_PARITY_CHROME_MCP_REVIEW.md`](COMMUNITY_FEATURE_PARITY_CHROME_MCP_REVIEW.md)，详细 gaps 见 [`COMMUNITY_FEATURE_PARITY_GAP.md`](COMMUNITY_FEATURE_PARITY_GAP.md)。

| Community surface | Status | 说明 |
|---|---|---|
| Login | REDESIGNED_PASS | Durable username/password session 取代 Product Token browser login。 |
| Home/Dashboard | REDESIGNED_PASS | Durable owner-scoped resources、recent activity、navigation 和 quick actions 使用 BYQ Product API semantics。 |
| Agent | REDESIGNED_PASS | Sessions、conversation composer、封闭 normalized WorkflowTrace cards/activities、可操作 strategy/stock/optimization projections、local/global approvals、backtest context、conversation starters 和 responsive assistant drawer 均真实并经 Product API 验证。 |
| Research | REDESIGNED_PASS | Owner-scoped task creation、entities、approvals 和 lineage projections 是 durable BYQ workflows，不复制 Community workspace。 |
| Strategy | REDESIGNED_PASS | Editor、durable lifecycle、deep fields、direct paginated history/count projections、approval 和 archive visibility 均真实。 |
| Backtest | REDESIGNED_PASS | ADR-0023 将 approved strategy/frozen canonical inputs 转为完整 result workspace 消费的 immutable signal snapshot。 |
| Stock Pool | REDESIGNED_PASS | Owner-scoped catalog 与五个 persisted projections、immutable member/weight snapshots、trusted index as-of history、lifecycle/tombstone semantics、frozen downstream references、MCP tools 和 desktop/mobile Product API flows 均真实。 |
| Paper Trading | COMPLETE | 六个 persisted tabs、精确 T+1/cash ledger semantics、immutable settlement、order audit、versioned risk controls、frozen pool binding 和 digested new-ID bundle transfer 已由真实 Product API/Chrome MCP 验证。 |
| Profile | REDESIGNED_PASS | Durable profile form 和 owner-scoped save 经 Product API 工作。 |
| Models | REDESIGNED_PASS | Encrypted write-only credentials、model profiles 和 Product Agent binding 持久且 secret-safe。 |
| Assets | REDESIGNED_PASS | Digested workspace export/import 创建 owner-safe identities，重新验证 strategies，并诚实保留 backtests archives。 |
| Agent Policy | REDESIGNED_PASS | Durable presets、effective ordered rule CRUD、audit 和 platform-precedence approvals 均真实。 |
| Operations | REDESIGNED_PASS | 九个有界 admin workbenches 暴露 normalized status、usage、access、audit 和 threshold projections。 |
| Data Center | REDESIGNED_PASS | Tushare-only encrypted credential lifecycle、有界 test/sync、durable per-symbol jobs 和诚实 PostgreSQL coverage audit 均真实并经 Chrome 验证。 |
| Shared components | REDESIGNED_PASS | Shared state/pagination，加经验证的 phase-specific approval、assistant、model 和 operations components，覆盖已分类 Community set。 |

## 最终 parity 与 coherence 结论

Phases 32–40 关闭每个已解释 product-depth gap，或记录显式 replacement/drop。Matrix 不含无法解释的 `PARTIAL`/`MISSING`；real-Product-API、no-mock、multi-user golden journey 及 desktop/mobile Chrome review 记录于 `docs/evidence/phase-40/`，因此 Phase 40 完成 parity gate。

原结论中的即时 v1.0 RC review 已在 2026-08-23 被 Accepted ADR-0024 和 Phases 41–48 Product experience program 取代。Phase 48 已对迁移后的 capabilities 重新对账，并重跑 no-mock two-user journey 与 desktop/tablet/mobile Chrome review。不存在无法解释的 `PARTIAL`/`MISSING`、owner crossover、fake state、raw internal browser path 或未解决 theme inconsistency。这重新开放独立 human v1.0 RC review，但不自动通过 review 或声明 release。
