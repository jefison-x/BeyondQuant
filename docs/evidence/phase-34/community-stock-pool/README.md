# Phase 34 Community Stock Pool visual baseline

Captured on 2026-08-21 as visual and interaction reference evidence for the
Phase 34 decision gate. This baseline is not Phase 34 implementation or
acceptance evidence.

## Provenance and safety

- Read-only source: `BeyondQuant-community` commit
  `58dd99dad9757e1feb53bfc0af7d54faf7bd52ac`.
- Inspected source: `frontend/src/views/StockPoolView.vue` and
  `frontend/src/components/stocks/StockPoolDialog.vue`.
- Browser: Google Chrome `151.0.7922.173`, driven headlessly with Playwright.
- Viewports: desktop `1440x900`; mobile `390x844`.
- The Community frontend was copied to a temporary runtime directory. Vite
  dependencies were read from the existing installation, while Vite caches
  and generated state remained under `/tmp`.
- Browser routes returned deterministic reference fixtures for auth, catalog,
  detail, candidate search, activation, creation, and deletion. No Community
  Backend or PostgreSQL endpoint was contacted, and no Community mutation was
  performed.
- `BeyondQuant-community` remained clean after capture. Image integrity is
  recorded in `SHA256SUMS`.

The deterministic fixtures make the page states reproducible, but they do not
prove Community API behavior or BYQ persistence. Phase 34 must still use real
BYQ Product API flows and persisted data for acceptance.

## Screenshot index

1. [Desktop custom catalog and members](./01-desktop-custom-catalog-and-members.png)
   — summary strip, type catalog, lifecycle affordances, custom member detail.
2. [Desktop custom filter conditions](./02-desktop-custom-filter-conditions.png)
   — the saved selection criteria projection.
3. [Desktop index constituents](./03-desktop-index-constituents.png)
   — read-only index identity, effective date, snapshot summary, constituents,
   and weights.
4. [Desktop index snapshot history](./04-desktop-index-snapshot-history.png)
   — dated immutable membership history affordance.
5. [Desktop create dialog candidates](./05-desktop-create-dialog-candidates.png)
   — pool identity, filters, candidate search, metrics, and add action.
6. [Desktop create dialog final membership](./06-desktop-create-dialog-final-membership.png)
   — candidate-to-final-list transition and removal action.
7. [Desktop delete confirmation](./07-desktop-delete-confirmation.png)
   — destructive lifecycle confirmation.
8. [Mobile catalog cards](./08-mobile-catalog-cards.png)
   — responsive summary, catalog cards, lifecycle actions, and bottom nav.
9. [Mobile create dialog](./09-mobile-create-dialog.png)
   — single-column form adaptation and scroll behavior.

## Interaction observations

- Desktop uses a catalog/detail split: selection on the left updates type-
  specific detail on the right without route navigation.
- Custom pools expose member and saved-filter tabs plus activate/deactivate and
  delete actions. Delete requires an explicit confirmation.
- Index pools are system-maintained and read-only. Their detail separates the
  latest constituents from dated historical snapshots and displays index
  weights.
- Dynamic pools appear in the shared catalog but only provide a future-state
  placeholder in the captured implementation.
- Creation is a wide dialog that separates candidate discovery from the final
  membership list. A candidate can be added or removed before submission.
- On mobile, the catalog switches from the desktop table to stacked cards and
  the dialog becomes a long, single-column form. The initial mobile viewport
  does not expose the dialog footer, so Phase 34 must verify scroll/focus and
  action reachability rather than merely matching the layout.
- The fixed desktop operation column compresses descriptive catalog content.
  Preserve the information architecture, but do not copy this truncation.
- The captured create/final-list flow has no member-weight editor. Phase 34
  must implement weights from the accepted BYQ contract rather than infer them
  from the Community visual surface.

## Migration classification

| Surface | Classification | Phase 34 direction |
| --- | --- | --- |
| Brand color, cards, tables, typography | `PORT_STYLE` | Reuse the visual language through BYQ tokens. |
| Catalog/detail split and responsive navigation | `PORT_LAYOUT` + `PORT_UX` | Retain the information hierarchy and responsive intent. |
| Candidate/final-list dialog | `PORT_COMPONENT` + `PORT_UX` | Rebuild against BYQ draft/snapshot contracts. |
| Custom member and filter tabs | `REFACTOR` | Render persisted BYQ projections; no browser-owned snapshot. |
| Index constituents and history | `REFACTOR` | Use immutable, versioned BYQ membership snapshots and provenance. |
| Activation/deactivation/delete | `PORT_UX` | Bind only to lifecycle semantics accepted by the Phase 34 ADR. |
| Dynamic pool placeholder | `REFERENCE_ONLY` | Do not implement until provenance and refresh semantics are explicit. |
| Community auth, API, storage, identifiers | `REPLACE` | Use durable BYQ identity and Gateway/Product API only. |

## Phase 34 checklist derived from the baseline

- [ ] Owner-scoped paged catalog with custom/index/dynamic provenance.
- [ ] Catalog/detail selection and type-specific persisted projections.
- [ ] Persisted member editing through immutable snapshots.
- [ ] Persisted weight validation and editing.
- [ ] Persisted filter-condition projection.
- [ ] Read-only index constituents with effective-date provenance.
- [ ] Historical snapshot list with stable version/fingerprint identity.
- [ ] ADR-defined activation, deactivation, and delete semantics.
- [ ] References from Paper Trading, research, and backtest remain valid and
      auditable across lifecycle changes.
- [ ] Desktop table and mobile card behavior use Product API only.
- [ ] Mobile create/edit actions remain reachable with keyboard and scrolling.
- [ ] BYQ Chrome MCP review is captured separately using real Product API and
      persisted data before Phase 34 is marked complete.

## Capture-time observations not to copy

Chrome reported a missing favicon request and Vue warned that icon components
were placed in a deeply reactive page-action collection. They did not block
capture, but are Community implementation details rather than BYQ behavior to
port.
