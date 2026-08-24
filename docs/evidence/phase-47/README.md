# Phase 47 acceptance evidence

Phase 47 closes the interaction, responsive and accessibility scope authorized
by ADR-0024. The corresponding Community components and UX patterns were
inspected read-only and classified in
`docs/migration/COMMUNITY_MIGRATION_INVENTORY.md` before implementation.

## Product evidence

- Shared loading, empty and recoverable error states expose semantic live
  regions, honest messages and retry actions. Pagination exposes localized
  totals, current-page announcements and a bounded mobile layout.
- Profile, Appearance, Stock Pool and Strategy protect dirty edits across
  resource and route changes. Save controls reflect dirty/busy state and
  successful writes update a visible polite status.
- Route transitions move keyboard focus to the new content heading after lazy
  views settle. Unknown authenticated routes render a recoverable in-shell 404.
- Dates, counts and common lifecycle states use shared localized display
  helpers. Desktop tables collapse to responsive cards or scrollable bounded
  regions without duplicate accessible content.
- Charts use semantic six-color light/dark palettes, rebuild on theme changes,
  publish an accessible chart name and text summary, and disable animation for
  reduced-motion users.
- All five accent colors in light and dark mode pass the recorded text/chart
  contrast matrix. Lighthouse Accessibility is 100 on desktop and mobile.

## Browser evidence

- `byq-phase47-appearance-desktop-light.png`: 1440x900 user-center layout and
  complete light appearance controls.
- `byq-phase47-appearance-mobile-dark.png`: 390x844 dark-mode mobile layout
  with no horizontal overflow.
- `byq-phase47-stock-pool-tablet.png`: 820x1180 real Product Stock Pool catalog
  and selected persisted detail.
- `byq-phase47-backtest-chart-desktop.png`: real completed Backtest with a
  named, summarized equity chart.
- `lighthouse-{desktop,mobile}.{json,html}`: Accessibility 100 and Best
  Practices 100 reports from the authenticated live Product page.

See `CHROME_MCP_REVIEW.md`, `COMMUNITY_FEATURE_CHECKLIST.md` and
`THEME_CONTRAST_MATRIX.md` for the detailed review.

## Automated verification

- Complete local CI: all 13 checks passed.
- Frontend production build: passed.
- Frontend unit tests: 72 passed across 27 files.
- Mocked Chromium Product journeys: 15 passed, including authenticated 404 and
  unsaved Profile navigation protection.
- Real Product API browser smoke: 3 passed against the isolated Compose stack.
