import { expect, test, type Page } from "@playwright/test";

const evidenceDir = process.env.BYQ_E2E_EVIDENCE_DIR;

async function login(page: Page) {
  const username = process.env.BYQ_E2E_ADMIN_USERNAME;
  const password = process.env.BYQ_E2E_ADMIN_PASSWORD;
  if (!username || !password) throw new Error("BYQ_E2E admin credentials are required");
  await page.goto("/login");
  await page.getByLabel("用户名").fill(username);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "进入" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
}

async function openProfileDialog(page: Page) {
  await page.goto("/user/models");
  await expect(page.getByText("模型档案", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "新建档案" }).click();
  await expect(page.getByRole("dialog")).toContainText("新建模型档案");
}

async function selectCredential(page: Page, label: string) {
  const dialog = page.getByRole("dialog");
  await dialog.locator(".el-form-item").filter({ hasText: "凭据" }).locator(".el-select").click();
  await page.getByRole("option", { name: new RegExp(label) }).first().click();
}

function trackTraffic(page: Page) {
  const origin = new URL(page.url() || process.env.BYQ_REAL_BASE_URL || "http://127.0.0.1").origin;
  const crossOrigin: string[] = [];
  const serverErrors: string[] = [];
  const discovery: number[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.origin !== origin) crossOrigin.push(request.url());
  });
  page.on("response", (response) => {
    if (response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`);
    if (response.request().method() === "GET" && /\/settings\/models\/credentials\/[^/]+\/models$/.test(new URL(response.url()).pathname)) {
      discovery.push(response.status());
    }
  });
  return { crossOrigin, serverErrors, discovery };
}

test("selecting a credential refreshes provider models through the Product API", async ({ page }) => {
  await login(page);
  await openProfileDialog(page);
  await selectCredential(page, "P101D 验证");
  const traffic = trackTraffic(page);

  await page.getByRole("button", { name: "刷新模型" }).click();
  await expect(page.locator(".el-message").filter({ hasText: "已刷新" })).toBeVisible({ timeout: 20000 });
  expect(traffic.discovery.length).toBeGreaterThanOrEqual(1);
  expect(traffic.discovery.every((status) => status === 200)).toBe(true);

  const dialog = page.getByRole("dialog");
  await dialog.locator(".el-form-item").filter({ hasText: "模型" }).locator(".el-select").click();
  await expect(page.getByRole("option", { name: "deepseek-v4-pro" })).toBeVisible();
  await expect(page.getByRole("option", { name: "deepseek-flash" })).toBeVisible();
  await page.keyboard.press("Escape");

  await page.setViewportSize({ width: 1440, height: 1000 });
  if (evidenceDir) await page.screenshot({ path: `${evidenceDir}/p101d-desktop-1440.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  const noOverflow = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
  expect(noOverflow).toBe(true);
  if (evidenceDir) await page.screenshot({ path: `${evidenceDir}/p101d-mobile-390.png`, fullPage: true });

  expect(traffic.crossOrigin).toEqual([]);
  expect(traffic.serverErrors).toEqual([]);
});

test("an unusable credential keeps the reviewed catalogue with a visible failure", async ({ page }) => {
  await login(page);
  const created = await page.request.post("/api/product/settings/models/credentials", {
    data: {
      purpose: "model_api_key", provider: "deepseek", scope: "user",
      label: "P101D 合成回退", secret: "synthetic-not-a-real-key",
      idempotency_key: `p101d-fallback-${Date.now()}`,
    },
  });
  expect(created.status()).toBeLessThan(400);

  await openProfileDialog(page);
  await selectCredential(page, "P101D 验证");
  const traffic = trackTraffic(page);
  await selectCredential(page, "P101D 合成回退");
  await expect.poll(() => traffic.discovery.some((status) => status >= 400), { timeout: 20000 }).toBe(true);

  await page.getByRole("button", { name: "刷新模型" }).click();
  await expect(page.locator(".el-message").filter({ hasText: /失败|unavailable/ })).toBeVisible({ timeout: 20000 });
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator(".el-form-item").filter({ hasText: "模型" }).locator(".el-select")).toContainText(/deepseek/i);
  expect(traffic.crossOrigin).toEqual([]);
});
