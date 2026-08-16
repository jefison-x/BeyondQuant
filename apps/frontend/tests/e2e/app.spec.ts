import { expect, test, type Page } from "@playwright/test";

async function login(page: Page) {
  await page.route("**/api/auth/login", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ user: { subject: "testuser" }, session_id: "session-test" }),
      headers: { "set-cookie": "byq_session=session-test; Path=/; HttpOnly; SameSite=Lax" },
    }),
  );
  await page.route("**/api/auth/me", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ subject: "testuser" }) }),
  );
  await page.goto("/login");
  await page.getByLabel("用户名").fill("testuser");
  await page.getByLabel("密码").fill("password123");
  await page.getByRole("button", { name: "进入" }).click();
  await expect(page).toHaveURL(/\/$/);
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
  await expect(page.getByText("backend")).toBeVisible();
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
  await page.getByRole("link", { name: "研究工作台" }).click();
  await expect(page.getByRole("heading", { name: "研究对话" })).toBeVisible();
  await expect(page.getByText("session.ready")).toBeVisible();
});

test("quant workspace renders factor, strategy, and backtest tabs", async ({ page }) => {
  await login(page);
  await page.getByRole("link", { name: "量化工作台" }).click();
  await expect(page.getByRole("heading", { name: "量化工作台" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Factor" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Strategy" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Backtest" })).toBeVisible();
});

test("settings page renders masked platform status", async ({ page }) => {
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
  await login(page);
  await page.getByRole("link", { name: "设置" }).click();
  await expect(page.getByRole("heading", { name: "用户与平台设置" })).toBeVisible();
  await page.getByRole("button", { name: "Data" }).click();
  await expect(page.getByText("Provider: tushare")).toBeVisible();
});

test("paper trading and stock pool pages render", async ({ page }) => {
  await login(page);
  await page.getByRole("link", { name: "模拟交易" }).click();
  await expect(page.getByRole("heading", { name: "模拟交易" })).toBeVisible();
  await page.getByRole("link", { name: "股票池" }).click();
  await expect(page.getByRole("heading", { name: "股票池" })).toBeVisible();
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
  await page.getByRole("link", { name: "Operations" }).click();
  await expect(page.getByRole("heading", { name: "Operations 状态" })).toBeVisible();
  await expect(page.getByText("runtime-adapter")).toBeVisible();
});

test("golden journey covers login, dashboard, agent, quant, settings, and operations", async ({ page }) => {
  await page.route("**/api/product/dashboard", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ok", resources: { backend: "ok", data: "not_loaded", migration: "not_started" } }),
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
  await expect(page.getByRole("heading", { name: "系统状态" })).toBeVisible();
  await page.getByRole("link", { name: "研究工作台" }).click();
  await expect(page.getByRole("heading", { name: "研究对话" })).toBeVisible();
  await page.getByRole("link", { name: "量化工作台" }).click();
  await expect(page.getByRole("heading", { name: "量化工作台" })).toBeVisible();
  await page.getByRole("link", { name: "设置" }).click();
  await expect(page.getByRole("heading", { name: "用户与平台设置" })).toBeVisible();
  await page.getByRole("link", { name: "Operations" }).click();
  await expect(page.getByRole("heading", { name: "Operations 状态" })).toBeVisible();
});
