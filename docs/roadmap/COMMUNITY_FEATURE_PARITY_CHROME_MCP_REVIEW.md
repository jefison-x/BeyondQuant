# Community Feature Parity Chrome MCP Review

This file records the Phase 8 browser review performed through Chrome MCP
against the rebuilt local BeyondQuant topology. It is not a release approval;
the human merge gate remains the final product acceptance point.

## Review conditions

- Date: 2026-08-16 Asia/Shanghai
- Reviewer: Codex Engineering Plane
- Chrome MCP server: `http://127.0.0.1:12306/mcp`
- Topology: `docker compose up -d frontend gateway backend` after rebuilding
  those images from `main` at `6b9afd9`
- Browser origin: `http://127.0.0.1:80`
- Authenticated principal: `admin` / role `admin`

## Method

Chrome MCP tools were used to open the login page, fill the durable
username/password form, and perform client-side navigation through the
authenticated Product shell. For each route, `chrome_get_web_content` captured
the rendered text through the real Product API boundary. No raw MCP, DSH,
Backend-internal, PostgreSQL, Redis, or provider URL was opened by the browser.

## Observed pages

| Route | Rendered evidence |
|---|---|
| `/login` | Username/password form; three interactive controls: 用户名, 密码, 进入 |
| `/` | Dashboard shows Backend ok, provider tushare, migration not_started, runtime runtime-adapter, storage ready, Product Health ok, model provider not_configured, pending approvals 0, WorkflowTrace/Audit configured |
| `/agent` | 小巴投研 workbench renders session/history, 研究对话, WorkflowTrace, 思考步骤, 审批收件箱, 回测上下文, 研究资产 empty states |
| `/stock-pool` | Stock Pool workspace renders create form (Symbol, 股票池名称, 成分股) and empty 股票池列表 |
| `/strategy` | Strategy workspace renders 策略版本 and 策略详情 empty states; artifact kind `strategy_version` |
| `/backtest` | Backtest task center renders loading/empty state without raw backend exposure |
| `/paper-trading` | Paper trading workspace renders 模拟账户 create surface and empty account list |
| `/assets` | Assets page renders strategy/pool/backtest/paper-account counts and empty lists; export/import actions visible |
| `/models` | Models page renders masked provider status: provider deepseek, configured false, 密钥展示 已掩码，仅可写入, no model list |
| `/agent-settings` | Agent policy page renders platform policy defaults and empty approval history |
| `/profile` | Profile page renders nickname/preferences/default-prompt form with durable profile values |
| `/research-center` | Research/Approval Center renders research assets and approval inbox empty/entity lookup |
| `/data-center` | Data Center renders Provider tushare, Migration not_started, Quality not_audited, no migrated datasets |
| `/system-status` | System status renders Provider tushare, Migration not_started, Backend ok |
| `/operations` | Operations renders Backend ok, Runtime runtime-adapter, Storage ready, Migration not_started, WorkflowTrace/Audit configured |
| `/admin/database` | Admin database section renders Backend ok, Storage ready, Migration not_started |

## Boundary checks

- The browser consumed Product API routes only; no `/mcp`, `/v1/*` Backend,
  DSH runtime, PostgreSQL, Redis, or provider endpoint appeared in the
  observed rendered content.
- Model credentials are returned as masked/write-only status; no token or
  secret value appeared in the model settings page.
- Durable session survived page refresh and client-side navigation without a
  Product Token in the browser form.

## Known remaining depth

The reviewed release candidate still shows empty states for research/backtest/
pool/paper data when no owner-scoped records exist, and some advanced editors
remain future hardening. These are recorded as `REDESIGNED_PASS` rather than
complete product depth.

## Backtest result workspace review (2026-08-17)

- Browser method: Chrome DevTools MCP (`chrome-devtools-mcp`, stdio, headed
  mode, viewport 1440x900)
- Topology: local `beyondquant` compose rebuilt from `main` at `5af1668`,
  including the merged Backtest result workspace (PR #52)
- Browser origin: `http://127.0.0.1`
- Authenticated principal: `chromeuser` / role `admin`

Observed at `/backtest` with a real completed owner-scoped job
(`backtest_6346a4d5cfae4e818df0e5b22e6744fd`, `completed`, total return
0.67%, max drawdown 0.00%, trade count 3, final value 201,336.64):

- List pane renders search by Job ID, status filter, selection checkboxes,
  per-row 收益/回撤/创建时间, run/cancel actions, 对比所选任务, and 刷新.
- Detail pane renders real metrics: Total Return, Max Drawdown, Trade Count,
  Blocked Trades, Final Value, Status.
- Tabs render: 权益曲线 (real equity data), 交易明细 (3 trade rows with
  date/symbol/side/quantity/price/commission/tax/realized PnL), 拦截明细,
  公司行动, and 输入清单 / Preflight (full frozen input manifest with
  strategy/approval ids, universe fingerprint, bars, signals, execution).
- No raw MCP/DSH/Backend/storage/provider URL or secret appeared in the
  rendered page; the page consumed Product API routes only.

## Data Center review (2026-08-17)

- Browser method: Chrome DevTools MCP (headed, viewport 1440x900)
- Topology: local `beyondquant` compose with the Data Center branch images
- Browser origin: `http://127.0.0.1`
- Authenticated principal: `chromeuser` / role `admin`

Observed at `/data-center`:

- Stats strip renders Provider (tushare), Migration (not_started), Quality
  (not_audited), 数据源状态 (未配置, derived from masked provider capability),
  and 同步状态 (not_started).
- 已迁移数据集 renders an honest empty state; no dataset is fabricated.
- No token, credential, or raw MCP/DSH/Backend/storage/provider URL appeared
  in the rendered page; the page consumed Product API routes only.

## Agent Policy workspace review (2026-08-17)

- Browser method: Chrome DevTools MCP (headed, viewport 1440x900)
- Topology: local `beyondquant` compose with the My Space agent-policy branch
  images
- Browser origin: `http://127.0.0.1`
- Authenticated principal: `chromeuser` / role `admin`

Observed at `/agent-settings`:

- 我的审批偏好 renders platform defaults (人工审批, limits) and the real
  pending approval count.
- 个人审批偏好 card renders editable switches (自动审批/暂停), 无匹配规则
  select (manual/auto_approve/auto_deny), and execution/failure limits, with a
  保存 button; saving persists the owner-scoped personal policy through the
  Product API.
- 我的审批历史 renders the real pending `byq_backtest_run` approval with
  decision metadata.
- No raw MCP/DSH/Backend/storage/provider URL or secret appeared in the
  rendered page; the page consumed Product API routes only.

## Agent workbench review (2026-08-17)

- Browser method: Chrome DevTools MCP (headed, viewport 1440x900)
- Topology: local `beyondquant` compose with the Agent workbench product-depth
  branch images
- Browser origin: `http://127.0.0.1`
- Authenticated principal: `chromeuser` / role `admin`

Observed at `/agent` with a live session and a real pending approval fixture:

- Session list is selectable (click to switch and stream events); 新建 creates
  a session, and 历史会话 shows it in the sidebar.
- Conversation composer (输入研究问题...) with 发送, plus 恢复/取消 actions.
- WorkflowTrace renders the real `session.ready` event from
  `runtime-adapter`; 思考步骤 panel and event timeline are present.
- 审批收件箱 renders a pending `byq_backtest_run` approval with 通过/拒绝
  decision buttons; attempting a self-decision is correctly rejected by the
  domain self-approval invariant.
- 回测上下文 and 研究资产 render real owner-scoped lists (1 backtest,
  4 artifacts).
- No raw MCP/DSH/Backend/storage/provider URL or secret appeared in the
  rendered page; the page consumed Product API routes only.

## Paper Trading workspace review (2026-08-17)

- Browser method: Chrome DevTools MCP (headed, viewport 1440x900)
- Topology: local `beyondquant` compose with the Paper Trading product-depth
  branch images
- Browser origin: `http://127.0.0.1`
- Authenticated principal: `chromeuser` / role `admin`

Observed at `/paper-trading`:

- Account cards render name/id/cash/status and switch selection; creating a
  simulation account through the browser form works end-to-end.
- Order form accepts Stock Pool ID, symbol, side, quantity, price, trade date;
  submitting a buy order through the Product API produced a real fill.
- Tabs render 总览 (cash/positions/orders/fills), 持仓 (000001.SZ, 100,
  20240102), 订单, 成交, and 资金流水 (20240102, 000001.SZ, buy, 100,
  cash_delta -1005, fees 5, realized 0).
- No raw MCP/DSH/Backend/storage/provider URL or secret appeared in the
  rendered page; the page consumed Product API routes only.

This review also exposed and fixed a Product API gap: paper order/positions/
orders/fills proxies did not forward trusted owner headers, so browser writes
and reads failed owner-scoped backend checks. The proxies now forward the
headers and the flow is verified end-to-end.

## Stock Pool Phase 34 review (2026-08-21)

- Browser method: Chrome DevTools MCP with system Google Chrome; desktop
  1440x900 and mobile 390x844.
- Topology: isolated Compose stack built from the Phase 34 worktree.
- Browser origin: ephemeral loopback frontend; authenticated durable principal
  `ci-admin`.
- Evidence index: [`../evidence/phase-34/byq-stock-pool/README.md`](../evidence/phase-34/byq-stock-pool/README.md).

Observed at `/stock-pool` through the real Product API:

- Created a weighted custom pool, rejected an invalid 0.8 total with HTTP 422,
  then persisted a three-member v2 snapshot.
- Read v1 from the immutable history dialog with stable fingerprint while v2
  remained current.
- Persisted active/inactive/active lifecycle transitions.
- Resolved a 2024-01-15 index request to the 2024-01-02 snapshot, not the later
  2024-02-01 snapshot, and displayed complete Tushare/unit/normalization
  provenance.
- Desktop table and mobile cards rendered the same persisted catalog. After a
  clean authenticated reload, Chrome reported no console warnings/errors.
- Every browser request was same-origin and used `/api/auth/*` or
  `/api/product/*`; no Backend, MCP, DSH, PostgreSQL, or provider call escaped
  the Gateway boundary.

The review exposed and fixed two integration defects: the real E2E assertion
had not followed the new Members tab, and Gateway mutations collapsed Backend
422 validation into 503. The test now opens the tab and the Gateway preserves
bounded domain errors with regression coverage.

## Strategy workspace review (2026-08-17)

- Browser method: Chrome DevTools MCP (`chrome-devtools-mcp`, stdio, headed
  mode, viewport 1440x900)
- Topology: local `beyondquant` compose with the Strategy product-depth
  branch frontend/gateway images
- Browser origin: `http://127.0.0.1`
- Authenticated principal: `chromeuser` / role `admin`

Observed at `/strategy` with real owner-scoped artifacts (a validated
`strategy_version`, its source `strategy_draft`, and an approved
`strategy_approval`):

- List pane renders search, 全部/草稿/版本 radio filters, per-row
  Artifact ID/类型/状态/创建时间, and mobile cards.
- Selecting a version shows a read-only editor (版本只读), the immutable
  version detail with validation evidence, 导出版本, and a real approval
  banner: 审批状态 已批准 / 已授权执行.
- Selecting a draft enables the editor (草稿可编辑), template select,
  插入模板 / 插入信号片段, 验证并保存草稿, and 创建不可变版本.
- The editor preloads the draft script from the artifact snapshot, and the
  task selector binds new drafts to an existing ResearchTask.
- No raw MCP/DSH/Backend/storage/provider URL or secret appeared in the
  rendered page; the page consumed Product API routes only.

## Phase 32 backtest depth review (2026-08-18)

- Browser method: Chrome DevTools MCP (`chrome-devtools-mcp`, headless,
  viewport 1440x900, isolated profile).
- Topology: local `beyondquant` compose rebuilt with `codex/phase-32-backtest-depth`
  backend/gateway/frontend images.
- Browser origin: `http://127.0.0.1`
- Authenticated principal: `admin`

Observed at `/backtest` with an existing completed owner-scoped job
(`backtest_7a98404878b14116925020071881ad4e`):

- List pane shows a per-row 删除 action on completed jobs (desktop table) and
  the same action on mobile cards.
- Detail tabs now include 每日持仓&收益, 日志输出, and 策略快照 in addition
  to the existing 权益曲线/交易明细/拦截明细/公司行动/输入清单 tabs.
- 策略快照 renders real strategy-version and approval artifact ids plus the
  full frozen input manifest (bars/signals/universe/execution).
- 每日持仓&收益 and 日志输出 render their table headers and bounded empty
  states for this pre-upgrade result; the engine now emits those fields for
  new runs and backend contract tests assert them.

Known remaining: result-object GC after job deletion is a follow-up slice.

## Phase 32 create wizard review (2026-08-18)

- Browser method: Chrome DevTools MCP, viewport 1440x900, isolated profile.
- Topology: local `phase-32-create-wizard` compose rebuilt from the
  `codex/phase-32-create-wizard` worktree (ADR-0017 accepted) with clean
  volumes; admin principal.
- Seed data: one research task with a validated `strategy_version`
  (`MomentumEvidence · 6a6b6c1d`), an approved `strategy_approval`, and one
  validated `signal_snapshot` artifact (`artifact_a5b318425` produced by
  `evidence-fixture`), created through the Backend keyless import path.

Observed at `/backtest` (authenticated as `admin`):

- 新建回测 button opens the "新建回测（Phase 32）" wizard.
- 已批准策略版本 select lists `MomentumEvidence · 6a6b6c1d` (from
  `GET /backtests/options`), confirming version + approval + task aggregation.
- Selecting the strategy enables 信号快照 select, which lists only snapshots
  whose `strategy.strategy_version_artifact_id` matches the chosen version
  (`artifact_a5b318425 · evidence-fixture`).
- Selecting the snapshot renders the frozen execution parameters read-only
  (初始资金 2000 / 手续费率 0 / 印花税率 0 / 整手 100).
- 创建回测 submits `POST /api/product/backtests` with
  `signal_snapshot_artifact_id`; the job appears as `queued`
  (`backtest_4f64f70c81c146c296874da762cb5d7a`).
- Running the job transitions it to `completed` with 收益 0.00% and
  回撤 0.00%; all detail tabs (权益曲线/交易明细/拦截明细/公司行动/
  每日持仓&收益/日志输出/策略快照/输入清单) are available.

Network evidence: `GET /backtests/options [200]`,
`GET /signal-snapshots [200]`, `POST /backtests [202]`,
`GET /backtests [200]`, `GET /backtests/{job_id} [200]`.

This closes D-0001 (create wizard); the end-to-end strategy-to-backtest
journey (signal producer) remains D-0002 pending a producer ADR.

## Phase 33 strategy workspace depth review (2026-08-20)

- Browser method: Chrome DevTools MCP (`chrome-devtools-mcp` 1.7.0, headless,
  viewport 1440x900, isolated profile).
- Topology: local `phase-33-strategy` compose rebuilt from
  `codex/phase-33-strategy` (postgres/backend/mcp/runtime-adapter/gateway/
  frontend all healthy); browser origin `http://127.0.0.1`.
- Authenticated principal: `admin` (durable username/password login, no
  Product Token).
- Seed data (Backend keyless import path): one research task with two
  validated `strategy_version` artifacts for `MomentumEvidence`, an approved
  `strategy_approval`, one completed backtest job against version v1, and one
  tolerant intermediate draft that fails static validation.

Observed at `/strategy`:

- Login used the real username/password form (用户名/密码/进入) and the durable
  session reached the strategy workspace.
- List pane renders the real owner-scoped artifacts (types 草稿/版本, status,
  created time, filters 全部/草稿/版本, search).
- Selecting a draft enables the editor (草稿可编辑) and the 保存草稿/删除草稿
  buttons.
- 保存草稿 persisted an intermediate script that fails static validation
  (`import os`); toast 草稿已保存 appeared, the new `strategy_draft` artifact
  appeared at the top of the list, and the workspace re-selected the saved
  draft so it stays editable.
- 删除草稿 soft-superseded the draft; toast 草稿已删除 appeared and the list
  refreshed.
- Selecting a version enters read-only mode (版本只读) and the detail pane
  renders real statistics: 回测任务数 1, 版本数 2, 策略 ID MomentumEvidence,
  plus the 版本历史 table with both immutable version rows
  (artifact/version_id/status/created time) and the full version JSON
  including `version_id`, `source_fingerprint`, `export`, and `lineage`.
- The version-history and backtest-count projections were fetched through
  `/api/product/strategies/MomentumEvidence/versions` and
  `/api/product/strategies/MomentumEvidence/backtest-count`; Product API
  returned 2 versions and 1 backtest job (v1).
- Network boundary: the strategy page consumed only `/api/auth/me` and
  `/api/product/*` routes (strategies, research tasks/artifacts, settings/
  status, versions, backtest-count, entity detail). No `/mcp`, `/v1/*`
  Backend, DSH, PostgreSQL, Redis, Tushare, or provider URL appeared.
- Screenshots were captured for login home, strategy list, draft save, draft
  delete, and version-history/stats views.

Community comparison: `StrategyView.vue` (1008 lines) was inspected. The
editor/templates/snippets map to `PORT_UX`; version history is `REFACTOR`
(BYQ immutable artifact versions); delete is `REPLACE` (BYQ soft-supersede of
immutable `strategy_draft` artifacts instead of Community row deletion);
domain validation remains `REPLACE` (BYQ static validator, execution deferred
to a future worker).
