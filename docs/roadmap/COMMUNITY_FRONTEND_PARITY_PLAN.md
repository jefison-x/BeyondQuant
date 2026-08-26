# Community Parity Delivery Plan

Status: `COMPLETE`

本计划在保留新架构的前提下恢复 Community user features：

```text
Browser -> BYQ Product API / Gateway -> BYQ domain or Runtime Adapter
        -> MCP / Backend / DSH behind accepted boundaries
```

每个 phase 必须同时交付：与 Community reference 对齐的 frontend page/UX；页面后的 Product API/Backend capability；Community-derived contract/regression tests 和 BYQ Playwright coverage。只有 page shell 或 placeholder business state 不算完成。

## 指导规则

- 每 phase 一个 isolated worktree/branch/Draft PR。
- 构建一个 business block、测试其 capabilities，然后停在 human merge gate。
- Community source 只读；仅在 inspect → classify → extract invariants → implement 后 port logic/tests。
- BaoStock、AKShare、VectorBT、PydanticAI、Hermes 和旧 raw API/event/DB coupling 保持 `DROP`/`REPLACE`。
- Browser time 使用 `Asia/Shanghai`；durable session 必须跨 refresh。

## Phase 1 — Session reliability 与 timezone

Frontend 修复 auth bootstrap refresh redirect 和 China-time formatting；`/api/auth/me` 返回 durable subject/role；Playwright 验证 reload-after-login，unit test 验证 formatter。Status: PR #34 merged。

## Phase 2 — Admin operations workspace 与 projections

交付 role-protected `OpsLayout + OpsSidebar` 和 database、sources、cache、models、agents、budget、runtime、graphs、access 九页。增加 owner-scoped list projections：`GET /api/product/research/tasks`、`experiments`、`backtests`、`strategies`、`factors`；`GET /api/product/dashboard` 返回 BYQ store counts/status。Destructive operations 保持 RBAC 后 read-only。Port research idempotency、backtest retry/resource、owner/actor assertions；添加 Product API tests 和 Playwright admin/list states。Status: PR #35 merged。

## Phase 3 — Home dashboard parity

Frontend 提供 strategies、backtests、stock pools、cache coverage、health、quick actions、recent results/resource bars。Product API 从 BYQ stores 聚合 counts/recent/data status 和真实 service readiness。测试 partial-failure、counts 和 Playwright journeys。Status: PR #36/#37 merged。

## Phase 4 — Agent research workbench parity

Frontend 提供 conversation、session history、streaming WorkflowTrace、thinking steps、artifact/approval/backtest cards。Product API 使用已有 session turn/resume/cancel，并补 normalized replay/approval inbox/decision。Port approval/audit 和 recovery invariants；测试 Agent contracts、Playwright stream/history/approval/error。Status: PR #38–#41 merged。

## Phase 5 — Strategy 与 Backtest workspaces

Frontend 提供 strategy list/detail、Python editor、templates、validation、version history，以及 backtest list/filter/compare/preflight/results/charts/trades/positions/logs/metrics。Product API 提供 strategy list/version/export/validation 和 backtest list/submit/run/cancel/result，使用 content-addressed manifests/immutable references。Port version snapshot、input manifest、A-share golden engine、object integrity tests，并覆盖 Product API/Playwright。Status: PR #42–#46 merged。

## Phase 6 — Stock Pool 与 Paper Trading

Frontend 提供 pool catalog/create/membership/snapshots/weights/mobile cards，以及 paper accounts/positions/orders/ledger/snapshots/strategy/risk。Product API 提供 pool list/version/membership 和 paper account/order/position/ledger/snapshot。Port pool version、universe guards、paper risk semantics，并验证 create/list/detail/owner isolation。Status: PR #47 merged。

## Phase 7 — My Space pages

拆分 assets、models、agent policy、profile。提供 durable profile/preferences、masked credential endpoints、owner-scoped asset index/export/import。Port bundle determinism/secret exclusion/object ownership tests；Playwright 验证 masked secrets/owner scope。Status: PR #48 merged。

## Phase 8 — Release parity 与 browser evidence

执行完整 Community checklist、每页 Chrome MCP review、真实 Product API Playwright golden journey，并更新 `COMMUNITY_FEATURE_PARITY_MATRIX_V2.md`。Status: PR #49 merged。

每个 phase 均停在 Draft PR/human merge gate。Phases 1–8 恢复 product shell，后续 product-depth phases 交付 Backtest、Strategy、Stock Pool、Paper Trading、Agent、Agent Policy 和 Data Center 深度。明确 deferred items 记录于 `COMMUNITY_FEATURE_PARITY_MATRIX_V2.md` 供 v1.0 RC review。
