# Community Feature Parity Matrix V2

Community feature parity status after the Phase 7/8 browser review. Each
surface is marked `PASS`, `REDESIGNED_PASS`, `PARTIAL`, `MISSING`,
`INTENTIONAL_DROP`, or `FAIL`. Browser observations are recorded in
[`COMMUNITY_FEATURE_PARITY_CHROME_MCP_REVIEW.md`](COMMUNITY_FEATURE_PARITY_CHROME_MCP_REVIEW.md).
Detailed gaps are in
[`COMMUNITY_FEATURE_PARITY_GAP.md`](COMMUNITY_FEATURE_PARITY_GAP.md).

| Community surface | Status | Notes |
|---|---|---|
| Login | REDESIGNED_PASS | Durable username/password session replaces Product Token browser login. |
| Home/Dashboard | PARTIAL | Resource status and recent lists exist; Community card/quick-action depth is reduced. |
| Agent | REDESIGNED_PASS | Sessions, conversation composer, WorkflowTrace, thinking panel, approval decisions, backtest context, and artifacts are real; assistant drawer remains partial. |
| Research | PARTIAL | Entity/approval lookup exists; lineage DAG and full research workspace are missing. |
| Strategy | REDESIGNED_PASS | Editor with templates/snippets, draft save/validate, immutable version creation, export, and approval banner are real. |
| Backtest | REDESIGNED_PASS | Result workspace (filters, mobile cards, equity curve, trades, blocked trades, corporate actions, compare, run/cancel, delete, 8 detail tabs) is real; create wizard submits via an immutable signal_snapshot (ADR-0017), end-to-end verified in Chrome (job backtest_4f64f70c81c146c296874da762cb5d7a). |
| Stock Pool | REDESIGNED_PASS | Catalog types, description, weights, membership detail, filters, and mobile cards are real; snapshot history remains partial. |
| Paper Trading | REDESIGNED_PASS | Accounts, orders, positions, fills, and derived ledger are real; snapshots/settlement/import-export remain partial. |
| Profile | REDESIGNED_PASS | Durable profile form and owner-scoped save work through Product API. |
| Models | PARTIAL | Masked configured status exists; credential/profile/Agent binding management is DEFERRED. |
| Assets | PARTIAL | Asset index and config-asset import/export exist; strategy/backtest re-import is not implemented. |
| Agent Policy | REDESIGNED_PASS | Personal approval preferences persist through Product API; presets and rule CRUD remain partial. |
| Operations | PARTIAL | Safe status and admin user/approval projections exist; most operations workbenches are placeholders or missing. |
| Data Center | REDESIGNED_PASS | Provider capability (masked) and sync status are real; data-source config and sync jobs remain partial. |
| Shared components | PARTIAL | Shell/chart/metric/loading/empty/error exist; deeper Community components are missing. |

## Release conclusion

Product-depth phases delivered: Backtest result workspace, Strategy, Stock
Pool, Paper Trading, Agent workbench, personal Agent Policy, and Data Center.
Remaining `PARTIAL`/`DEFERRED` items are explicitly bounded: the
strategy-to-backtest signal producer (D-0002, needs a producer ADR), model
credential CRUD, asset strategy/backtest re-import, agent policy presets/rule
CRUD, operations
workbenches, data sync jobs, and paper snapshots/settlement. The next step is
the human v1.0 RC review with these deferred items recorded.
