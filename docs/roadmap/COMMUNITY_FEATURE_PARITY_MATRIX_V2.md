# Community Feature Parity Matrix V2

Final Community feature parity status after Phase 40. Each
surface is marked `PASS`, `REDESIGNED_PASS`, `PARTIAL`, `MISSING`,
`INTENTIONAL_DROP`, or `FAIL`. Browser observations are recorded in
[`COMMUNITY_FEATURE_PARITY_CHROME_MCP_REVIEW.md`](COMMUNITY_FEATURE_PARITY_CHROME_MCP_REVIEW.md).
Detailed gaps are in
[`COMMUNITY_FEATURE_PARITY_GAP.md`](COMMUNITY_FEATURE_PARITY_GAP.md).

| Community surface | Status | Notes |
|---|---|---|
| Login | REDESIGNED_PASS | Durable username/password session replaces Product Token browser login. |
| Home/Dashboard | REDESIGNED_PASS | Durable owner-scoped resources, recent activity, navigation and quick actions use BYQ Product API semantics. |
| Agent | REDESIGNED_PASS | Sessions, conversation composer, closed normalized WorkflowTrace cards/activities, actionable strategy/stock/optimization projections, local/global approvals, backtest context, conversation starters, and responsive assistant drawer are real and verified through Product API. |
| Research | REDESIGNED_PASS | Owner-scoped task creation, entities, approvals and lineage projections are durable BYQ workflows rather than a copy of the Community workspace. |
| Strategy | REDESIGNED_PASS | Editor, durable lifecycle, deep fields, direct paginated history/count projections, approval and archive visibility are real. |
| Backtest | REDESIGNED_PASS | ADR-0023 turns an approved strategy and frozen canonical inputs into an immutable signal snapshot consumed by the complete result workspace. |
| Stock Pool | REDESIGNED_PASS | Owner-scoped catalog and five persisted projections, immutable member/weight snapshots, trusted index as-of history, lifecycle/tombstone semantics, frozen downstream references, MCP tools, and desktop/mobile Product API flows are real. |
| Paper Trading | COMPLETE | Six persisted tabs, exact T+1/cash ledger semantics, immutable settlement, order audit, versioned risk controls, frozen pool binding, and digested new-ID bundle transfer are verified through real Product API and Chrome MCP. |
| Profile | REDESIGNED_PASS | Durable profile form and owner-scoped save work through Product API. |
| Models | REDESIGNED_PASS | Encrypted write-only credentials, model profiles and Product Agent binding are durable and secret-safe. |
| Assets | REDESIGNED_PASS | Digested workspace export/import creates owner-safe identities, revalidates strategies and preserves backtests as honest archives. |
| Agent Policy | REDESIGNED_PASS | Durable presets, effective ordered rule CRUD, audit and platform-precedence approvals are real. |
| Operations | REDESIGNED_PASS | Nine bounded admin workbenches expose normalized status, usage, access, audit and threshold projections. |
| Data Center | REDESIGNED_PASS | Tushare-only encrypted credential lifecycle, bounded test/sync, durable per-symbol jobs and honest PostgreSQL coverage audit are real and Chrome-verified. |
| Shared components | REDESIGNED_PASS | Shared state/pagination plus the proven phase-specific approval, assistant, model and operations components cover the classified Community set. |

## Historical parity conclusion

Phases 32–40 close every explained product-depth gap or record an explicit
replacement/drop. The matrix has no unexplained `PARTIAL`/`MISSING` entry,
and the real-Product-API, no-mock, multi-user golden journey plus desktop and
mobile Chrome review are recorded under `docs/evidence/phase-40/`. Phase 40
therefore completed its parity gate. The immediate v1.0 RC review described by
the original conclusion was superseded on 2026-08-23 by Accepted ADR-0024 and
the Phases 41-48 Product experience program; parity completion remains valid
evidence but is not a current release declaration.
