import { expect, test } from "@playwright/test";

test("login page requires a product token", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "BeyondQuant Next" })).toBeVisible();
  await page.getByRole("button", { name: "进入" }).click();
  await expect(page.getByText("请输入产品访问令牌")).toBeVisible();
});

test("authenticated dashboard shows resource cards", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("byq-product-token", "product-test-token");
  });
  await page.route("**/api/product/dashboard", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ok", resources: { backend: "ok", data: "not_loaded", migration: "not_started" } }),
    }),
  );
  await page.goto("/");
  await expect(page.getByText("backend")).toBeVisible();
});

test("agent workbench renders a normalized BYQ workflow surface", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("byq-product-token", "product-test-token");
  });
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
  await page.goto("/agent");
  await expect(page.getByRole("heading", { name: "研究对话" })).toBeVisible();
  await expect(page.getByText("session.ready")).toBeVisible();
});

test("quant workspace renders factor, strategy, and backtest tabs", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("byq-product-token", "product-test-token");
  });
  await page.goto("/quant");
  await expect(page.getByRole("heading", { name: "量化工作台" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Factor" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Strategy" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Backtest" })).toBeVisible();
});

test("settings page renders masked platform status", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("byq-product-token", "product-test-token");
  });
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
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "用户与平台设置" })).toBeVisible();
  await page.getByRole("button", { name: "Data" }).click();
  await expect(page.getByText("Provider: tushare")).toBeVisible();
});

test("paper trading and stock pool pages render", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("byq-product-token", "product-test-token");
  });
  await page.goto("/paper-trading");
  await expect(page.getByRole("heading", { name: "模拟交易" })).toBeVisible();
  await page.goto("/stock-pool");
  await expect(page.getByRole("heading", { name: "股票池" })).toBeVisible();
});

test("operations page renders safe status projection", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("byq-product-token", "product-test-token");
  });
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
  await page.goto("/operations");
  await expect(page.getByRole("heading", { name: "Operations 状态" })).toBeVisible();
  await expect(page.getByText("runtime-adapter")).toBeVisible();
});

test("golden journey covers login, dashboard, agent, quant, settings, and operations", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("byq-product-token", "product-test-token");
  });
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

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "首页" })).toBeVisible();
  await page.goto("/agent");
  await expect(page.getByRole("heading", { name: "研究对话" })).toBeVisible();
  await page.goto("/quant");
  await expect(page.getByRole("heading", { name: "量化工作台" })).toBeVisible();
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "用户与平台设置" })).toBeVisible();
  await page.goto("/operations");
  await expect(page.getByRole("heading", { name: "Operations 状态" })).toBeVisible();
});
