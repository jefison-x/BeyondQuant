/** Inspect the exact live training approval through Frontend/Gateway only. */
import { chromium } from "@playwright/test";

const origin = process.env.BYQ_REAL_BASE_URL;
const username = process.env.BYQ_E2E_ADMIN_USERNAME;
const password = process.env.BYQ_E2E_ADMIN_PASSWORD;
const fields = ["WATCH_ID", "TASK_ID", "STRATEGY_ID", "POOL_SNAPSHOT_ID", "SUBMISSION_KEY"];
const identities = fields.map((name) => process.env[`BYQ_PHASE15_${name}`]);
const approve = process.argv.includes("--approve");
const receiptOnly = process.argv.includes("--receipt-only");
const approvalId = process.env.BYQ_PHASE15_APPROVAL_ID;
const conversationId = process.env.BYQ_PHASE15_CONVERSATION_ID;
if (approve && receiptOnly) throw new Error("read-only receipt cannot approve");
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin ?? "") || !username || !password
    || identities.some((value) => !value)) throw new Error("exact isolated training approval context required");
if (approve && (process.env.BYQ_PHASE15_GOLDEN_C_MODEL_AUTHORIZED !== "1"
    || !/^agent_approval_[0-9a-f]{32}$/.test(approvalId ?? "")
    || !/^conversation_[0-9a-f]{32}$/.test(conversationId ?? ""))) {
  throw new Error("the bounded approval continuation requires explicit model authorization");
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
const requests = [];
page.on("request", (request) => requests.push(request.url()));
async function receipt() {
  const approval = (await page.evaluate(async (url) => {
    const response = await fetch(url);
    if (!response.ok) throw new Error("approval receipt read failed");
    return response.json();
  }, `${origin}/api/product/approvals/${approvalId}`)).approval;
  const watch = approval?.resource_preview;
  if (approval?.status !== "approved" || approval.continuation_status !== "submitted"
      || watch?.watch_id !== identities[0] || watch.idempotency_key !== identities[4]
      || watch.task_id !== identities[1] || watch.ml_strategy_artifact_id !== identities[2]
      || watch.stock_pool_snapshot_id !== identities[3]) throw new Error("exact approved receipt differs");
  if (watch.state !== "confirmed") return null;
  const study = await page.evaluate(async (url) => {
    const response = await fetch(url);
    if (!response.ok) throw new Error("study receipt read failed");
    return response.json();
  }, `${origin}/api/product/ml/studies/${identities[2]}`);
  const runs = study.training_runs?.runs;
  if (!Array.isArray(runs) || runs.length !== 2) throw new Error("expected baseline and one new TrainingJob");
  const details = [];
  for (const run of runs) {
    details.push((await page.evaluate(async (url) => (await fetch(url)).json(),
      `${origin}/api/product/ml/training-runs/${run.training_run_id}`)).training_run);
  }
  const matches = details.filter((run) => run?.idempotency_key === identities[4]);
  if (matches.length !== 1) throw new Error("exact accepted TrainingJob is not unique");
  const exact = matches[0];
  const runId = exact.training_run_id;
  if (!/^mlrun_[0-9a-f]{32}$/.test(runId ?? "") || exact?.task_id !== identities[1]
      || exact.ml_strategy_artifact_id !== identities[2] || exact.stock_pool_snapshot_id !== identities[3]
      || exact.idempotency_key !== identities[4]) throw new Error("accepted TrainingJob differs from frozen inputs");
  return runId;
}
try {
  await page.goto(`${origin}/login`, { waitUntil: "domcontentloaded" });
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: "进入" }).click();
  await page.waitForURL((url) => url.pathname !== "/login", { timeout: 15000 });
  if (receiptOnly) {
    const runId = await receipt();
    if (!runId) throw new Error("receipt is not confirmed");
    const offOrigin = requests.filter((url) => !url.startsWith(`${origin}/`) && url !== origin);
    if (offOrigin.length) throw new Error("browser requested outside Frontend/Gateway origin");
    console.log(JSON.stringify({ result: "PASS", receipt_only: true, decision_submitted: false,
      approval_id: approvalId, watch_id: identities[0], training_run_id: runId, continuation_status: "submitted",
      browser_requests: requests.length, off_origin_requests: offOrigin.length }));
  } else {
  if (approve) {
    await page.evaluate(async (url) => {
      const response = await fetch(url, { credentials: "include", headers: { Accept: "text/event-stream" } });
      if (!response.ok || !response.body || !response.headers.get("content-type")?.includes("text/event-stream")) {
        throw new Error("exact conversation workflow stream unavailable");
      }
      window.phase15Stream = { open: true, bytes: 0 };
      const reader = response.body.getReader();
      void (async () => {
        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            window.phase15Stream.bytes += value.length;
          }
        } finally { window.phase15Stream.open = false; }
      })();
    }, `${origin}/v1/workflows/${conversationId}/events`);
  }
  await page.getByRole("button", { name: /^待人工审批/ }).click();
  const row = page.locator(".approval-panel li").filter({ hasText: identities[0] });
  await row.waitFor({ timeout: 15000 });
  if (await row.count() !== 1) throw new Error("training approval is not unique");
  const text = await row.innerText();
  if (!identities.every((value) => text.includes(value))
      || !text.includes("开始机器学习训练")
      || await row.getByRole("button", { name: "批准", exact: true }).isDisabled()) {
    throw new Error("browser did not render an actionable exact frozen submission preview");
  }
  let runId;
  let continuationStatus;
  if (approve) {
    if (!await page.evaluate(() => window.phase15Stream?.open)) throw new Error("workflow stream closed before decision");
    const decisionResponse = page.waitForResponse((response) => response.url()
      === `${origin}/api/product/approvals/${approvalId}/decision`
      && response.request().method() === "POST", { timeout: 45000 });
    await row.getByRole("button", { name: "批准", exact: true }).click();
    const response = await decisionResponse;
    const decision = await response.json();
    if (response.status() !== 200 || decision.approval?.approval_id !== approvalId
        || decision.approval?.status !== "approved"
        || decision.approval?.continuation_status !== "submitted") {
      throw new Error(`decision/continuation not confirmed: HTTP ${response.status()}`);
    }
    continuationStatus = decision.approval.continuation_status;
    // Keep the browser's live conversation open until the domain receipt exists.
    // Closing its SSE beforehand can release the original ephemeral Agent session.
    const deadline = Date.now() + 180000;
    while (Date.now() < deadline) {
      if (!await page.evaluate(() => window.phase15Stream?.open)) throw new Error("workflow stream closed before receipt");
      runId = await receipt();
      if (runId) break;
      await page.waitForTimeout(500);
    }
    if (!runId) throw new Error("no exact TrainingJob receipt; do not repeat the decision or prompt");
  }
  const offOrigin = requests.filter((url) => !url.startsWith(`${origin}/`) && url !== origin);
  if (offOrigin.length) throw new Error("browser requested outside Frontend/Gateway origin");
  const stream = approve ? await page.evaluate(() => window.phase15Stream) : null;
  if (approve && (!stream?.open || !stream.bytes)) throw new Error("live workflow stream evidence missing");
  console.log(JSON.stringify({ result: "PASS", watch_id: identities[0],
    frozen_field_count: identities.length, browser_requests: requests.length,
    off_origin_requests: offOrigin.length, decision_submitted: approve,
    ...(approve ? { approval_id: approvalId, continuation_status: continuationStatus, training_run_id: runId,
      workflow_stream_open_until_receipt: stream.open, workflow_stream_bytes: stream.bytes } : {}) }));
  }
} finally {
  await browser.close();
}
