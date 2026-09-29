/** Real-browser Phase 15 reset against new, disposable Product records only. */
import { chromium } from "@playwright/test";

const origin = process.env.BYQ_REAL_BASE_URL;
const scope = process.env.BYQ_DEV_SCOPE;
const username = process.env.BYQ_E2E_ADMIN_USERNAME;
const password = process.env.BYQ_E2E_ADMIN_PASSWORD;
const taskId = process.env.BYQ_PHASE15_RESET_TASK_ID;
const jobIds = [process.env.BYQ_PHASE15_RESET_BACKTEST_A,
  process.env.BYQ_PHASE15_RESET_BACKTEST_B];
const optimizationId = process.env.BYQ_PHASE15_RESET_OPTIMIZATION_ID;
const artifactId = process.env.BYQ_PHASE15_RESET_ARTIFACT_ID;
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin ?? "")
    || !/^byq-dev-[0-9a-f]{10}$/.test(scope ?? "")
    || !username || !password || !/^task_[0-9a-f]{32}$/.test(taskId ?? "")
    || jobIds.some((id) => !/^backtest_[0-9a-f]{32}$/.test(id ?? ""))
    || !/^optimizationjob_[0-9a-f]{32}$/.test(optimizationId ?? "")
    || !/^artifact_[0-9a-f]{32}$/.test(artifactId ?? "")) {
  throw new Error("exact isolated Phase 15 browser context required");
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
const offOrigin = [];
page.on("request", (request) => {
  const url = new URL(request.url());
  if (["http:", "https:"].includes(url.protocol) && url.origin !== origin) {
    offOrigin.push(url.origin);
  }
});

async function product(path, options = {}) {
  return page.evaluate(async ({ path, options }) => {
    const response = await fetch(path, { credentials: "include", ...options });
    return { status: response.status, body: await response.json() };
  }, { path, options });
}

try {
  await page.goto(`${origin}/login`);
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: "进入" }).click();
  await page.waitForURL((url) => url.pathname !== "/login", { timeout: 15000 });
  const meBefore = await product("/api/auth/me");
  if (meBefore.status !== 200 || !meBefore.body.workspace?.workspace_id) {
    throw new Error("durable Product login did not bind a Workspace");
  }
  const workspaceId = meBefore.body.workspace.workspace_id;
  const automationBefore = await product("/api/product/data-center/automation");
  const tasksBefore = await product("/api/product/research/tasks");
  const jobsBefore = await product("/api/product/backtests?query=&status=&limit=20&offset=0");
  const optimizationBefore = await product(`/api/product/optimization-jobs/${optimizationId}`);
  const artifactsBefore = await product("/api/product/research/artifacts");
  if (!tasksBefore.body.tasks?.some((item) => item.task_id === taskId)
      || jobIds.some((id) => !jobsBefore.body.backtests?.some((item) =>
        item.job_id === id && item.status === "completed"))
      || optimizationBefore.status !== 200
      || optimizationBefore.body.job?.job_id !== optimizationId
      || optimizationBefore.body.job?.status !== "SUCCEEDED"
      || !artifactsBefore.body.artifacts?.some((item) => item.artifact_id === artifactId)
      || automationBefore.status !== 200 || !automationBefore.body.automation?.config) {
    throw new Error("exact completed Task, Jobs, Artifact and global config are required before reset");
  }

  await page.goto(`${origin}/user/reset`);
  await page.getByRole("heading", { name: "重置整个工作区" }).waitFor();
  const runtimeResponse = page.waitForResponse((response) =>
    response.url().endsWith("/v1/workspaces/current/runtime-reset")
    && response.request().method() === "POST");
  await page.getByRole("button", { name: "重置运行时" }).click();
  await page.getByRole("button", { name: "确认重置", exact: true }).click();
  if ((await runtimeResponse).status() !== 200) throw new Error("browser Runtime reset failed");
  await page.getByRole("status").filter({ hasText: "运行时已重置" }).waitFor();
  const tasksAfterRuntime = await product("/api/product/research/tasks");
  if (!tasksAfterRuntime.body.tasks?.some((item) => item.task_id === taskId)) {
    throw new Error("Runtime reset removed durable research");
  }

  await page.getByLabel(/输入“重置工作区”以确认/).fill("重置工作区");
  const workspaceResponse = page.waitForResponse((response) =>
    response.url().endsWith("/v1/workspaces/current/reset")
    && response.request().method() === "POST");
  await page.getByRole("button", { name: "确认重置整个工作区" }).click();
  const resetResponse = await workspaceResponse;
  const receipt = await resetResponse.json();
  if (resetResponse.status() !== 200 || receipt.status !== "reset"
      || receipt.workspace_id !== workspaceId
      || receipt.deleted?.backtest_jobs !== 2
      || receipt.deleted?.optimization_jobs !== 1
      || receipt.deleted?.research_tasks < 1
      || receipt.deleted?.artifacts < 1) {
    throw new Error(`browser Workspace reset failed: HTTP ${resetResponse.status()} ${receipt.detail ?? ""}`);
  }
  await page.getByRole("status").filter({ hasText: "工作区重置已完成" }).waitFor();
  const meAfter = await product("/api/auth/me");
  const automationAfter = await product("/api/product/data-center/automation");
  const tasksAfter = await product("/api/product/research/tasks");
  const jobsAfter = await product("/api/product/backtests?query=&status=&limit=20&offset=0");
  const optimizationAfter = await product(`/api/product/optimization-jobs/${optimizationId}`);
  const artifactsAfter = await product("/api/product/research/artifacts");
  if (meAfter.status !== 200 || meAfter.body.workspace?.workspace_id !== workspaceId
      || meAfter.body.subject !== meBefore.body.subject
      || meAfter.body.role !== meBefore.body.role
      || meAfter.body.workspace?.role !== meBefore.body.workspace?.role
      || automationAfter.status !== 200
      || JSON.stringify(automationAfter.body.automation?.config)
         !== JSON.stringify(automationBefore.body.automation.config)
      || tasksAfter.body.tasks?.some((item) => item.task_id === taskId)
      || jobIds.some((id) => jobsAfter.body.backtests?.some((item) => item.job_id === id))
      || optimizationAfter.status !== 404
      || artifactsAfter.body.artifacts?.some((item) => item.artifact_id === artifactId)) {
    throw new Error("Workspace reset did not preserve account/RBAC/global config or clear the exact graph");
  }

  const title = `Phase15-reset-research-${Date.now()}`;
  const created = await product("/api/product/research/tasks", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ title, objective: "Verify research can restart after browser Workspace reset." }),
  });
  const tasksAgain = await product("/api/product/research/tasks");
  if (created.status !== 201 || created.body.workspace_id !== workspaceId
      || !tasksAgain.body.tasks?.some((item) => item.task_id === created.body.task_id)) {
    throw new Error("new ResearchTask could not persist after browser reset");
  }
  if (offOrigin.length) throw new Error("browser requested an origin outside Frontend/Gateway");
  console.log(JSON.stringify({ result: "PASS", workspace_id: workspaceId,
    deleted: receipt.deleted, new_task_id: created.body.task_id,
    protected_identity: "subject/role/workspace_role/global_automation_config_equal",
    exact_removed_ids: [taskId, ...jobIds, optimizationId, artifactId],
    off_origin_requests: offOrigin.length }));
} finally {
  await browser.close();
}
