# Community Feature Parity Chrome MCP Review

本文记录通过 Chrome MCP 对重建后的本地 BeyondQuant topology 执行的 browser review，不是 release approval；human merge gate 仍是最终 Product acceptance。

## 初始 Phase 8 review（2026-08-16，Asia/Shanghai）

- Reviewer: Codex Engineering Plane；Chrome MCP: `http://127.0.0.1:12306/mcp`。
- Topology：从 `main@6b9afd9` rebuild 后运行 `docker compose up -d frontend gateway backend`。
- Origin: `http://127.0.0.1:80`；principal `admin`/role `admin`。
- Method：经真实 username/password login，使用 client navigation；`chrome_get_web_content` 捕获真实 Product API 渲染。Browser 未打开 raw MCP、DSH、Backend、PostgreSQL、Redis 或 provider URL。

| Route | Rendered evidence |
|---|---|
| `/login` | 用户名、密码、进入。 |
| `/` | Backend/provider/migration/runtime/storage/Product health/model/approval/WorkflowTrace/Audit 状态。 |
| `/agent` | 小巴投研、session/history、对话、WorkflowTrace、思考、审批、回测、资产 empty states。 |
| `/stock-pool` | Create form 和 empty catalog。 |
| `/strategy` | 策略版本/详情 empty states，kind `strategy_version`。 |
| `/backtest` | Task center loading/empty，无 raw backend。 |
| `/paper-trading` | 模拟账户创建与 empty list。 |
| `/assets` | strategy/pool/backtest/paper counts、lists、export/import。 |
| `/models` | `deepseek`、configured false、masked/write-only。 |
| `/agent-settings` | Platform policy defaults/approval history。 |
| `/profile` | Nickname/preferences/default prompt 持久值。 |
| `/research-center` | Research assets、approval inbox/entity lookup。 |
| `/data-center` | `tushare`、`not_started`、`not_audited`、无虚构 dataset。 |
| `/system-status`、`/operations`、`/admin/database` | 真实 bounded service/storage/migration/observability 状态。 |

Boundary：browser 只消费 Product API；credentials masked；durable session 跨 refresh/navigation，form 无 Product Token。无 owner data 时 empty state 真实；高级 editor 后续 hardening，故当时标为 `REDESIGNED_PASS`。

## Backtest result workspace（2026-08-17）

在 `main@5af1668` Compose、1440x900 headed Chrome、`chromeuser` admin 下检查真实 completed job `backtest_6346a4d5cfae4e818df0e5b22e6744fd`（return 0.67%、drawdown 0、3 trades、final 201,336.64）。List 有 search/filter/select、收益/回撤/创建时间、run/cancel/compare/refresh。Detail 展示 metrics 和权益曲线、交易明细、拦截、公司行动、Input Manifest/Preflight；完整 frozen strategy/approval/universe/bars/signals/execution。只调用 Product API，无 secret/internal URL。

## Data Center、Agent Policy、Agent、Paper Trading（2026-08-17）

- `/data-center`：显示 provider `tushare`、migration `not_started`、quality `not_audited`、masked-derived 未配置和 sync `not_started`；dataset empty state 诚实。
- `/agent-settings`：platform defaults、pending count、editable personal policy、manual/`auto_approve`/`auto_deny`、limits/save 和真实 `byq_backtest_run` approval。
- `/agent`：live session switch/new/history、composer、resume/cancel、真实 `session.ready`、thinking/timeline、pending approval self-decision 正确拒绝、1 backtest/4 artifacts。
- `/paper-trading`：browser 创建 account；order form 经 Product API 产生真实 fill；tabs 展示 overview、`000001.SZ` position、orders/fills/ledger（cash_delta -1005、fees 5）。Review 发现 paper proxies 未转发 trusted owner headers，已修复并有 regression。

上述页面均只使用 Product API，不暴露 raw internal URL/secret。

## Stock Pool Phase 34（2026-08-21）

在 isolated Compose、desktop 1440x900/mobile 390x844、durable `ci-admin` 下：

- 创建 weighted custom pool；0.8 total 返回 HTTP 422；随后持久化三成员 v2。
- 从 history 读取 immutable v1，fingerprint stable，v2 仍 current。
- 持久化 active/inactive/active lifecycle。
- 2024-01-15 index request 解析到 2024-01-02 snapshot，而非 2024-02-01；展示完整 Tushare/unit/normalization provenance。
- Desktop table/mobile cards 使用同一 persisted catalog；authenticated reload 后 console clean。
- 23? Browser requests 均 same-origin `/api/auth/*`/`/api/product/*`，无 boundary escape。

Review 发现 E2E 未进入 Members tab，以及 Gateway 将 Backend 422 折叠为 503；已修复并覆盖。证据索引：`docs/evidence/phase-34/byq-stock-pool/README.md`。

## Strategy 与 Phase 32 Backtest（2026-08-17 至 2026-08-20）

Strategy workspace 使用真实 validated version/draft/approval：list 支持 search/filter/mobile；version 为 read-only，展示 validation/export/approval；draft 可编辑、插 template/snippet、validate/save/create version；source 从 artifact snapshot preload，task selector 绑定 ResearchTask。Phase 33 review 又验证保存包含 `import os` 且 static validation 失败的 intermediate draft、soft-supersede delete、两 version/一 backtest stats，并确认只使用 `/api/auth/me`/`/api/product/*`。Community editor=`PORT_UX`、history=`REFACTOR`、delete/validation=`REPLACE`。

Phase 32 result-depth review验证 completed job `backtest_7a98404878b14116925020071881ad4e` 的 delete/mobile、每日持仓&收益、日志、策略快照和原有 tabs。旧 result 对新增 fields 显示有界 empty，新 engine 已输出并有 contract tests。

Phase 32 wizard 在 clean volumes 下使用 task、validated `MomentumEvidence · 6a6b6c1d`、approved approval 和 matching `artifact_a5b318425` signal snapshot：options 只列 matching snapshot，execution params read-only；`POST /api/product/backtests` 创建 `backtest_4f64f70c81c146c296874da762cb5d7a`，run 后 completed、0% return/drawdown，八 tabs 可用。Network 为 options/snapshots/backtests/job Product routes。此项关闭 D-0001；当时 D-0002 留给 producer ADR。

## Phase 35 Paper Trading（2026-08-22）

在 isolated six-service Compose、desktop/mobile、durable `ci-admin` 下，真实 golden flow 创建 Stock Pool/Paper account、buy、settle、保存 notional risk limit、查看 order audit、export 并 import 为新 ID。六 tabs 展示 overview、T+1 partitions、order/fill、ledger、immutable snapshots、risk/migration。Settled account 为 cash ¥98,995、equity ¥100,045、market value ¥1,050、100 total/100 sellable/0 locked、20240103 mark ¥10.50。Order detail 展示 frozen snapshot、`filled`、passed risk、provenance/events。Desktop/mobile actions 可达，console clean，所有 23 XHR/fetch 为 same-origin Product routes。Checklist：`docs/evidence/phase-35/COMMUNITY_FEATURE_CHECKLIST.md`。
