import { expect, test } from "@playwright/test";

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
  await expect(page).toHaveURL(`${origin}/`);
  await expect(page.getByRole("heading", { name: "工作台" })).toBeVisible();

  await page.goto("/stock-pool");
  await expect(page.getByRole("heading", { name: "股票管理" })).toBeVisible();

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
  expect((await createdResponse).status()).toBe(201);
  await expect(page.getByText(poolName, { exact: true }).first()).toBeVisible();
  await expect(page.getByText("000001.SZ", { exact: true }).first()).toBeVisible();

  expect([...unexpectedOrigins]).toEqual([]);
  expect(serverErrors).toEqual([]);
});
