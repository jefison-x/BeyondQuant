import { expect, test, type Page } from "@playwright/test";

interface PasswordTestAccount {
  label: string;
  username?: string;
  currentPassword?: string;
  newPassword?: string;
  expectedRole: "user" | "admin";
  changeViewport: { width: number; height: number };
  loginViewport: { width: number; height: number };
}

const accounts: PasswordTestAccount[] = [
  {
    label: "ordinary user",
    username: process.env.BYQ_R4_TEST_USER_USERNAME,
    currentPassword: process.env.BYQ_R4_TEST_USER_CURRENT_PASSWORD,
    newPassword: process.env.BYQ_R4_TEST_USER_NEW_PASSWORD,
    expectedRole: "user",
    changeViewport: { width: 1440, height: 1000 },
    loginViewport: { width: 390, height: 844 },
  },
  {
    label: "dedicated Admin",
    username: process.env.BYQ_R4_TEST_ADMIN_USERNAME,
    currentPassword: process.env.BYQ_R4_TEST_ADMIN_CURRENT_PASSWORD,
    newPassword: process.env.BYQ_R4_TEST_ADMIN_NEW_PASSWORD,
    expectedRole: "admin",
    changeViewport: { width: 390, height: 844 },
    loginViewport: { width: 1440, height: 1000 },
  },
];

async function login(page: Page, username: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("用户名").fill(username);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "进入" }).click();
}

async function loginProfile(page: Page, username: string, password: string) {
  await login(page, username, password);
  await expect(page).toHaveURL(/\/agent$/);
  await page.goto("/user/profile");
  await expect(page.getByLabel("当前密码")).toBeVisible();
}

async function changePasswordOnProfile(page: Page, current: string, next: string) {
  await page.getByLabel("当前密码").fill(current);
  await page.getByLabel("新密码", { exact: true }).fill(next);
  await page.getByLabel("确认新密码").fill(next);
  const responsePromise = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/auth/change-password" && response.request().method() === "POST");
  await page.getByRole("button", { name: "修改密码" }).click();
  const response = await responsePromise;
  const receipt = await response.json() as { status?: string; error?: { code?: string } };
  expect(response.status(), receipt.error?.code ?? "missing password-change receipt").toBe(200);
  expect(receipt.status).toBe("ok");
  await expect(page).toHaveURL(/\/login$/);
}

async function staleSessionIsRejected(page: Page) {
  await page.goto("/user/profile");
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
}

async function verifyIdentity(page: Page, username: string, role: "user" | "admin") {
  const response = await page.request.get("/api/product/auth/me");
  expect(response.ok()).toBe(true);
  const identity = await response.json() as { subject?: string; role?: string };
  expect(identity.subject).toBe(username);
  expect(identity.role).toBe(role);
}

for (const account of accounts) {
  test(`R4 ${account.label} changes password on ${account.changeViewport.width < 768 ? "mobile" : "desktop"} and revokes prior logins`, async ({ page, browser, baseURL }) => {
    test.skip(!account.username || !account.currentPassword || !account.newPassword,
      "requires this role's dedicated disposable test account and current/new passwords");
    const testOrigin = new URL(baseURL ?? "");
    expect(process.env.BYQ_R4_DISPOSABLE_STACK, "explicit disposable-stack opt-in is required").toBe("1");
    expect(testOrigin.protocol).toBe("http:");
    expect(["127.0.0.1", "localhost"]).toContain(testOrigin.hostname);
    const requiredPrefix = account.expectedRole === "user" ? "r4-test-user-" : "r4-test-admin-";
    expect(account.username!.startsWith(requiredPrefix)).toBe(true);
    expect(account.newPassword).not.toBe(account.currentPassword);

    await page.setViewportSize(account.changeViewport);
    await loginProfile(page, account.username!, account.currentPassword!);
    await verifyIdentity(page, account.username!, account.expectedRole);

    const oldSessionContext = await browser.newContext({ viewport: account.changeViewport });
    const oldSessionPage = await oldSessionContext.newPage();
    await loginProfile(oldSessionPage, account.username!, account.currentPassword!);
    await changePasswordOnProfile(page, account.currentPassword!, account.newPassword!);

    await staleSessionIsRejected(oldSessionPage);
    await login(oldSessionPage, account.username!, account.currentPassword!);
    await expect(oldSessionPage).toHaveURL(/\/login(?:\?|$)/);
    await expect(oldSessionPage.locator(".login-error")).toBeVisible();

    await page.setViewportSize(account.loginViewport);
    await loginProfile(page, account.username!, account.newPassword!);
    await verifyIdentity(page, account.username!, account.expectedRole);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);

    await oldSessionContext.close();
  });
}
