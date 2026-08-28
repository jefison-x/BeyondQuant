# Paper Trading main-workspace maintenance evidence

## Scope

- Move `模拟操盘` from User Center to primary Product navigation immediately
  below `回测管理`.
- Make `/paper-trading` canonical and redirect the legacy
  `/user/paper-trading` route.
- Recompose the existing Phase 35 workflow with the shared Phase 46
  `ManagementWorkspace` catalog/detail hierarchy.
- Do not change Backend, Gateway, Product API, DSH, authorization, account
  persistence, settlement, order, risk or transfer semantics.

## Community classification

The read-only Community `frontend/src/components/layout/AppSidebar.vue` and
`frontend/src/views/PaperTradingView.vue` were inspected. The primary business
destination is `PORT_UX`; account catalog/detail continuity is `PORT_LAYOUT`;
all Community APIs, Agent/runtime integration, broker behavior and storage are
`REFERENCE_ONLY` / `DROP`. No Community source was copied or modified.

## Verification

- `npm run build`: PASS
- `npm run test`: PASS — 42 files / 113 tests
- mocked Playwright navigation/Paper Trading/mobile journey: PASS — 4 tests
- `python3 -m unittest discover -s tests -p 'test_*.py'`: PASS — 65 tests
- desktop Chrome review: PASS
- mobile Chrome review: PASS
- legacy `/user/paper-trading` redirect: PASS
- Console errors/warnings/issues: none
- Network boundary: PASS — same-origin `/api/auth/*` and `/api/product/*` only
- `git diff --check`: PASS

## Browser evidence

- `desktop-paper-trading.png`
- `mobile-paper-trading.png`
- `mobile-paper-trading-navigation.png`
- `CHROME_MCP_REVIEW.md`
