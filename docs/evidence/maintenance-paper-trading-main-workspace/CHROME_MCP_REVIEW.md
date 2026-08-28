# Chrome MCP review

- Review URL: `http://127.0.0.1:8766/paper-trading`
- Data path: existing formal Gateway at `127.0.0.1:8100`
- Desktop: primary navigation order is Stock Pool → Strategy → Backtest →
  Paper Trading; the active item is Paper Trading. The page uses the shared
  summary plus catalog/detail hierarchy and renders three real persisted
  accounts.
- Legacy route: navigating to `/user/paper-trading` resolves to canonical
  `/paper-trading`.
- Mobile `390x844`: the page becomes one column without horizontal overflow;
  the navigation drawer preserves Paper Trading directly below Backtest.
- Loading and empty states remain the existing Product-backed states; no fake
  data or local-only state was added.
- Console: no errors, warnings or issues observed.
- Network: all observed requests were same-origin and limited to
  `/api/auth/*`, `/api/product/settings/appearance`, `/api/product/approvals`
  and `/api/product/paper/*`; no Backend, DSH, MCP, database or provider direct
  request was observed.
