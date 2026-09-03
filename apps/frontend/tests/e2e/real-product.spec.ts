import { expect, test, type Page } from "@playwright/test";

async function openUserDestination(page: Page, label: string) {
  await page.getByTitle(/用户设置/).click();
  await page.getByRole("menuitem", { name: label }).click();
}

test("Phase 90 real feedback preview, submission, moderation and unconfigured publication", phase90FeedbackJourney);

test("real Product API login and Stock Pool create flow", async ({ page, baseURL }) => {
  const adminUsername = process.env.BYQ_E2E_ADMIN_USERNAME;
  const adminPassword = process.env.BYQ_E2E_ADMIN_PASSWORD;
  if (!adminUsername || !adminPassword) {
    throw new Error("BYQ_E2E_ADMIN_USERNAME and BYQ_E2E_ADMIN_PASSWORD are required");
  }
  const origin = new URL(baseURL ?? "http://127.0.0.1:18080").origin;
  const unexpectedOrigins = new Set<string>();
  const serverErrors: string[] = [];

  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.protocol === "http:" || url.protocol === "https:") {
      if (url.origin !== origin) unexpectedOrigins.add(url.origin);
    }
  });
  page.on("response", (response) => {
    if (response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`);
  });

  await page.goto("/login");
  await page.getByLabel("用户名").fill(adminUsername);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "进入" }).click();
  await expect(page).toHaveURL(`${origin}/agent`);
  await expect(page.getByRole("heading", { name: "小巴投研" })).toBeVisible();

  await page.goto("/stock-pool");
  await expect(page.getByRole("heading", { name: "股票管理" })).toBeVisible();
  await page.getByRole("button", { name: "新建股票池" }).click();

  const poolName = `CI股票池-${Date.now()}`;
  await page.getByPlaceholder("Pool name").fill(poolName);
  await page.getByPlaceholder("股票池用途或说明").fill("真实 Product API E2E");
  await page.getByPlaceholder("000001.SZ,600000.SH").fill("000001.SZ,600000.SH");

  const createdResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/product/paper/pools") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "创建股票池" }).click();
  const response = await createdResponse;
  expect(response.status()).toBe(201);
  const created = await response.json() as { pool: { pool_id: string; current_snapshot_id: string } };
  const replaceStatus = await page.evaluate(async (pool) => {
    const result = await fetch(`/api/product/paper/pools/${pool.pool_id}/snapshot`, {
      method: "PUT", credentials: "include", headers: { "content-type": "application/json" },
      body: JSON.stringify({ expected_current_snapshot_id: pool.current_snapshot_id,
        symbols: ["000001.SZ", "300750.SZ"], idempotency_key: crypto.randomUUID() }),
    });
    return result.status;
  }, created.pool);
  expect(replaceStatus).toBe(200);
  await page.goto(`/stock-pool?pool=${created.pool.pool_id}`);
  await expect(page.getByText(poolName, { exact: true }).first()).toBeVisible();
  await expect(page.getByText("current", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "成员与权重" }).click();
  await expect(page.getByText("000001.SZ", { exact: true }).first()).toBeVisible();
  await page.getByRole("tab", { name: "快照历史" }).click();
  await page.getByRole("button", { name: "比较最近两个快照" }).click();
  await expect(page.getByTestId("stock-pool-snapshot-diff")).toContainText("新增");
  const evidenceDir = process.env.BYQ_E2E_EVIDENCE_DIR;
  if (evidenceDir) {
    await page.screenshot({ path: `${evidenceDir}/01-stock-pool-closure-desktop.png`, fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: `${evidenceDir}/02-stock-pool-closure-mobile.png`, fullPage: true });
  }

  expect([...unexpectedOrigins]).toEqual([]);
  expect(serverErrors).toEqual([]);
});

test("Phase 74 real LightGBM training to frozen-signal backtest journey", async ({ page, baseURL }) => {
  test.setTimeout(240_000);
  const username = process.env.BYQ_E2E_ADMIN_USERNAME, password = process.env.BYQ_E2E_ADMIN_PASSWORD;
  if (!username || !password) throw new Error("BYQ_E2E admin credentials are required");
  const origin = new URL(baseURL ?? "http://127.0.0.1:18080").origin;
  const unexpectedOrigins = new Set<string>(), serverErrors: string[] = [];
  page.on("request", request => { const url = new URL(request.url()); if (["http:", "https:"].includes(url.protocol) && url.origin !== origin) unexpectedOrigins.add(url.origin); });
  page.on("response", response => { if (response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`); });
  await page.goto("/login"); await page.getByLabel("用户名").fill(username); await page.getByLabel("密码").fill(password); await page.getByRole("button", { name: "进入" }).click();
  await expect(page).toHaveURL(`${origin}/agent`);
  const poolStatus = await page.evaluate(async () => (await fetch("/api/product/paper/pools", { method: "POST", credentials: "include", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: `Phase 74 ML 冻结池-${Date.now()}`, pool_type: "custom", description: "真实浏览器 LightGBM 闭环", symbols: ["000001.SZ", "600000.SH"] }) })).status);
  expect(poolStatus).toBe(201);
  await page.goto("/model-research");
  await expect(page.getByRole("heading", { name: "模型研究目录与实验进程" })).toBeVisible();
  await page.getByRole("button", { name: "新建模型研究" }).first().click();
  await page.getByTestId("ml-save").click(); await expect(page.getByText("研究定义已冻结，可以进入训练")).toBeVisible();
  await page.getByTestId("ml-train").click(); await page.getByLabel("确认训练范围").getByRole("button", { name: "批准并开始训练" }).click();
  await expect(page.getByTestId("ml-predict")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText("训练结果")).toBeVisible();
  await page.getByTestId("ml-predict").click(); await expect(page.getByTestId("ml-backtest")).toBeVisible({ timeout: 120_000 });
  await page.getByRole("tab", { name: "预测结果" }).click();
  await expect(page.getByRole("columnheader", { name: "排名" })).toBeVisible();
  await page.getByTestId("ml-backtest").click(); await expect(page.getByRole("button", { name: "查看完整回测" })).toBeVisible({ timeout: 120_000 });
  const evidenceDir = process.env.BYQ_E2E_EVIDENCE_DIR;
  if (evidenceDir) { await page.screenshot({ path: `${evidenceDir}/01-lightgbm-desktop.png`, fullPage: true }); await page.setViewportSize({ width: 390, height: 844 }); await page.screenshot({ path: `${evidenceDir}/02-lightgbm-mobile.png`, fullPage: true }); }
  expect([...unexpectedOrigins]).toEqual([]); expect(serverErrors).toEqual([]);
});

test("Phase 86 real HS300 regime experts to routed frozen-signal backtest journey", async ({ page, baseURL }) => {
  test.setTimeout(360_000);
  const username = process.env.BYQ_E2E_ADMIN_USERNAME, password = process.env.BYQ_E2E_ADMIN_PASSWORD;
  if (!username || !password) throw new Error("BYQ_E2E admin credentials are required");
  const origin = new URL(baseURL ?? "http://127.0.0.1:18080").origin;
  const unexpectedOrigins = new Set<string>(), serverErrors: string[] = [];
  page.on("request", request => { const url = new URL(request.url()); if (["http:", "https:"].includes(url.protocol) && url.origin !== origin) unexpectedOrigins.add(url.origin); });
  page.on("response", response => { if (response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`); });
  await page.goto("/login"); await page.getByLabel("用户名").fill(username); await page.getByLabel("密码").fill(password); await page.getByRole("button", { name: "进入" }).click();
  await expect(page).toHaveURL(`${origin}/agent`);
  const poolStatus = await page.evaluate(async () => (await fetch("/api/product/paper/pools", { method: "POST", credentials: "include", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: `Phase 86 状态专家池-${Date.now()}`, pool_type: "custom", description: "真实浏览器沪深300状态专家闭环", symbols: ["000001.SZ", "600000.SH"] }) })).status);
  expect(poolStatus).toBe(201);
  await page.goto("/model-research");
  await expect(page.getByRole("heading", { name: "模型研究目录与实验进程" })).toBeVisible();
  await page.getByRole("button", { name: "新建模型研究" }).first().click();
  const dialog = page.getByRole("dialog", { name: "新建模型研究" });
  await dialog.getByText("市场状态专家", { exact: true }).click();
  await expect(dialog.getByText("沪深300状态专家", { exact: true })).toBeVisible();
  await expect(dialog.getByTestId("ml-expert-risk_on")).toBeVisible();
  await page.getByTestId("ml-save").click();
  await expect(page.getByText("研究定义已冻结，可以进入训练")).toBeVisible();
  await page.getByTestId("ml-train").click();
  await page.getByLabel("确认训练范围").getByRole("button", { name: "批准并开始训练" }).click();
  await expect(page.getByTestId("ml-predict")).toBeVisible({ timeout: 180_000 });
  await expect(page.getByText("市场状态专家路由")).toBeVisible();
  await expect(page.getByText("训练模型").locator("..")).toContainText("3");
  await page.getByTestId("ml-predict").click();
  await expect(page.getByTestId("ml-backtest")).toBeVisible({ timeout: 180_000 });
  await page.getByRole("tab", { name: "预测结果" }).click();
  await expect(page.getByRole("columnheader", { name: "市场状态" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "使用专家" })).toBeVisible();
  await page.getByTestId("ml-backtest").click();
  await expect(page.getByRole("button", { name: "查看完整回测" })).toBeVisible({ timeout: 180_000 });
  const evidenceDir = process.env.BYQ_E2E_EVIDENCE_DIR;
  if (evidenceDir) { await page.screenshot({ path: `${evidenceDir}/03-regime-experts-desktop.png`, fullPage: true }); await page.setViewportSize({ width: 390, height: 844 }); await page.screenshot({ path: `${evidenceDir}/04-regime-experts-mobile.png`, fullPage: true }); }
  expect([...unexpectedOrigins]).toEqual([]); expect(serverErrors).toEqual([]);
});

test("real Product API index pool materializes validated point-in-time weights", async ({ page, baseURL }) => {
  const username = process.env.BYQ_E2E_ADMIN_USERNAME;
  const password = process.env.BYQ_E2E_ADMIN_PASSWORD;
  if (!username || !password) throw new Error("BYQ_E2E admin credentials are required");
  const origin = new URL(baseURL ?? "http://127.0.0.1:18080").origin;
  const unexpectedOrigins = new Set<string>();
  const serverErrors: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if ((url.protocol === "http:" || url.protocol === "https:") && url.origin !== origin) unexpectedOrigins.add(url.origin);
  });
  page.on("response", (response) => { if (response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`); });

  await page.goto("/login");
  await page.getByLabel("用户名").fill(username);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "进入" }).click();
  await expect(page).toHaveURL(`${origin}/agent`);
  await page.goto("/stock-pool");
  await page.getByRole("button", { name: "新建股票池" }).click();
  const dialog = page.getByRole("dialog", { name: "创建版本化股票池" });
  await dialog.getByText("指数型股票池", { exact: true }).click();
  await dialog.locator(".el-select").click();
  await expect(page.getByRole("option")).toHaveCount(6);
  await expect(page.getByRole("option", { name: /上证50/ })).toBeEnabled();
  await expect(page.getByRole("option", { name: /中证500/ })).toBeEnabled();
  await expect(page.getByRole("option", { name: /中证1000/ })).toBeEnabled();
  await page.getByRole("option", { name: /沪深300/ }).click();
  const poolName = `CI指数池-${Date.now()}`;
  await dialog.getByPlaceholder("Pool name").fill(poolName);
  const createdResponse = page.waitForResponse((response) =>
    response.url().endsWith("/api/product/paper/index-pools") && response.request().method() === "POST",
  );
  await dialog.getByRole("button", { name: "创建并生成快照" }).click();
  const response = await createdResponse;
  expect(response.status()).toBe(202);
  const created = await response.json() as { pool: { pool_id: string } };

  await expect.poll(async () => page.evaluate(async (poolId) => {
    const result = await fetch(`/api/product/paper/pools/${poolId}/materializations`, { credentials: "include" });
    if (!result.ok) return `http-${result.status}`;
    return (await result.json()).runs?.[0]?.status ?? "missing";
  }, created.pool.pool_id), { timeout: 30_000 }).toBe("succeeded");

  await page.goto(`/stock-pool?pool=${created.pool.pool_id}`);
  await expect(page.getByText(poolName, { exact: true }).first()).toBeVisible();
  await page.getByRole("tab", { name: "成员与权重" }).click();
  await expect(page.getByText("000001.SZ", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("600000.SH", { exact: true }).first()).toBeVisible();
  await page.getByRole("tab", { name: "快照历史" }).click();
  await expect(
    page.getByRole("tabpanel", { name: "快照历史" }).getByText("succeeded", { exact: true }),
  ).toBeVisible();
  const evidenceDir = process.env.BYQ_E2E_EVIDENCE_DIR;
  if (evidenceDir) {
    await page.screenshot({ path: `${evidenceDir}/01-index-pool-desktop.png`, fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: `${evidenceDir}/02-index-pool-mobile.png`, fullPage: true });
  }
  expect([...unexpectedOrigins]).toEqual([]);
  expect(serverErrors).toEqual([]);
});

test("real Product API dynamic pool previews and materializes a closed rule", async ({ page, baseURL }) => {
  const username = process.env.BYQ_E2E_ADMIN_USERNAME;
  const password = process.env.BYQ_E2E_ADMIN_PASSWORD;
  if (!username || !password) throw new Error("BYQ_E2E admin credentials are required");
  const origin = new URL(baseURL ?? "http://127.0.0.1:18080").origin;
  const unexpectedOrigins = new Set<string>();
  const serverErrors: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if ((url.protocol === "http:" || url.protocol === "https:") && url.origin !== origin) unexpectedOrigins.add(url.origin);
  });
  page.on("response", (response) => { if (response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`); });

  await page.goto("/login");
  await page.getByLabel("用户名").fill(username);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "进入" }).click();
  await expect(page).toHaveURL(`${origin}/agent`);
  await page.goto("/stock-pool");
  await page.getByRole("button", { name: "新建股票池" }).click();
  const dialog = page.getByRole("dialog", { name: "创建版本化股票池" });
  await dialog.getByText("动态股票池", { exact: true }).click();
  const poolName = `CI动态池-${Date.now()}`;
  await dialog.getByPlaceholder("Pool name").fill(poolName);
  await dialog.getByTestId("dynamic-top-n").locator("input").fill("2");
  const previewResponse = page.waitForResponse((response) =>
    response.url().endsWith("/api/product/paper/dynamic-pools/preview") && response.request().method() === "POST",
  );
  await dialog.getByTestId("dynamic-preview").click();
  expect((await previewResponse).status()).toBe(200);
  await expect(dialog.getByText(/非权威预览：2 只/)).toBeVisible();
  const createResponse = page.waitForResponse((response) =>
    response.url().endsWith("/api/product/paper/dynamic-pools") && response.request().method() === "POST",
  );
  await dialog.getByRole("button", { name: "创建并生成快照" }).click();
  const response = await createResponse;
  expect(response.status()).toBe(202);
  const created = await response.json() as { pool: { pool_id: string } };
  await expect.poll(async () => page.evaluate(async (poolId) => {
    const result = await fetch(`/api/product/paper/pools/${poolId}/materializations`, { credentials: "include" });
    return result.ok ? (await result.json()).runs?.[0]?.status ?? "missing" : `http-${result.status}`;
  }, created.pool.pool_id), { timeout: 30_000 }).toBe("succeeded");
  await page.goto(`/stock-pool?pool=${created.pool.pool_id}`);
  await expect(page.getByText(poolName, { exact: true }).first()).toBeVisible();
  await expect(page.getByText("规则 v1 已保存", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "成员与权重" }).click();
  await expect(page.getByText("300750.SZ", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("000001.SZ", { exact: true }).first()).toBeVisible();
  const evidenceDir = process.env.BYQ_E2E_EVIDENCE_DIR;
  if (evidenceDir) {
    await page.screenshot({ path: `${evidenceDir}/03-dynamic-pool-desktop.png`, fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: `${evidenceDir}/04-dynamic-pool-mobile.png`, fullPage: true });
  }
  expect([...unexpectedOrigins]).toEqual([]);
  expect(serverErrors).toEqual([]);
});

test("real Product API Paper Trading settlement, risk, detail, and bundle flow", async ({ page, baseURL }) => {
  const adminUsername = process.env.BYQ_E2E_ADMIN_USERNAME;
  const adminPassword = process.env.BYQ_E2E_ADMIN_PASSWORD;
  if (!adminUsername || !adminPassword) throw new Error("BYQ_E2E admin credentials are required");
  const origin = new URL(baseURL ?? "http://127.0.0.1:18080").origin;
  const unexpectedOrigins = new Set<string>();
  const serverErrors: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if ((url.protocol === "http:" || url.protocol === "https:") && url.origin !== origin) unexpectedOrigins.add(url.origin);
  });
  page.on("response", (response) => { if (response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`); });

  await page.goto("/login");
  await page.getByLabel("用户名").fill(adminUsername);
  await page.getByLabel("密码").fill(adminPassword);
  await page.getByRole("button", { name: "进入" }).click();
  await expect(page).toHaveURL(`${origin}/agent`);

  const suffix = Date.now();
  const pool = await page.evaluate(async (name) => {
    const response = await fetch("/api/product/paper/pools", {
      method: "POST", credentials: "include", headers: { "content-type": "application/json" },
      body: JSON.stringify({ name, symbols: ["000001.SZ"], pool_type: "custom" }),
    });
    if (!response.ok) throw new Error(`pool create failed: ${response.status}`);
    return (await response.json()).pool;
  }, `纸面交易池-${suffix}`) as { pool_id: string; name: string };

  await page.goto("/paper-trading");
  await expect(page.getByRole("heading", { name: "模拟账户与交易监督" })).toBeVisible();
  await page.getByTestId("paper-account-name").fill(`纸面账户-${suffix}`);
  const createdAccount = page.waitForResponse((response) => response.url().endsWith("/api/product/paper/accounts") && response.request().method() === "POST");
  await page.getByRole("button", { name: "新建账户" }).click();
  expect((await createdAccount).status()).toBe(201);
  await expect(page.getByText(`纸面账户-${suffix}`, { exact: true })).toBeVisible();

  const accountId = await page.getByText(`纸面账户-${suffix}`, { exact: true }).locator("..").locator("small").textContent();
  if (!accountId) throw new Error("created paper account id missing");
  const firstOrderStatus = await page.evaluate(async ({ accountId: id, poolId: selectedPool }) => {
    const response = await fetch("/api/product/paper/orders", {
      method: "POST", credentials: "include", headers: { "content-type": "application/json" },
      body: JSON.stringify({ account_id: id, pool_id: selectedPool, symbol: "000001.SZ",
        side: "buy", quantity: 100, price: 10, trade_date: "20240102", idempotency_key: crypto.randomUUID() }),
    });
    return response.status;
  }, { accountId, poolId: pool.pool_id });
  expect(firstOrderStatus).toBe(201);
  await page.reload();

  await page.getByRole("tab", { name: "持仓" }).click();
  await expect(page.getByText("000001.SZ", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "日终结算" }).click();
  const dialog = page.getByRole("dialog", { name: "手动日终结算" });
  await dialog.getByPlaceholder("YYYYMMDD").fill("20240103");
  await dialog.locator(".el-input-number input").fill("10.5");
  const settled = page.waitForResponse((response) => response.url().includes("/settlements") && response.request().method() === "POST");
  await dialog.getByRole("button", { name: "确认结算" }).click();
  expect((await settled).status()).toBe(201);
  await expect(page.getByRole("tab", { name: "结算快照" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tabpanel", { name: "结算快照" }).getByText("20240103", { exact: true })).toBeVisible();

  await page.getByRole("tab", { name: "订单与成交" }).click();
  await page.getByText("已成交", { exact: true }).first().click();
  await expect(page.getByRole("dialog", { name: "订单审计详情" })).toBeVisible();
  await expect(page.getByText("paper-execution-v2", { exact: false })).toBeVisible();
  await page.getByRole("dialog", { name: "订单审计详情" }).locator(".el-dialog__headerbtn").click();

  await page.getByRole("tab", { name: "风险与迁移" }).click();
  const riskPanel = page.locator(".risk-panel").first();
  await riskPanel.locator(".el-input-number input").fill("500");
  const controlsSaved = page.waitForResponse((response) => response.url().endsWith("/controls") && response.request().method() === "PUT");
  await riskPanel.getByRole("button", { name: "保存风险控制" }).click();
  expect((await controlsSaved).status()).toBe(200);

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出 JSON" }).click();
  const download = await downloadPromise;
  const downloadPath = await download.path();
  if (!downloadPath) throw new Error("paper account bundle download path missing");
  const imported = page.waitForResponse((response) => response.url().endsWith("/api/product/paper/accounts/import") && response.request().method() === "POST");
  await page.getByTestId("paper-import-input").setInputFiles(downloadPath);
  const importedResponse = await imported;
  expect(importedResponse.status(), await importedResponse.text()).toBe(201);
  await expect(page.getByText(new RegExp(`纸面账户-${suffix} · 导入`)).first()).toBeVisible();

  expect([...unexpectedOrigins]).toEqual([]);
  expect(serverErrors).toEqual([]);
});

test("real Product API My Space credential, binding, policy, and asset import flow", async ({ page, baseURL }) => {
  const username = process.env.BYQ_E2E_ADMIN_USERNAME;
  const password = process.env.BYQ_E2E_ADMIN_PASSWORD;
  if (!username || !password) throw new Error("BYQ_E2E admin credentials are required");
  const origin = new URL(baseURL ?? "http://127.0.0.1:18080").origin;
  const unexpectedOrigins = new Set<string>();
  const serverErrors: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if ((url.protocol === "http:" || url.protocol === "https:") && url.origin !== origin) unexpectedOrigins.add(url.origin);
  });
  page.on("response", (response) => { if (response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`); });

  await page.goto("/login");
  await page.getByLabel("用户名").fill(username);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "进入" }).click();
  await expect(page).toHaveURL(`${origin}/agent`);

  const suffix = Date.now();
  const result = await page.evaluate(async (id) => {
    async function request(path: string, init: RequestInit = {}) {
      const response = await fetch(`/api/product${path}`, {
        ...init, credentials: "include",
        headers: { ...(init.body ? { "content-type": "application/json" } : {}), ...(init.headers ?? {}) },
      });
      const text = await response.text();
      if (!response.ok) throw new Error(`${path} failed: ${response.status} ${text}`);
      return { body: JSON.parse(text), text };
    }
    const secret = `sk-phase37-browser-${id}`;
    const created = await request("/settings/models/credentials", { method: "POST", body: JSON.stringify({ provider: "deepseek", label: `E2E凭据-${id}`, secret, idempotency_key: `e2e-credential-${id}` }) });
    if (created.text.includes(secret) || created.text.includes("ciphertext")) throw new Error("credential response leaked secret material");
    const credential = created.body.credential;
    const profile = (await request("/settings/models/profiles", { method: "POST", body: JSON.stringify({ credential_id: credential.credential_id, key_name: `e2e-${id}`, display_name: `E2E档案-${id}`, provider: "deepseek", model: "deepseek-v4-flash", temperature: 0.2, reasoning_enabled: false }) })).body.profile;
    const settings = (await request("/settings/models")).body;
    const binding = settings.bindings.find((item: { agent_id: string }) => item.agent_id === "byq-product");
    await request("/settings/models/bindings/byq-product", { method: "PUT", body: JSON.stringify({ profile_id: profile.profile_id, expected_version: binding?.version ?? 0 }) });
    await request("/settings/agent-policy/rules", { method: "POST", body: JSON.stringify({ name: `E2E拒绝回测-${id}`, description: "real browser evidence", action: "byq_backtest_run", agent_id: "*", decision_mode: "auto_deny", risk_level: "high", priority: 10, enabled: true }) });
    await request("/paper/pools", { method: "POST", body: JSON.stringify({ name: `E2E资产池-${id}`, symbols: ["000001.SZ"], pool_type: "custom" }) });
    const bundle = (await request("/settings/assets/export")).body;
    const imported = (await request("/settings/assets/import", { method: "POST", body: JSON.stringify(bundle) })).body;
    return { bundleVersion: bundle.schema_version, imported, credentialLabel: credential.label };
  }, suffix) as { bundleVersion: string; imported: { imported: { pools: number }; source_owner_reused: boolean }; credentialLabel: string };

  expect(result.bundleVersion).toBe("byq-workspace-assets-v2");
  expect(result.imported.imported.pools).toBeGreaterThanOrEqual(1);
  expect(result.imported.source_owner_reused).toBe(false);

  await openUserDestination(page, "模型配置");
  await expect(page).toHaveURL(`${origin}/user/models`);
  await expect(page.getByText(result.credentialLabel, { exact: true })).toBeVisible();
  await expect(page.getByText(`E2E档案-${suffix}`, { exact: true })).toBeVisible();
  const evidenceDir = process.env.BYQ_E2E_EVIDENCE_DIR;
  if (evidenceDir) await page.screenshot({ path: `${evidenceDir}/01-model-settings.png`, fullPage: true });
  await openUserDestination(page, "智能助手偏好");
  await expect(page).toHaveURL(`${origin}/user/agent-policy`);
  await expect(page.getByText(`E2E拒绝回测-${suffix}`, { exact: true })).toBeVisible();
  if (evidenceDir) await page.screenshot({ path: `${evidenceDir}/02-agent-policy.png`, fullPage: true });
  await openUserDestination(page, "资产管理");
  await expect(page).toHaveURL(`${origin}/user/assets`);
  await expect(page.getByText(`E2E资产池-${suffix}`, { exact: true }).first()).toBeVisible();
  if (evidenceDir) await page.screenshot({ path: `${evidenceDir}/03-assets-import.png`, fullPage: true });

  await openUserDestination(page, "系统设置");
  await expect(page).toHaveURL(new RegExp(`${origin}/settings/system/overview`));
  await expect(page.getByRole("dialog").getByRole("heading", { name: "系统概览" })).toBeVisible();
  const settingsNavigation = page.getByRole("navigation", { name: "系统设置导航" });
  await settingsNavigation.getByRole("button", { name: /数据库/ }).click();
  await expect(page.getByRole("dialog").getByText("byq_domain", { exact: true })).toBeVisible();
  await settingsNavigation.getByRole("button", { name: /运行时/ }).click();
  await expect(page.getByText("deepseek-harness-sdk==0.1.1rc1", { exact: true })).toBeVisible();

  expect([...unexpectedOrigins]).toEqual([]);
  expect(serverErrors).toEqual([]);
});

async function phase90FeedbackJourney({ page, baseURL }: { page: Page; baseURL?: string }) {
  const username = process.env.BYQ_E2E_ADMIN_USERNAME;
  const password = process.env.BYQ_E2E_ADMIN_PASSWORD;
  if (!username || !password) throw new Error("BYQ_E2E admin credentials are required");
  const origin = new URL(baseURL ?? "http://127.0.0.1:18080").origin;
  const unexpectedOrigins = new Set<string>();
  const serverErrors: string[] = [];
  const consoleErrors: string[] = [];
  const feedbackRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (["http:", "https:"].includes(url.protocol) && url.origin !== origin) unexpectedOrigins.add(url.origin);
    if (url.pathname.startsWith("/api/product/feedback")) feedbackRequests.push(`${request.method()} ${url.pathname}`);
  });
  page.on("response", (response) => { if (response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`); });

  await page.goto("/login");
  await page.getByLabel("用户名").fill(username);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "进入" }).click();
  await expect(page).toHaveURL(`${origin}/agent`);
  page.on("console", (entry) => { if (entry.type() === "error") consoleErrors.push(entry.text()); });
  await page.goto("/feedback");
  await expect(page.getByRole("heading", { name: "反馈与建议" })).toBeVisible();
  await expect(page.getByText(/无需配置 GitHub 账号/)).toBeVisible();
  await expect.poll(() => feedbackRequests.filter((value) => value.startsWith("GET ")).length).toBe(2);
  const suffix = Date.now();
  await page.getByRole("button", { name: "新建" }).click();
  await page.getByLabel("标题").fill(`Phase90 加载反馈 ${suffix}`);
  await page.getByLabel("问题或建议描述").fill("真实浏览器验证反馈首屏、隐私预览和审核闭环。 ");
  await page.getByRole("button", { name: "保存草稿" }).click();
  await page.getByRole("button", { name: "生成提交预览" }).click();
  await expect(page.getByRole("heading", { name: "公开候选快照" })).toBeVisible();
  const submitCount = feedbackRequests.filter((value) => value.endsWith("/submit")).length;
  expect(submitCount).toBe(0);
  await page.getByRole("button", { name: "检查无误，确认提交" }).click();
  await page.getByRole("button", { name: "我已检查并提交" }).click();
  await expect.poll(() => feedbackRequests.filter((value) => value.endsWith("/submit")).length).toBe(1);
  const feedbackId = await page.evaluate(async (title) => {
    const response = await fetch(`/api/product/feedback/items?status=submitted&category=all&query=${encodeURIComponent(title)}&limit=1&offset=0`, { credentials: "include" });
    return (await response.json()).items[0].feedback_id as string;
  }, `Phase90 加载反馈 ${suffix}`);

  const evidenceDir = process.env.BYQ_E2E_EVIDENCE_DIR;
  if (evidenceDir) await page.screenshot({ path: `${evidenceDir}/01-feedback-owner-desktop.png`, fullPage: true });
  await page.goto("/settings/system/feedback");
  await expect(page.getByText("GitHub 发布服务未配置")).toBeVisible();
  await page.getByRole("button", { name: new RegExp(`Phase90 加载反馈 ${suffix}`) }).click();
  await page.getByRole("button", { name: "完成分诊" }).click();
  await page.getByRole("dialog", { name: "标记已分诊" }).getByRole("textbox").fill("已复核真实浏览器反馈");
  await page.getByRole("dialog", { name: "标记已分诊" }).getByRole("button", { name: "确定" }).click();
  await page.getByRole("button", { name: "采纳", exact: true }).click();
  await page.getByRole("dialog", { name: "采纳并进入发布队列" }).getByRole("textbox").fill("验收通过，进入发布队列");
  await page.getByRole("dialog", { name: "采纳并进入发布队列" }).getByRole("button", { name: "确定" }).click();
  await expect(page.getByText("GitHub 发布服务未配置")).toBeVisible();
  const accepted = await page.evaluate(async (id) => {
    const response = await fetch(`/api/product/feedback/moderation/items/${id}`, { credentials: "include" });
    return (await response.json()).feedback;
  }, feedbackId) as { status: string; publication_status: string };
  expect(accepted).toMatchObject({ status: "accepted", publication_status: "publisher_unconfigured" });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.getByText("GitHub 发布服务未配置")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  if (evidenceDir) await page.screenshot({ path: `${evidenceDir}/02-feedback-admin-mobile.png`, fullPage: true });
  expect([...unexpectedOrigins]).toEqual([]);
  expect(serverErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
}
