# Community Feature Parity Matrix V2

Current Community feature parity status after Phase 34. Each
surface is marked `PASS`, `REDESIGNED_PASS`, `PARTIAL`, `MISSING`,
`INTENTIONAL_DROP`, or `FAIL`. Browser observations are recorded in
[`COMMUNITY_FEATURE_PARITY_CHROME_MCP_REVIEW.md`](COMMUNITY_FEATURE_PARITY_CHROME_MCP_REVIEW.md).
Detailed gaps are in
[`COMMUNITY_FEATURE_PARITY_GAP.md`](COMMUNITY_FEATURE_PARITY_GAP.md).

| Community surface | Status | Notes |
|---|---|---|
| Login | REDESIGNED_PASS | Durable username/password session replaces Product Token browser login. |
| Home/Dashboard | PARTIAL | Resource status and recent lists exist; Community card/quick-action depth is reduced. |
| Agent | REDESIGNED_PASS | Sessions, conversation composer, closed normalized WorkflowTrace cards/activities, actionable strategy/stock/optimization projections, local/global approvals, backtest context, conversation starters, and responsive assistant drawer are real and verified through Product API. |
| Research | PARTIAL | Entity/approval lookup exists; lineage DAG and full research workspace are missing. |
| Strategy | REDESIGNED_PASS | Editor with templates/snippets, durable draft save/delete (soft-superseded immutable artifacts), static validation, immutable version creation, version-history list, per-strategy backtest counts, export, and approval banner are real. |
| Backtest | PARTIAL | Result workspace and immutable signal_snapshot wizard are real; a newly authored strategy still cannot produce that snapshot (D-0002), so the product journey is incomplete. |
| Stock Pool | REDESIGNED_PASS | Owner-scoped catalog and five persisted projections, immutable member/weight snapshots, trusted index as-of history, lifecycle/tombstone semantics, frozen downstream references, MCP tools, and desktop/mobile Product API flows are real. |
| Paper Trading | COMPLETE | Six persisted tabs, exact T+1/cash ledger semantics, immutable settlement, order audit, versioned risk controls, frozen pool binding, and digested new-ID bundle transfer are verified through real Product API and Chrome MCP. |
| Profile | REDESIGNED_PASS | Durable profile form and owner-scoped save work through Product API. |
| Models | PARTIAL | Masked configured status exists; credential/profile/Agent binding management is DEFERRED. |
| Assets | PARTIAL | Asset index and config-asset import/export exist; strategy/backtest re-import is not implemented. |
| Agent Policy | PARTIAL | Personal approval preferences persist through Product API; presets and rule CRUD remain incomplete. |
| Operations | PARTIAL | Safe status and admin user/approval projections exist; most operations workbenches are placeholders or missing. |
| Data Center | REDESIGNED_PASS | Tushare-only encrypted credential lifecycle, bounded test/sync, durable per-symbol jobs and honest PostgreSQL coverage audit are real and Chrome-verified. |
| Shared components | PARTIAL | Shell/chart/metric/loading/empty/error exist; deeper Community components are missing. |

## Release conclusion

Product-depth foundations exist for Backtest, Strategy, Stock Pool, Paper
Trading, Agent, Agent Policy, and Data Center. Remaining `PARTIAL` items are
explicitly bounded: the
strategy-to-backtest signal producer (D-0002, needs a producer ADR), model
credential CRUD, asset strategy/backtest re-import, agent policy presets/rule
CRUD, operations
workbenches. The v1.0 RC gate
is **not eligible for review** until Phases 36–40 close these items (or record
an accepted intentional DROP), the parity matrix has no unexplained PARTIAL,
and a real-Product-API, no-mock, multi-user golden journey passes.
