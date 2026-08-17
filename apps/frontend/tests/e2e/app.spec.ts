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

async function mockAdminOps(page: Page) {
  await page.route("**/api/product/operations/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        backend: "ok",
        runtime: "runtime-adapter",
        storage: "ready",
        migration: "not_started",
        observability: { workflow_trace: "configured", audit: "configured" },
      }),
    }),
  );
  await page.route("**/api/product/data/status", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok", provider: "tushare", migration: "not_started", backend: "ok" }) }),
  );
  await page.route("**/api/product/data-center/status", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ migration: "not_started", datasets: [], provider: "tushare", quality: "not_audited" }) }),
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
  await page.route("**/v1/agent/sessions", (route) =>
    route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({ session_id: "session-1", trace_id: "trace-1", status: "ready" }),
    }),
  );
  await page.route("**/v1/workflows/session-1/events", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: 'data: {"kind":"session.ready","source":"runtime-adapter"}\n\n',
    }),
  );
  await login(page);
  await openNav(page, "小巴投研");
  await expect(page.getByRole("heading", { name: "小巴投研" })).toBeVisible();
  await expect(page.getByText("研究对话")).toBeVisible();
  await expect(page.getByText("session.ready")).toBeVisible();
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
      body: JSON.stringify({ provider: "deepseek", configured: false, models: [], credentials: { masked: true, write_only: true } }),
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
      body: JSON.stringify({ platform_policy: { automation_enabled: false, paused: false, default_decision_mode: "manual", max_auto_executions_per_hour: 20, max_auto_failures_per_hour: 3 }, approval_inbox: { pending: 0 } }),
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
  await expect(page.getByText("已掩码，仅可写入")).toBeVisible();

  await openNav(page, "智能体策略");
  await expect(page.getByRole("heading", { name: "智能体策略" })).toBeVisible();

  await openNav(page, "个人设置");
  await expect(page.getByRole("heading", { name: "个人设置" })).toBeVisible();
  await expect(page.getByLabel("昵称")).toHaveValue("老李");
});

test("paper trading and stock pool pages render", async ({ page }) => {
  await login(page);
  await openNav(page, "模拟操盘");
  await expect(page.getByRole("heading", { name: "模拟操盘" })).toBeVisible();
  await page.route("**/api/product/paper/pools", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        pools: [
          {
            pool_id: "stock_pool_1",
            name: "沪深300",
            pool_type: "index",
            description: "指数池",
            symbols: ["000001.SZ", "600000.SH"],
            weights: { "000001.SZ": 0.6 },
            version: "v1",
            created_at: "2026-08-16T00:00:00+00:00",
          },
        ],
      }),
    }),
  );
  await openNav(page, "股票管理");
  await expect(page.getByRole("heading", { name: "股票管理" })).toBeVisible();
  await expect(page.getByRole("radio", { name: "指数" }).first()).toBeVisible();
  await expect(page.getByText("沪深300", { exact: true })).toBeVisible();
});

test("operations page renders safe status projection", async ({ page }) => {
  await page.route("**/api/product/operations/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        backend: "ok",
        runtime: "runtime-adapter",
        storage: "ready",
        migration: "not_started",
        observability: { workflow_trace: "configured", audit: "configured" },
      }),
    }),
  );
  await login(page);
  await openNav(page, "系统运维");
  await expect(page.getByRole("heading", { name: "系统运维" })).toBeVisible();
  await expect(page.getByText("runtime-adapter")).toBeVisible();
});

test("admin operations workspace renders database and access sections", async ({ page }) => {
  await mockAdminOps(page);
  await loginAsAdmin(page);
  await page.goto("/admin/database");
  await expect(page.getByRole("heading", { name: "数据库管理" })).toBeVisible();
  await expect(page.getByText("Backend")).toBeVisible();

  await page.goto("/admin/access");
  await expect(page.getByRole("heading", { name: "权限与审计" })).toBeVisible();
  await expect(page.getByText("用户", { exact: true })).toBeVisible();
});

test("golden journey covers login, dashboard, agent, strategy, settings, and operations", async ({ page }) => {
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
      body: JSON.stringify({
        backend: "ok",
        runtime: "runtime-adapter",
        storage: "ready",
        migration: "not_started",
        observability: { workflow_trace: "configured", audit: "configured" },
      }),
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
  await openNav(page, "系统运维");
  await expect(page.getByRole("heading", { name: "系统运维" })).toBeVisible();
  await openNav(page, "数据中心");
  await expect(page.getByRole("heading", { name: "数据中心" })).toBeVisible();
  await openNav(page, "研究/审批");
  await expect(page.getByRole("heading", { name: "研究/审批" })).toBeVisible();
});
