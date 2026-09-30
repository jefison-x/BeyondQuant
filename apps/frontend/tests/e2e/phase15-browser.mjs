/** Real browser evidence for Phase 15's existing fresh-state Product records. */
import { chromium } from "@playwright/test";

const origin = process.env.BYQ_REAL_BASE_URL;
const scope = process.env.BYQ_DEV_SCOPE;
const username = process.env.BYQ_E2E_ADMIN_USERNAME;
const password = process.env.BYQ_E2E_ADMIN_PASSWORD;
const conversation = process.env.BYQ_PHASE15_CONVERSATION_ID;
const backtests = [process.env.BYQ_PHASE15_BACKTEST_A, process.env.BYQ_PHASE15_BACKTEST_B];
const artifacts = [process.env.BYQ_PHASE15_RESEARCH_ARTIFACT_ID,
  process.env.BYQ_PHASE15_COMPARISON_ARTIFACT_ID];

if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin ?? "") || !/^byq-dev-[0-9a-f]{10}$/.test(scope ?? "")
    || !username || !password || !/^conversation_[0-9a-f]{32}$/.test(conversation ?? "")
    || backtests.some((id) => !/^backtest_[0-9a-f]{32}$/.test(id ?? ""))
    || artifacts.some((id) => !/^artifact_[0-9a-f]{32}$/.test(id ?? ""))) {
  throw new Error("exact isolated Phase 15 browser context required");
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
const browserRequests = [];
page.on("request", (request) => browserRequests.push(request.url()));

try {
  await page.goto(`${origin}/login`, { waitUntil: "domcontentloaded" });
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: "进入" }).click();
  await page.waitForURL((url) => url.pathname !== "/login", { timeout: 15000 });

  await page.goto(`${origin}/agent?session=${encodeURIComponent(conversation)}`);
  await page.waitForFunction(() => {
    const text = document.body.innerText;
    return text.includes("9.21") && text.includes("信息披露");
  }, undefined, { timeout: 20000 });
  const agentText = await page.locator("body").innerText();
  if (!agentText.includes("9.21") || !agentText.includes("信息披露")) {
    throw new Error("fresh two-turn Product conversation was not rendered");
  }

  await page.goto(`${origin}/backtest?job=${encodeURIComponent(backtests[0])}`);
  await page.getByRole("heading", { name: "回测任务与完整结果" }).waitFor({ timeout: 20000 });
  const names = ["Phase 15 synthetic backtest 2", "Phase 15 synthetic backtest 3"];
  const catalog = await page.evaluate(async () => {
    const response = await fetch("/api/product/backtests?query=&status=&limit=20&offset=0", {
      credentials: "include",
    });
    if (!response.ok) throw new Error("Product Backtest catalog failed in browser");
    return response.json();
  });
  if (!Array.isArray(catalog.backtests)) throw new Error("Product Backtest catalog is invalid");
  for (const [index, id] of backtests.entries()) {
    const matches = catalog.backtests.filter((item) => item.job_id === id && item.status === "completed"
      && item.name === names[index]);
    const suffixMatches = catalog.backtests.filter((item) =>
      String(item.job_id ?? "").endsWith(id.slice(-4)));
    if (matches.length !== 1 || suffixMatches.length !== 1) {
      throw new Error("exact completed Backtest identity does not uniquely map to visible short reference");
    }
  }
  for (const name of names) {
    await page.getByRole("row", { name: new RegExp(name) }).first().waitFor({ timeout: 15000 });
  }
  const rows = names.map((name, index) => page.getByRole("row", { name: new RegExp(name) })
    .filter({ hasText: backtests[index].slice(-4) }).first());
  for (const [index, row] of rows.entries()) {
    const text = await row.innerText();
    if (!text.includes(backtests[index].slice(-4)) || !text.includes("已完成")) {
      throw new Error("the exact completed Backtest Job is missing from the browser list");
    }
    await row.locator("label.el-checkbox").click();
  }
  await page.getByRole("button", { name: "对比所选任务" }).click();
  const dialog = page.getByRole("dialog", { name: "回测对比" });
  await dialog.waitFor({ timeout: 10000 });
  for (const label of ["指标差异", "任务 A", "任务 B", "差异 B - A"]) {
    if (!(await dialog.innerText()).includes(label)) throw new Error(`comparison view missing ${label}`);
  }
  const returnCells = await dialog.getByRole("row", { name: /累计收益/ }).locator("td").allInnerTexts();
  if (returnCells.length !== 4 || returnCells.slice(1).some((value) =>
    value.trim() === "-" || !Number.isFinite(Number.parseFloat(value)))) {
    throw new Error("comparison view did not render numeric Backtest result values");
  }

  await page.goto(`${origin}/user/research`);
  await page.getByRole("tab", { name: "研究资产" }).click();
  const artifactFilter = page.getByPlaceholder("筛选资产类型、编号或状态");
  for (const id of artifacts) {
    await artifactFilter.fill(id);
    await page.getByRole("row", { name: new RegExp(id) }).waitFor({ timeout: 10000 });
  }

  const offOrigin = browserRequests.filter((url) => !url.startsWith(`${origin}/`) && url !== origin);
  if (offOrigin.length) throw new Error("browser issued a request outside Gateway/Frontend origin");
  console.log(JSON.stringify({
    result: "PASS", conversation_id: conversation, backtest_job_ids: backtests,
    agent_ui: "two-turn answer visible", backtest_ui: "exact completed rows and comparison visible",
    artifact_ids_visible: artifacts,
    browser_requests: browserRequests.length, off_origin_requests: offOrigin.length,
  }));
} finally {
  await browser.close();
}
