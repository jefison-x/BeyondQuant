# Phase 40 Community feature checklist

The Community repository was inspected read-only before implementation. The
classification evidence is in `docs/migration/COMMUNITY_MIGRATION_INVENTORY.md`
and the final decisions are in
`docs/roadmap/COMMUNITY_FEATURE_PARITY_MATRIX.md`.

| Capability | Decision | Evidence |
|---|---|---|
| Strategy `generate_signals` contract | `PORT_LOGIC` / `PORT_TESTS` | Closed Pandas profile creates a normalized immutable signal snapshot. |
| Community in-process `exec` | `REPLACE` | Credential-free, resource-bounded sandbox; trusted worker never executes source. |
| Target-weight/stateful strategy execution | `REFERENCE_ONLY` | v1 fails closed; no compatibility fallback. |
| Loading/error/empty states | `PORT_COMPONENT` / `REFACTOR` | `AppStateBlock` plus component tests. |
| Pagination | `PORT_COMPONENT` / `REFACTOR` | `EntityPagination`, direct bounded Product projection and >200-row tests. |
| Strategy archive visibility | `PORT_UX` | Active view hides superseded drafts; explicit archive view restores them. |
| Strategy description/parameters/schema | `REUSE_AS_IS` / `REFACTOR` | Editable draft fields frozen into read-only StrategyVersion and signal input. |
| Mutable enable/disable and non-artifact CRUD | `DROP` / `REPLACE` | Artifact lifecycle and explicit owner approval authorize execution. |
| Approval/assistant/thinking components | `REUSE_AS_IS` / `REFACTOR` | Phase 36 normalized public components; hidden reasoning remains dropped. |
| Stock Pool/model settings/analytics/chart | `REUSE_AS_IS` / `PORT_UX` / `REFACTOR` | Phase 34/37/38 implementations and existing `ChartWrapper` remain authoritative. |

Result: no unexplained Community `PARTIAL` or `MISSING` capability remains.
