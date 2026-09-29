/** Read-only browser replay of Product research created after Workspace reset. */
import { chromium } from "@playwright/test";

const origin = process.env.BYQ_REAL_BASE_URL;
const scope = process.env.BYQ_DEV_SCOPE;
const username = process.env.BYQ_E2E_ADMIN_USERNAME;
const password = process.env.BYQ_E2E_ADMIN_PASSWORD;
const conversationId = process.env.BYQ_PHASE15_POST_RESET_CONVERSATION_ID;
const artifactId = process.env.BYQ_PHASE15_POST_RESET_ARTIFACT_ID;
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin ?? "")
    || !/^byq-dev-[0-9a-f]{10}$/.test(scope ?? "") || !username || !password
    || !/^conversation_[0-9a-f]{32}$/.test(conversationId ?? "")
    || !/^artifact_[0-9a-f]{32}$/.test(artifactId ?? "")) {
  throw new Error("exact isolated post-reset research context required");
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
const offOrigin = [];
page.on("request", (request) => {
  const url = new URL(request.url());
  if (["http:", "https:"].includes(url.protocol) && url.origin !== origin) offOrigin.push(url.origin);
});
try {
  await page.goto(`${origin}/login`);
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: "进入" }).click();
  await page.waitForURL((url) => url.pathname !== "/login", { timeout: 15000 });

  await page.goto(`${origin}/agent?session=${encodeURIComponent(conversationId)}`);
  await page.waitForFunction(() => {
    const content = document.body.innerText;
    return content.includes("9.21") && content.includes("信息披露");
  }, undefined, { timeout: 20000 });
  const replay = await page.evaluate(async (id) => {
    const response = await fetch(`/v1/agent/sessions/${id}`, { credentials: "include" });
    if (!response.ok) throw new Error("Product conversation replay failed");
    return response.json();
  }, conversationId);
  if (replay.conversation?.session_id !== conversationId
      || replay.messages?.map((item) => item.role).join(",") !== "user,assistant,user,assistant") {
    throw new Error("post-reset two-turn research replay is inconsistent");
  }

  await page.goto(`${origin}/user/research`);
  await page.getByRole("tab", { name: "研究资产" }).click();
  await page.getByPlaceholder("筛选资产类型、编号或状态").fill(artifactId);
  await page.getByRole("row", { name: new RegExp(artifactId) }).waitFor({ timeout: 10000 });
  if (offOrigin.length) throw new Error("browser requested an origin outside Frontend/Gateway");
  console.log(JSON.stringify({ result: "PASS", conversation_id: conversationId,
    artifact_id: artifactId, turns: 2, off_origin_requests: 0 }));
} finally {
  await browser.close();
}
