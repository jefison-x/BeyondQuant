import { expect, test, type Page } from "@playwright/test";

async function login(page: Page) {
  let meAuthenticated = false;
  await page.route("**/api/auth/login", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ user: { subject: "testuser" }, session_id: "session-test" }),
      headers: { "set-cookie": "byq_session=session-test; Path=/; HttpOnly; SameSite=Lax" },
    }),
  );
  await page.route("**/api/auth/me", (route) =>
    meAuthenticated
      ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ subject: "testuser" }) })
      : (meAuthenticated = true, route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ error: { message: "unauthenticated" } }) })),
  );
  await page.goto("/login");
  await page.getByLabel("用户名").fill("testuser");
  await page.getByLabel("密码").fill("password123");
  await page.getByRole("button", { name: "进入" }).click();
  await expect(page).toHaveURL(/\/$/);
}

async function loginAsAdmin(page: Page) {
  let meAuthenticated = false;
  await page.route("**/api/auth/login", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ user: { subject: "admin", role: "admin" }, session_id: "session-admin" }),
      headers: { "set-cookie": "byq_session=session-admin; Path=/; HttpOnly; SameSite=Lax" },
    }),
  );
  await page.route("**/api/auth/me", (route) =>
    meAuthenticated
      ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ subject: "admin", role: "admin" }) })
      : (meAuthenticated = true, route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ error: { message: "unauthenticated" } }) })),
  );
  await page.goto("/login");
  await page.getByLabel("用户名").fill("admin");
  await page.getByLabel("密码").fill("adminpass123");
  await page.getByRole("button", { name: "进入" }).click();
  await expect(page).toHaveURL(/\/$/);
}

function operationsPayload() {
  return {
    schema_version: "operations.v1",
    services: { gateway: "ready", backend: "ready", runtime_adapter: "ready" },
    database: { engine: "postgresql", status: "ready", name: "byq_domain", server_version: "16.9", size_bytes: 5242880, table_count: 30, estimated_rows: 120, domain_counts: [{ resource: "market_bars", count: 80 }], migration: { single_domain_store: "complete", legacy_sqlite_runtime: false } },
    cache: { kind: "postgresql_market_data", status: "ready", row_count: 80, redis: "not_used", groups: [{ data_source: "tushare", asset_type: "stock", symbol_count: 4, row_count: 80, date_min: "2026-01-01", date_max: "2026-08-22" }] },
    sources: { provider: "tushare", credential_metadata: [], configuration_scope: "phase_39", legacy_providers: [], secrets_exposed: false },
    models: { credential_metadata: [{ provider_key: "deepseek", scope: "system", status: "active", count: 1 }], profiles: 2, bindings: 1, secrets_exposed: false },
    agents: { status_groups: [{ role_id: "quant_orchestrator", status: "completed", count: 3 }], recent_runs: [] },
    graphs: { projection: "normalized_agent_runs", recent_runs: [], raw_dsh_events: false },
    access: { principal_groups: [{ role: "admin", status: "active", count: 1 }], agent_audit: [], operations_audit: [] },
    budget: { policy_id: "product-agent", enabled: false, alert_total_tokens: 400000, alert_requests: 48, version: 1, updated_by: "system-bootstrap", updated_at: "2026-08-22T00:00:00Z" },
    runtime: { schema_version: "runtime-operations.v1", runtime: { status: "ready", sdk: "deepseek-harness-sdk==0.1.0rc6", process_ownership: "one-per-active-session" }, sessions: { active: 1, active_prompts: 0, status_counts: { idle: 1 } }, usage: { input_tokens: 100, output_tokens: 20, cache_read_tokens: 30, cache_write_tokens: 0, reasoning_tokens: 10, model_calls: 1, total_tokens: 150, scope: "adapter_process_lifetime", source: "normalized_dsh_token_usage" }, raw_dsh_events: false },
    observability: { workflow_trace: "normalized", audit: "append_only", raw_dsh_events: false },
  };
}

async function mockAdminOps(page: Page) {
  await page.route("**/api/product/operations/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(operationsPayload()),
    }),
  );
  await page.route("**/api/product/data/status", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok", provider: "tushare", migration: "not_started", backend: "ok" }) }),
  );
  await page.route("**/api/product/data-center/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ migration: "not_started", datasets: [], provider: "tushare", quality: "not_audited", provider_status: { configured: true, sync: "not_started" } }),
    }),
  );
  await page.route("**/api/product/settings/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        profile: { configured: true },
        model_provider: { configured: false },
        data_provider: { provider: "tushare", migration: "not_started" },
        storage: { status: "ready" },
        approval_inbox: { pending: 0 },
      }),
    }),
  );
  await page.route("**/api/product/health", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok", service: "byq-gateway" }) }),
  );
  await page.route("**/api/product/admin/users", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ users: [] }) }),
  );
  await page.route("**/api/product/approvals", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ approvals: [] }) }),
  );
}

async function openNav(page: Page, label: string) {
  await page.getByRole("menuitem", { name: label }).click();
}

async function mockResearchLists(page: Page) {
  await page.route("**/api/product/research/artifacts", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ artifacts: [] }),
    }),
  );
  await page.route("**/api/product/approvals", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ approvals: [] }),
    }),
  );
  await page.route("**/api/product/strategies", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ strategies: [] }) }),
  );
  await page.route("**/api/product/backtests", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ backtests: [] }) }),
  );
}

test("login page requires username and password", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "BeyondQuant Next" })).toBeVisible();
  await page.getByRole("button", { name: "进入" }).click();
  await expect(page.getByText("请输入用户名和密码")).toBeVisible();
});

test("authenticated dashboard shows resource cards", async ({ page }) => {
  await page.route("**/api/product/dashboard", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ok", resources: { backend: "ok", data: "not_loaded", migration: "not_started" } }),
    }),
  );
  await login(page);
  await expect(page.getByText("Backend", { exact: true }).first()).toBeVisible();
});

test("agent workbench renders a normalized BYQ workflow surface", async ({ page }) => {
  await page.route("**/v1/agent/sessions", (route) => {
    const session = { session_id: "session-1", trace_id: "trace-1", status: "ready" };
    return route.fulfill({
      status: route.request().method() === "POST" ? 201 : 200,
      contentType: "application/json",
      body: JSON.stringify(route.request().method() === "POST" ? session : { sessions: [session] }),
    });
  });
  await page.route("**/v1/workflows/session-1/events", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: 'data: {"trace_id":"trace-1","session_id":"session-1","sequence":1,"timestamp":"2026-08-22T00:00:00Z","kind":"agent.activity","source":"runtime-adapter","payload":{"schema_version":"workflow-activity.v1","activity_id":"activity_11111111111111111111111111111111","phase":"understand","state":"started","label":"理解请求"}}\n\n',
    }),
  );
  await page.route("**/api/product/approvals", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ approvals: [{ approval_id: "agent_approval_1", action: "run_backtest", status: "pending" }] }),
    }),
  );
  await page.route("**/api/product/approvals/agent_approval_1/decision", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ approval: { approval_id: "agent_approval_1", status: "approved" } }),
    }),
  );
  await login(page);
  await openNav(page, "小巴投研");
  await expect(page.getByRole("heading", { name: "小巴投研" })).toBeVisible();
  await expect(page.getByText("研究对话")).toBeVisible();
  await expect(page.getByText("BYQ 规范化工作流")).toBeVisible();
  await expect(page.getByText("理解请求")).toBeVisible();
  await expect(page.getByRole("button", { name: "通过" })).toBeVisible();
});

test("strategy workspace renders strategy version list and detail", async ({ page }) => {
  await mockResearchLists(page);
  await page.route("**/api/product/research/tasks", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ tasks: [{ task_id: "task_1" }] }) }),
  );
  await page.route("**/api/product/strategies", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        strategies: [
          {
            artifact_id: "artifact_draft_1",
            kind: "strategy_draft",
            status: "draft",
            content: { snapshot: { strategy_id: "MomentumStrategy", script: "class CustomStrategy:\n    def generate_signals(self, data, parameters=None):\n        return {}" } },
            created_at: "2026-08-16T00:00:00+00:00",
          },
          {
            artifact_id: "artifact_version_1",
            kind: "strategy_version",
            status: "validated",
            content: { snapshot: { strategy_id: "MomentumStrategy", script: "class CustomStrategy:\n    def generate_signals(self, data, parameters=None):\n        return {}" } },
            created_at: "2026-08-16T00:00:00+00:00",
          },
          {
            artifact_id: "artifact_approval_1",
            kind: "strategy_approval",
            status: "validated",
            content: { strategy_version_artifact_id: "artifact_version_1", decision: "approved", execution_authorized: true },
            created_at: "2026-08-16T00:00:00+00:00",
          },
        ],
      }),
    }),
  );
  await page.route("**/api/product/research/artifacts/artifact_version_1", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ artifact_id: "artifact_version_1", kind: "strategy_version" }) }),
  );
  await page.route("**/api/product/research/artifacts", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        artifacts: [
          {
            artifact_id: "artifact_approval_1",
            kind: "strategy_approval",
            status: "validated",
            content: { strategy_version_artifact_id: "artifact_version_1", decision: "approved", execution_authorized: true },
            created_at: "2026-08-16T00:00:00+00:00",
          },
        ],
      }),
    }),
  );
  await login(page);
  await openNav(page, "策略管理");
  await expect(page.getByRole("heading", { name: "策略管理" })).toBeVisible();
  await expect(page.getByText("策略编辑器", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "插入模板" })).toBeVisible();
  await expect(page.getByRole("button", { name: "创建不可变版本" })).toBeVisible();
  await expect(page.getByText("已批准")).toBeVisible();
});

test("backtest workspace renders backtest result list", async ({ page }) => {
  await mockResearchLists(page);
  await page.route("**/api/product/backtests", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        backtests: [{ job_id: "backtest_1", status: "completed", summary: { total_return: 0.05, max_drawdown: 0.1, trade_count: 2 }, input_manifest: { execution: {} }, created_at: "2026-08-16T00:00:00+00:00" }],
      }),
    }),
  );
  await page.route("**/api/product/backtests/backtest_1", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ job: { job_id: "backtest_1", status: "completed", summary: { total_return: 0.05, max_drawdown: 0.1, trade_count: 2 }, input_manifest: { execution: { initial_capital: 100000 } } } }),
    }),
  );
  await page.route("**/api/product/backtests/backtest_1/result", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        job_id: "backtest_1",
        result: {
          total_return: 0.05,
          max_drawdown: 0.1,
          trade_count: 1,
          equity_curve: [{ trade_date: "2026-01-05", equity: 100000, cash: 100000, positions_count: 0 }],
          trades: [{ timestamp: "2026-01-05", symbol: "000001.SZ", order_type: "buy", quantity: 100, price: 10, commission: 0, tax: 0, realized_pnl: null }],
          blocked_trades: [],
          corporate_action_events: [],
        },
      }),
    }),
  );
  await login(page);
  await openNav(page, "回测管理");
  await expect(page.getByRole("heading", { name: "回测管理" })).toBeVisible();
  await expect(page.getByText("回测结果", { exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: "权益曲线" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "交易明细" })).toBeVisible();
});

test("my space pages render profile, models, assets, and agent policy", async ({ page }) => {
  await page.route("**/api/product/profile", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ profile: { subject: "testuser", display_name: "老李", preferences: "低波动", default_prompt: "先给结论", role: "user", status: "active" } }),
    }),
  );
  await page.route("**/api/product/settings/models", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ provider: "deepseek", configured: false, models: [], agents: [], credential_items: [], profiles: [], bindings: [], audit: [], encryption: { configured: true, status: "ready" }, credentials: { masked: true, write_only: true } }),
    }),
  );
  await page.route("**/api/product/settings/assets", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ strategies: [], backtests: [], pools: [], paper_accounts: [], summary: { strategies: 0, backtests: 0, pools: 0, paper_accounts: 0 } }),
    }),
  );
  await page.route("**/api/product/settings/agent-policy", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        platform_policy: { automation_enabled: false, paused: false, default_decision_mode: "manual", max_auto_executions_per_hour: 20, max_auto_failures_per_hour: 3 },
        personal_policy: { automation_enabled: false, paused: false, default_decision_mode: "manual", max_auto_executions_per_hour: 20, max_auto_failures_per_hour: 3 },
        rules: [], presets: [{ preset_id: "manual_safe", name: "全部人工确认", description: "安全默认", rules: [] }], audit: [],
        approval_inbox: { pending: 0 },
      }),
    }),
  );
  await page.route("**/api/product/approvals", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ approvals: [] }) }),
  );

  await login(page);
  await openNav(page, "用户资产");
  await expect(page.getByRole("heading", { name: "用户资产" })).toBeVisible();
  await expect(page.getByText("导出资产包")).toBeVisible();

  await openNav(page, "个人模型");
  await expect(page.getByRole("heading", { name: "模型设置" })).toBeVisible();
  await expect(page.getByRole("button", { name: "添加凭据" })).toBeVisible();

  await openNav(page, "智能体策略");
  await expect(page.getByRole("heading", { name: "智能体策略" })).toBeVisible();
  await expect(page.getByRole("button", { name: "保存" })).toBeVisible();
  await expect(page.getByRole("button", { name: "新建规则" })).toBeVisible();

  await openNav(page, "个人设置");
  await expect(page.getByRole("heading", { name: "个人设置" })).toBeVisible();
  await expect(page.getByLabel("昵称")).toHaveValue("老李");
});

test("paper trading and stock pool pages render", async ({ page }) => {
  await login(page);
  await page.route("**/api/product/paper/pools", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ pools: [{
      pool_id: "stock_pool_1", name: "沪深300", pool_type: "index", description: "指数池",
      symbols: ["000001.SZ", "600000.SH"], weights: { "000001.SZ": 0.6 }, version: "v1",
      status: "active", created_at: "2026-08-16T00:00:00+00:00",
    }] }) }),
  );
  await page.route("**/api/product/paper/accounts", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ accounts: [{ account_id: "paper_account_1", name: "sim", cash: 100000, status: "active" }] }),
    }),
  );
  await page.route("**/api/product/paper/accounts/paper_account_1/positions", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ positions: [] }) }),
  );
  await page.route("**/api/product/paper/accounts/paper_account_1/orders", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ orders: [] }) }),
  );
  await page.route("**/api/product/paper/accounts/paper_account_1/fills", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ fills: [] }) }),
  );
  await page.route("**/api/product/paper/accounts/paper_account_1/ledger", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ledger: [] }) }),
  );
  await page.route("**/api/product/paper/accounts/paper_account_1/snapshots", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ snapshots: [] }) }),
  );
  await page.route("**/api/product/paper/accounts/paper_account_1/controls", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ controls: { kill_switch_engaged: false, max_order_notional: null, version: 1 } }) }),
  );
  await page.route("**/api/product/paper/accounts/paper_account_1", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ account: { account_id: "paper_account_1", name: "sim", cash: 100000, equity: 100000, version: 1, status: "active" } }) }),
  );
  await openNav(page, "模拟操盘");
  await expect(page.getByRole("heading", { name: "模拟操盘" }).last()).toBeVisible();
  await expect(page.getByText("sim", { exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: "资金流水" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "结算快照" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "风险与迁移" })).toBeVisible();
  await openNav(page, "股票管理");
  await expect(page.getByRole("heading", { name: "股票管理" })).toBeVisible();
  await expect(page.getByRole("radio", { name: "指数" }).first()).toBeVisible();
  await expect(page.getByText("沪深300", { exact: true }).first()).toBeVisible();
});

test("operations page renders safe status projection", async ({ page }) => {
  await page.route("**/api/product/operations/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(operationsPayload()),
    }),
  );
  await loginAsAdmin(page);
  await page.goto("/admin/runtime");
  await expect(page.getByRole("heading", { name: "运行诊断" })).toBeVisible();
  await expect(page.getByText("deepseek-harness-sdk==0.1.0rc6")).toBeVisible();
});

test("admin operations workspace renders database and access sections", async ({ page }) => {
  await mockAdminOps(page);
  await loginAsAdmin(page);
  await page.goto("/admin/database");
  await expect(page.getByRole("heading", { name: "数据库管理" })).toBeVisible();
  await expect(page.getByText("byq_domain")).toBeVisible();

  await page.goto("/admin/access");
  await expect(page.getByRole("heading", { name: "权限与审计" })).toBeVisible();
  await expect(page.getByText("admin · active")).toBeVisible();
});

test("mocked UI navigation covers core product routes", async ({ page }) => {
  await page.route("**/api/product/dashboard", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ok", resources: { backend: "ok", data: "not_loaded", migration: "not_started" } }),
    }),
  );
  await page.route("**/api/product/profile", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ profile: { subject: "testuser", display_name: "老李", preferences: "低波动", default_prompt: "先给结论", role: "user", status: "active" } }),
    }),
  );
  await page.route("**/api/product/operations/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(operationsPayload()),
    }),
  );
  await mockResearchLists(page);

  await login(page);
  await expect(page.getByRole("heading", { name: "工作台" })).toBeVisible();
  await openNav(page, "小巴投研");
  await expect(page.getByRole("heading", { name: "小巴投研" })).toBeVisible();
  await openNav(page, "策略管理");
  await expect(page.getByRole("heading", { name: "策略管理" })).toBeVisible();
  await openNav(page, "个人设置");
  await expect(page.getByRole("heading", { name: "个人设置" })).toBeVisible();
  await openNav(page, "系统状态");
  await expect(page.getByRole("heading", { name: "系统状态" })).toBeVisible();
  await openNav(page, "数据中心");
  await expect(page.getByRole("heading", { name: "数据中心" })).toBeVisible();
  await openNav(page, "研究/审批");
  await expect(page.getByRole("heading", { name: "研究/审批" })).toBeVisible();
});
