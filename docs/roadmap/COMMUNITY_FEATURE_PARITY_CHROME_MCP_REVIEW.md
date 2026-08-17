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

## Stock Pool workspace review (2026-08-17)

- Browser method: Chrome DevTools MCP (headed, viewport 1440x900)
- Topology: local `beyondquant` compose with the Stock Pool product-depth
  branch images
- Browser origin: `http://127.0.0.1`
- Authenticated principal: `chromeuser` / role `admin`

Observed at `/stock-pool`:

- Create form renders 股票池名称, 类型 radios (自建/指数/动态), 说明,
  成分股, and optional 权重 JSON.
- A pool was created through the real browser form and the fixed Product API
  proxy: 沪深300增强 / 指数 / 2 只成分 / v1 / 浏览器审查指数池.
- List pane renders name/type/count/version/description/updated-time with
  全部/自建/指数/动态 filters, search, and refresh.
- Detail pane renders the immutable snapshot: symbols 000001.SZ + 600000.SH
  and weights {"000001.SZ": 0.6, "600000.SH": 0.4}.
- No raw MCP/DSH/Backend/storage/provider URL or secret appeared in the
  rendered page; the page consumed Product API routes only.

This review also exposed and fixed a real defect: the Product API wraps
backtest jobs in `{"job": ...}` and the frontend client did not unwrap it,
so job detail never loaded. The fix unwraps `job` in the quant API client and
adds unit/e2e coverage.

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
