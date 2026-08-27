import { expect, test } from "@playwright/test";

async function login(page: import("@playwright/test").Page) {
  const username = process.env.BYQ_E2E_ADMIN_USERNAME;
  const password = process.env.BYQ_E2E_ADMIN_PASSWORD;
  if (!username || !password) throw new Error("BYQ_E2E admin credentials are required");
  await page.goto("/login");
  await page.getByLabel("用户名").fill(username);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "进入" }).click();
  await expect(page).toHaveURL(/\/agent$/);
}

test("stock-pool readiness and ordinary language stay user-facing", async ({ page }) => {
  const consoleErrors: string[] = [];
  const serverErrors: string[] = [];
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("response", (response) => {
    if (response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`);
  });

  await login(page);
  // The login bootstrap intentionally probes /api/auth/me before credentials exist.
  consoleErrors.length = 0;
  await page.goto("/settings/system/data");
  await page.getByRole("tab", { name: "覆盖审计" }).click();
  await page.getByRole("combobox", { name: "选择数据可用性股票池" }).click();
  const firstPool = page.locator(".el-select-dropdown:visible .el-select-dropdown__item").first();
  await expect(firstPool).toBeVisible();
  await firstPool.click();
  await expect(page.getByRole("combobox", { name: "选择本次检查成分" })).toBeVisible();
  await expect(page.getByPlaceholder("多个代码用逗号分隔，最多 20 个")).not.toHaveValue("");

  const readinessResponse = page.waitForResponse((response) =>
    response.url().includes("/api/product/data-center/readiness") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "检查可用性" }).click();
  expect((await readinessResponse).status()).toBe(200);
  await expect(page.getByText(/可以使用|部分受限|暂不可用/).first()).toBeVisible();
  await page.screenshot({ path: "../../docs/evidence/phase-62/screenshots/01-stock-pool-readiness.png", fullPage: true });

  await page.goto("/dashboard");
  const body = await page.locator("body").innerText();
  for (const label of ["Backend", "Artifact ID", "Job ID", "Product API", "Gateway", "WorkflowTrace"]) {
    expect(body).not.toContain(label);
  }

  await page.goto("/backtest");
  const completedRow = page.locator(".desktop-catalog-table tbody tr").filter({ hasText: "已完成" }).first();
  await expect(completedRow).toBeVisible();
  await completedRow.click();
  await expect(page.locator(".chart-wrapper canvas")).toBeVisible();
  await page.screenshot({ path: "../../docs/evidence/phase-62/screenshots/02-modular-chart.png", fullPage: true });
  expect(consoleErrors).toEqual([]);
  expect(serverErrors).toEqual([]);
});
