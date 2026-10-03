import { expect, test } from "@playwright/test";

const username = process.env.BYQ_R2_TEST_ADMIN_USERNAME;
const password = process.env.BYQ_R2_TEST_ADMIN_PASSWORD;

test.skip(!username || !password, "requires a dedicated disposable Admin account");

test("R2 Admin personal workspace name is corrected in desktop and mobile menus", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("用户名").fill(username!);
  await page.getByLabel("密码").fill(password!);
  await page.getByRole("button", { name: "进入" }).click();
  await expect(page).toHaveURL(/\/agent$/);

  const desktopName = page.locator(".sidebar-user-menu .user-copy small");
  await expect(desktopName).toHaveText("Admin的个人工作区");
  await page.locator(".sidebar-user-menu .user-trigger").click();
  await expect(page.getByLabel("当前个人工作区").getByText("Admin的个人工作区")).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "打开产品导航" }).click();
  const mobileName = page.locator(".product-navigation-drawer .user-copy small");
  await expect(mobileName).toHaveText("Admin的个人工作区");
});
