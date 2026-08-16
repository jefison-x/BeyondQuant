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
