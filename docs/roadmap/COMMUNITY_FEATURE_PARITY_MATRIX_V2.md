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
| Agent | PARTIAL | Normalized trace/approval/context panels exist; conversation/tool/card depth is missing. |
| Research | PARTIAL | Entity/approval lookup exists; lineage DAG and full research workspace are missing. |
| Strategy | PARTIAL | List/validate/export exists; full editor, templates, version history, and save/delete are missing. |
| Backtest | PARTIAL | List/status/empty chart exists; create wizard, comparison, trades/positions/logs/snapshot are missing. |
| Stock Pool | PARTIAL | Create/list exists; catalog types, member editing, index constituents, filters, weights, snapshots are missing. |
| Paper Trading | PARTIAL | Create/order/positions/fills exist; ledger, snapshots, settlement, risk controls, import/export are missing. |
| Profile | REDESIGNED_PASS | Durable profile form and owner-scoped save work through Product API. |
| Models | PARTIAL | Masked configured status exists; credential/profile/Agent binding management is missing. |
| Assets | PARTIAL | Asset index and config-asset import/export exist; strategy/backtest re-import is not implemented. |
| Agent Policy | PARTIAL | Platform policy and approval history exist; personal preferences/presets/rule CRUD are missing. |
| Operations | PARTIAL | Safe status and admin user/approval projections exist; most operations workbenches are placeholders or missing. |
| Data Center | PARTIAL | Provider/migration/quality status exists; data-source config, sync, and coverage detail are missing. |
| Shared components | PARTIAL | Shell/chart/metric/loading/empty/error exist; deeper Community components are missing. |

## Release conclusion

The current release is not yet a v1.0 RC. Several high-value Community
workflows remain `PARTIAL` or `MISSING`, especially Strategy, Backtest, Stock
Pool, Paper Trading, Agent, Models, Assets, Agent Policy, and Operations. The
next work must close these product-depth gaps before the RC review gate can be
reopened.
