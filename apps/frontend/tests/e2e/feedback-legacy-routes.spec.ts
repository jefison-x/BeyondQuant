import { expect, test, type Page } from "@playwright/test";

async function login(page: Page, admin = true) {
  let authenticated = false;
  await page.route("**/api/auth/login", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
    user: { subject: admin ? "admin" : "owner", role: admin ? "admin" : "user", workspace: { workspace_id: "workspace-feedback-test" } },
    session_id: "session-feedback",
  }) }));
  await page.route("**/api/auth/me", route => authenticated
    ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ subject: admin ? "admin" : "owner", role: admin ? "admin" : "user", workspace: { workspace_id: "workspace-feedback-test" } }) })
    : (authenticated = true, route.fulfill({ status: 401, contentType: "application/json", body: "{}" })));
  await page.route("**/v1/agent/sessions**", route => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({ sessions: [], total: 0, limit: 20, offset: 0 }),
  }));
  await page.goto("/login");
  await page.getByLabel("用户名").fill(admin ? "admin" : "owner");
  await page.getByLabel("密码").fill("password123");
  await page.getByRole("button", { name: "进入" }).click();
  await expect(page).toHaveURL(/\/agent$/);
}

test("legacy feedback bookmarks return to the conversation without standalone feedback requests", async ({ page }) => {
  const feedbackRequests: string[] = [];
  page.on("request", request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/product/feedback")) feedbackRequests.push(`${request.method()} ${url.pathname}`);
  });

  await login(page);
  for (const legacyPath of ["/feedback", "/settings/system/feedback", "/admin/feedback"]) {
    await page.goto(legacyPath);
    await expect(page).toHaveURL(/\/agent$/);
    await expect(page.getByRole("heading", { name: "小巴投研" })).toBeVisible();
  }
  expect(feedbackRequests).toEqual([]);
});
