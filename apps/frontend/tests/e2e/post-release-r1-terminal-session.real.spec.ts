import { expect, test, type Page } from "@playwright/test";

const username = process.env.BYQ_R1_TEST_USERNAME;
const password = process.env.BYQ_R1_TEST_PASSWORD;
const sessionId = process.env.BYQ_R1_TERMINAL_SESSION_ID;

test.skip(!username || !password || !sessionId, "requires a dedicated read-only user and terminal session ID");

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("用户名").fill(username!);
  await page.getByLabel("密码").fill(password!);
  await page.getByRole("button", { name: "进入" }).click();
  await expect(page).toHaveURL(/\/agent$/);
}

test("R1 opens terminal history without reconnecting or writing, and offers a new conversation", async ({ page }) => {
  const streamRequests: string[] = [];
  const sessionWrites: string[] = [];
  page.on("request", request => {
    const url = new URL(request.url());
    if (url.pathname === `/v1/workflows/${encodeURIComponent(sessionId!)}/events`) streamRequests.push(request.url());
    if ((url.pathname.startsWith("/v1/agent/") || url.pathname.startsWith("/v1/workflows/"))
      && request.method() !== "GET") sessionWrites.push(`${request.method()} ${url.pathname}`);
  });

  await login(page);
  streamRequests.length = 0;
  sessionWrites.length = 0;
  const replayResponsePromise = page.waitForResponse(response => {
    const url = new URL(response.url());
    return response.request().method() === "GET" && url.pathname === `/v1/agent/sessions/${encodeURIComponent(sessionId!)}`;
  });
  await page.goto(`/agent?session=${encodeURIComponent(sessionId!)}`);
  const replayResponse = await replayResponsePromise;
  expect(replayResponse.ok()).toBe(true);
  const replay = await replayResponse.json() as {
    messages?: Array<{ role: string; content: string }>;
    conversation?: { session_id?: string };
  };
  expect(replay.conversation?.session_id).toBe(sessionId);
  const oldUserMessage = replay.messages?.find(message => message.role === "user" && message.content.trim());
  expect(oldUserMessage, "the supplied terminal session must contain a persisted user message").toBeTruthy();
  const visiblePart = oldUserMessage!.content.slice(0, 100);

  await expect(page.locator(".conversation-message.user .message-body").filter({ hasText: visiblePart }).first()).toBeVisible();
  await expect(page.getByText(/该会话已结束.*请新建会话继续/)).toBeVisible();
  await expect(page.getByRole("button", { name: "新投研对话" })).toBeVisible();
  await page.waitForTimeout(1_200);
  expect(streamRequests).toEqual([]);
  expect(sessionWrites).toEqual([]);
});
