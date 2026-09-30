/** Real browser evidence for one exact isolated OptimizationJob comparison Artifact. */
import { chromium } from "@playwright/test";

const origin = process.env.BYQ_REAL_BASE_URL;
const username = process.env.BYQ_E2E_ADMIN_USERNAME;
const password = process.env.BYQ_E2E_ADMIN_PASSWORD;
const artifactId = process.env.BYQ_PHASE15_COMPARISON_ARTIFACT_ID;
const jobIds = [process.env.BYQ_PHASE15_BACKTEST_A, process.env.BYQ_PHASE15_BACKTEST_B];
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin ?? "") || !username || !password
    || !/^artifact_[0-9a-f]{32}$/.test(artifactId ?? "")
    || jobIds.some((id) => !/^backtest_[0-9a-f]{32}$/.test(id ?? ""))) {
  throw new Error("exact isolated optimization browser context required");
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

  await page.goto(`${origin}/user/research`);
  await page.getByRole("tab", { name: "实体查询" }).click();
  await page.getByPlaceholder("Entity ID").fill(artifactId);
  await page.getByRole("button", { name: "查看" }).click();
  const result = page.locator("pre.quant-result");
  await result.waitFor({ timeout: 15000 });
  const artifact = JSON.parse(await result.innerText());
  const content = artifact.content ?? {};
  const rankedIds = (content.ranking ?? []).map((row) => row.backtest_job_id);
  if (artifact.artifact_id !== artifactId || artifact.kind !== "optimization_comparison"
      || artifact.status !== "validated" || content.candidate_count !== 2
      || content.reran_backtests !== false || rankedIds.length !== 2
      || new Set(rankedIds).size !== 2 || jobIds.some((id) => !rankedIds.includes(id))) {
    throw new Error("browser did not render the exact two-Job comparison ranking");
  }
  const offOrigin = browserRequests.filter((url) => !url.startsWith(`${origin}/`) && url !== origin);
  if (offOrigin.length) throw new Error("browser requested a service outside Frontend/Gateway origin");
  console.log(JSON.stringify({ result: "PASS", artifact_id: artifactId,
    ranked_job_ids: rankedIds, browser_requests: browserRequests.length,
    off_origin_requests: offOrigin.length }));
} finally {
  await browser.close();
}
