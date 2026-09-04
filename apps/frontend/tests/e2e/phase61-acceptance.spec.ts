import { expect, test, type Page } from "@playwright/test";

async function login(page: Page) {
  const username = process.env.BYQ_E2E_ADMIN_USERNAME;
  const password = process.env.BYQ_E2E_ADMIN_PASSWORD;
  if (!username || !password) throw new Error("BYQ_E2E admin credentials are required");
  await page.goto("/login");
  await page.getByLabel("用户名").fill(username);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "进入" }).click();
  await expect(page).toHaveURL(/\/agent/);
}

function observeBrowser(page: Page) {
  const consoleErrors: string[] = [];
  const serverErrors: string[] = [];
  const unexpectedOrigins = new Set<string>();
  const origin = new URL(process.env.BYQ_REAL_BASE_URL ?? "http://127.0.0.1:18081").origin;
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (["http:", "https:"].includes(url.protocol) && url.origin !== origin) unexpectedOrigins.add(url.origin);
  });
  page.on("response", (response) => { if (response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`); });
  return { consoleErrors, serverErrors, unexpectedOrigins };
}

async function researchCounts(page: Page) {
  return page.evaluate(async () => {
    const paths = ["/api/product/research/tasks", "/api/product/research/experiments", "/api/product/research/artifacts"];
    const keys = ["tasks", "experiments", "artifacts"];
    const result: Record<string, number> = {};
    for (let index = 0; index < paths.length; index += 1) {
      const response = await fetch(paths[index], { credentials: "include" });
      if (!response.ok) throw new Error(`research count failed: ${response.status}`);
      const body = await response.json();
      result[keys[index]] = Array.isArray(body[keys[index]]) ? body[keys[index]].length : -1;
    }
    return result;
  });
}

test("Phase 61 continuous research keeps context, visible progress, and zero unnecessary assets", async ({ page }) => {
  await login(page);
  const browser = observeBrowser(page);
  await page.goto(`/agent?new=${Date.now()}`);
  await expect(page.getByRole("heading", { name: "今天想研究什么？" })).toBeVisible();
  const before = await researchCounts(page);

  const composer = page.getByPlaceholder("向小巴描述你的投研问题…");
  await composer.fill("帮我看看招商银行最近 5 个交易日走势怎么样。只使用已同步数据，并明确实际起止日期、行数和结论截止日。");
  await page.getByRole("button", { name: "发送" }).click();
  const progress = page.locator(".run-strip");
  await expect(progress).toContainText("已用时");
  await expect(progress.getByRole("button", { name: "停止本轮" })).toBeVisible();
  await expect(composer).toBeDisabled();
  await expect(progress).toBeHidden({ timeout: 180_000 });

  const first = page.locator(".conversation-message.agent .message-body").last();
  await expect(first).toContainText("招商银行");
  await expect(first).toContainText(/2026-08-26|20260826/);
  const firstText = await first.innerText();
  expect(firstText).not.toMatch(/Artifact ID|WorkflowTrace|DSH|ResearchTask/);

  await composer.fill("和兴业银行比一下，哪个最近更强？还是按刚才的 5 个交易日和同一数据口径。请同时给出首日至末日收盘变化，严格用末日收盘除以首日收盘再减 1 计算。");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(progress).toContainText("已用时");
  await expect(progress).toBeHidden({ timeout: 180_000 });
  const second = page.locator(".conversation-message.agent .message-body").last();
  await expect(second).toContainText("兴业银行");
  await expect(second).toContainText("招商银行");
  await expect(second).toContainText(/招商银行[^\n]*(?:\+?2\.4|\+?2\.42)%/);
  await expect(second).toContainText(/兴业银行[^\n]*(?:\+?0\.2|\+?0\.22)%/);

  expect(await researchCounts(page)).toEqual(before);
  expect(browser.consoleErrors).toEqual([]);
  expect(browser.serverErrors).toEqual([]);
  expect([...browser.unexpectedOrigins]).toEqual([]);
  const evidenceDir = process.env.BYQ_E2E_EVIDENCE_DIR;
  if (evidenceDir) await page.screenshot({ path: `${evidenceDir}/04-agent-continuous-research.png`, fullPage: true });
});

test("Phase 61 task readiness and post-backtest next steps are understandable", async ({ page }) => {
  await login(page);
  const browser = observeBrowser(page);

  await page.goto("/settings/system/data");
  await expect(page.getByText("这批数据现在能用吗？", { exact: true })).toBeVisible();
  const readinessCard = page.locator(".readiness-card");
  await readinessCard.getByLabel("股票代码").fill("002737.SZ");
  await readinessCard.getByLabel("开始日期").fill("20260727");
  await readinessCard.getByLabel("结束日期").fill("20260826");
  const readiness = page.waitForResponse((response) => response.url().endsWith("/api/product/data-center/readiness"));
  await readinessCard.getByRole("button", { name: "检查可用性" }).click();
  expect((await readiness).status()).toBe(200);
  await expect(page.locator(".readiness-result")).toContainText(/可以使用|部分受限|暂不可用/);
  await expect(page.getByText("下方全局概览只说明已存数据量，不能代替上面的任务可用性检查。")).toBeVisible();

  await page.goto("/backtest");
  const completedRow = page.locator(".desktop-catalog-table tbody tr").filter({ hasText: "已完成" }).first();
  await expect(completedRow).toBeVisible();
  await completedRow.click();
  await expect(page.getByRole("button", { name: "让小巴分析" })).toBeVisible();
  await expect(page.getByRole("button", { name: "基于结果优化" })).toBeVisible();
  await expect(page.getByRole("button", { name: "再次回测" })).toBeVisible();
  await expect(page.getByRole("button", { name: "进入模拟操盘" })).toBeVisible();
  await expect(page.getByText("累计收益", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "让小巴分析" }).click();
  await expect(page).toHaveURL(/\/agent\?.*draft=/);
  await expect(page.getByPlaceholder("向小巴描述你的投研问题…")).not.toHaveValue("");
  await page.goBack();
  await expect(page.getByRole("button", { name: "基于结果优化" })).toBeVisible();

  expect(browser.consoleErrors).toEqual([]);
  expect(browser.serverErrors).toEqual([]);
  expect([...browser.unexpectedOrigins]).toEqual([]);
  const evidenceDir = process.env.BYQ_E2E_EVIDENCE_DIR;
  if (evidenceDir) await page.screenshot({ path: `${evidenceDir}/05-readiness-backtest-next-step.png`, fullPage: true });
});

test("Phase 61 strategy detail leads with user meaning and hands off to backtest", async ({ page }) => {
  await login(page);
  const browser = observeBrowser(page);
  await page.goto("/strategy");
  await expect(page.getByRole("heading", { name: "策略目录与版本谱系" })).toBeVisible();
  await page.getByPlaceholder("搜索策略名称、说明或策略编号").fill("Phase58 v1.2 权限复验策略");
  await page.locator(".strategy-list-pane .el-radio-button").filter({ hasText: /^版本$/ }).click();
  await page.getByText("Phase58 v1.2 权限复验策略", { exact: true }).first().click();

  const detail = page.locator(".strategy-detail-pane");
  await expect(detail.getByText("Phase58 v1.2 权限复验策略", { exact: true })).toBeVisible();
  await expect(detail.getByText("关键参数", { exact: true })).toBeVisible();
  await expect(detail.getByText("技术与审计详情", { exact: true })).toBeVisible();
  await expect(detail.locator(".quant-result")).toBeHidden();
  await expect(detail.getByRole("button", { name: "批准此版本" })).toHaveCount(0);
  const start = detail.getByRole("button", { name: "开始回测" });
  await expect(start).toBeEnabled();
  await start.click();
  await page.locator(".el-message-box").getByRole("button", { name: "继续" }).click();
  await expect(page).toHaveURL(/\/backtest\?.*strategy=/);
  await expect(page.getByRole("dialog", { name: "生成信号并新建回测" })).toBeVisible();

  expect(browser.consoleErrors).toEqual([]);
  expect(browser.serverErrors).toEqual([]);
  expect([...browser.unexpectedOrigins]).toEqual([]);
  const evidenceDir = process.env.BYQ_E2E_EVIDENCE_DIR;
  if (evidenceDir) await page.screenshot({ path: `${evidenceDir}/06-strategy-backtest-handoff.png`, fullPage: true });
});
