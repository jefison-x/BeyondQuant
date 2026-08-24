# Community Feature Parity Gap Audit

Status: **reconciled and closed by Phase 48**. This document was originally
written after Phase 34 and is retained as the historical gap register. Its
former `PARTIAL` statements were superseded by Phases 35–40 and the complete
conversation-first Product experience delivered in Phases 41–48.

## Reconciliation method

- The read-only Community frontend under
  `/home/jefison/projects/BeyondQuant-community/frontend` was inspected by
  surface; it was never modified or copied.
- Each capability was classified in
  `docs/migration/COMMUNITY_MIGRATION_INVENTORY.md` before its corresponding
  Product phase.
- The Phase 40 V2 matrix closed domain/workbench parity with no unexplained
  `PARTIAL` or `MISSING` row.
- Phases 42–47 deliberately relocated those capabilities into the
  conversation-first shell, user center, System Settings dialog and unified
  management workspaces.
- Phase 48 reran a fresh no-mock, two-user Product journey and desktop,
  tablet and mobile Chrome review across the composed experience.

## Final disposition

| Community surface | BYQ disposition | Final status |
|---|---|---|
| Login and durable user identity | Durable username/password Product session; bootstrap token is not normal browser login. | `REDESIGNED_PASS` |
| Dashboard and quick entry | Xiaoba is the default Product surface; resource summaries/actions remain reachable through Product routes and settings. | `REDESIGNED_PASS` |
| Agent and conversation history | Owner-scoped durable catalog, turn replay, rename, pin, archive/restore and normalized WorkflowTrace. | `REDESIGNED_PASS` |
| Research and approvals | BYQ ResearchTask/Artifact/Approval lineage and bounded approval inbox. | `REDESIGNED_PASS` |
| Stock Pool | Mutable identity plus immutable membership snapshots, lifecycle, weights, history and frozen references. | `REDESIGNED_PASS` |
| Strategy | Editable drafts, validation, immutable versions, approval, export, history and signal lineage. | `REDESIGNED_PASS` |
| Backtest | Approved version → isolated signal snapshot → deterministic result with all eight evidence tabs. | `REDESIGNED_PASS` |
| Paper Trading | Owner-scoped accounts, exact T+1 ledger, settlement, risk controls and safe bundle transfer. | `REDESIGNED_PASS` |
| Profile and appearance | Durable profile plus versioned system/light/dark and closed accent themes. | `REDESIGNED_PASS` |
| Models, assets and Agent policy | Encrypted write-only credentials, profiles/binding, validated asset transfer and effective policy rules. | `REDESIGNED_PASS` |
| Operations and Data Center | Route-backed admin-only bounded projections, Tushare sync and PostgreSQL coverage; no raw infrastructure controls. | `REDESIGNED_PASS` |
| Shared responsive components | Unified states, pagination, dialogs, charts, focus, unsaved-change and semantic theme behavior. | `REDESIGNED_PASS` |

The final detailed comparison remains
[`COMMUNITY_FEATURE_PARITY_MATRIX_V2.md`](COMMUNITY_FEATURE_PARITY_MATRIX_V2.md).
The Phase 48 residual Product and release work is recorded separately in
[`../evidence/phase-48/PRODUCT_GAP_REGISTER.md`](../evidence/phase-48/PRODUCT_GAP_REGISTER.md).
No historical gap in this file authorizes reintroducing Community APIs,
runtime, storage, BaoStock, AKShare, VectorBT, PydanticAI or Hermes.

## Release meaning

Parity and Product-experience implementation are complete, but this is not an
automatic v1.0 release declaration. Phase 48 only reopens the human release-
candidate review required by ADR-0024. The maintainer must separately evaluate
the release evidence and decide whether to accept an RC.
