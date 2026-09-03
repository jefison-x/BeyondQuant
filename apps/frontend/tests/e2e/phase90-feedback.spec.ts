import { expect, test, type Page } from "@playwright/test";

async function login(page: Page, admin = false) {
  let authenticated = false;
  await page.route("**/api/auth/login", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ user: { subject: admin ? "admin" : "owner", role: admin ? "admin" : "user" }, session_id: "session-feedback" }) }));
  await page.route("**/api/auth/me", (route) => authenticated
    ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ subject: admin ? "admin" : "owner", role: admin ? "admin" : "user" }) })
    : (authenticated = true, route.fulfill({ status: 401, contentType: "application/json", body: "{}" })));
  await page.goto("/login");
  await page.getByLabel("用户名").fill(admin ? "admin" : "owner");
  await page.getByLabel("密码").fill("password123");
  await page.getByRole("button", { name: "进入" }).click();
}

const id = `feedback_${"a".repeat(32)}`;
const content = {
  schema_version: "product-feedback.v1", category: "performance", component: "model_research", severity: "high",
  title: "模型研究页面加载缓慢", description: "进入页面后等待时间较长。", reproduction_steps: ["进入模型研究"],
  expected_behavior: "快速展示第一页", actual_behavior: "等待较长时间", diagnostics: {},
};
const summary = { ...content, feedback_id: id, status: "draft", version: 1, current_revision: 1, publication_status: "not_queued", github_issue: null, created_at: "2026-09-03T00:00:00Z", updated_at: "2026-09-03T00:00:00Z" };

test("owner feedback uses two-call bootstrap and explicit preview confirmation", async ({ page }) => {
  const calls: string[] = [];
  await page.route("**/api/product/feedback/**", async (route) => {
    const url = new URL(route.request().url()); calls.push(`${route.request().method()} ${url.pathname}`);
    if (url.pathname.endsWith("/options")) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ schema_version: "product-feedback-options.v1", categories: ["bug", "feature", "performance", "usability", "other"], components: ["model_research", "other"], severities: ["low", "normal", "high"], limits: { title: 160, description: 8000, steps: 12, request_bytes: 24576 }, privacy: { preview_required: true, explicit_confirmation_required: true, attachments_supported: false, security_reports_public: false, normal_user_github_configuration: false }, publisher: { configured: false, status: "unconfigured" } }) });
    if (url.pathname.endsWith("/preview")) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ schema_version: "feedback-publication-preview.v1", public_content: content, redactions: { categories: [], count: 0 }, disclosure: "提交后可能公开到 GitHub Issue。", preview_hash: "b".repeat(64) }) });
    if (url.pathname.endsWith("/submit")) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ feedback: { ...summary, status: "submitted", version: 2 } }) });
    if (url.pathname.endsWith(`/items/${id}`)) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ feedback: { ...summary, status: calls.some((value) => value.endsWith("/submit")) ? "submitted" : "draft", content } }) });
    if (url.pathname.endsWith("/items") && route.request().method() === "POST") return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ feedback: { ...summary, content } }) });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ schema_version: "product-feedback-catalog.v1", items: calls.some((value) => value === "POST /api/product/feedback/items") ? [summary] : [], total: 0, limit: 12, offset: 0, has_more: false }) });
  });
  await login(page); await page.goto("/feedback");
  await expect(page.getByRole("heading", { name: "反馈与建议" })).toBeVisible();
  await expect(page.getByText(/你无需配置 GitHub 账号/)).toBeVisible();
  expect(calls.slice(0, 2).sort()).toEqual(["GET /api/product/feedback/items", "GET /api/product/feedback/options"].sort());
  await page.getByRole("button", { name: "新建" }).click();
  await page.getByLabel("标题").fill(content.title);
  await page.getByLabel("问题或建议描述").fill(content.description);
  await page.getByRole("button", { name: "保存草稿" }).click();
  await page.getByRole("button", { name: "生成提交预览" }).click();
  await expect(page.getByRole("heading", { name: "公开候选快照" })).toBeVisible();
  expect(calls.some((value) => value.endsWith("/submit"))).toBe(false);
  await page.getByRole("button", { name: "检查无误，确认提交" }).click();
  await page.getByRole("button", { name: "我已检查并提交" }).click();
  await expect.poll(() => calls.some((value) => value.endsWith("/submit"))).toBe(true);
});

test("administrator lazily opens moderation detail without publisher credentials", async ({ page }) => {
  const requested: string[] = [];
  const moderation = { ...summary, schema_version: "feedback-moderation.v1", status: "submitted", submitted_snapshot: { public_content: content, redactions: { categories: [], count: 0 }, preview_hash: "b".repeat(64) } };
  await page.route("**/api/product/feedback/moderation/**", (route) => {
    const path = new URL(route.request().url()).pathname; requested.push(path);
    if (path.endsWith("publisher-status")) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ schema_version: "feedback-publisher-status.v1", configured: false, status: "unconfigured", repository: null, credential_kind: null, queue: { queued: 0, publishing: 0, retry_wait: 0, published: 0, failed_terminal: 0 }, last_error_category: null, last_heartbeat_at: null, last_success_at: null }) });
    if (path.endsWith(`/items/${id}`)) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ feedback: moderation }) });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ schema_version: "feedback-moderation-catalog.v1", items: [moderation], total: 1, limit: 15, offset: 0, has_more: false }) });
  });
  await login(page, true); await page.goto("/settings/system/feedback");
  await expect(page.getByText("GitHub 发布服务未配置")).toBeVisible();
  expect(requested).toHaveLength(2);
  await page.getByRole("button", { name: /模型研究页面加载缓慢/ }).click();
  await expect(page.getByText("进入页面后等待时间较长。")).toBeVisible();
  expect(requested).toHaveLength(3);
});
