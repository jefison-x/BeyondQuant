# Phase 44 acceptance evidence

> 本文记录该 Phase 的验收与审计证据。中文负责说明和结论；文件名、路径、命令、字段、状态码、测试计数及原始观察值保持英文原样。

Phase 44 implements ADR-0024's route-backed user center and durable appearance
boundary. The Community profile, assets, models, agent-policy, paper-trading,
layout and theme implementations were inspected read-only and classified in
`docs/migration/COMMUNITY_MIGRATION_INVENTORY.md`. Visual language and user
flows were used as evidence; Community storage, API and runtime coupling were
not copied.

## Contract and persistence evidence

- PostgreSQL owns one versioned `ui-preferences.v1` record per durable user.
  Backend tests cover defaults, restart-safe reads, closed values, optimistic
  version conflicts and two-owner isolation.
- Gateway exposes only same-origin Product API GET/PUT routes and supplies the
  exact authenticated owner header to Backend.
- The pre-mount browser cache is a validated, non-authoritative paint hint. It
  contains only schema, color mode and accent—never identity, credentials or a
  trusted version—and Backend authority replaces it after authentication.
- A real Compose save of dark/indigo survived Backend and Gateway restart and
  a full browser reload. The acceptance account was then restored to
  system/emerald.

## Automated verification

- Architecture suite: passed.
- Backend PostgreSQL suite: passed.
- Gateway suite: 51 passed.
- Frontend production build: passed.
- Frontend unit tests: 63 passed across 22 files.
- Mocked Chromium Product journeys: 12 passed, including durable appearance
  save/reload and user-center Paper Trading reachability.
- Full isolated Compose smoke: passed.
- Real Product API Chromium journeys: 3 passed.
- Complete local CI: all 13 checks passed.

## Chrome DevTools MCP review

- `appearance-system-emerald.png`: 1440x900 route-backed user center with the
  default system mode, emerald accent and consolidated navigation.
- `appearance-dark-indigo.png`: 1440x900 durable dark/indigo state using the
  global semantic palette without changing success/warning/risk meaning.
- `appearance-mobile-dark-indigo.png`: 390x844 responsive user-center selector
  and stacked appearance controls.
- `lighthouse-desktop.html` and `lighthouse-desktop.json`: production Compose
  navigation audit with Accessibility 100 and Best Practices 100.
- Browser network inspection showed only same-origin frontend and
  Gateway/Product API requests. No Backend, MCP, DSH, PostgreSQL, Redis,
  Tushare or raw event endpoint was requested.

## Community feature checklist

| Capability | Result |
|---|---|
| Profile, assets, models and policy consolidation | PASS — one responsive route-backed user center. |
| Paper Trading reachability | PASS — user-center route and real Product API page. |
| Durable cross-device appearance | PASS — owner-scoped PostgreSQL contract and restart proof. |
| System/light/dark modes | PASS — live preview and validated pre-mount restore. |
| Five closed accent themes | PASS — emerald, ocean, indigo, amber and graphite. |
| Global semantic consistency | PASS — shared tokens and theme-aware ECharts recreation. |
| Contrast and mobile behavior | PASS — Lighthouse 100 and Chrome 390x844 review. |
| Credential secrecy and policy precedence | PASS — existing Product API boundaries preserved and regression-tested. |
| Community theme/runtime coupling | REPLACED — BYQ Product API and `ui-preferences.v1`. |
