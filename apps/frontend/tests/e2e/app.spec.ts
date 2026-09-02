import { expect, test, type Page } from "@playwright/test";

async function login(page: Page) {
  let meAuthenticated = false;
  await page.route("**/api/auth/login", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ user: { subject: "testuser" }, session_id: "session-test" }),
      headers: { "set-cookie": "byq_session=session-test; Path=/; HttpOnly; SameSite=Lax" },
    }),
  );
  await page.route("**/api/auth/me", (route) =>
    meAuthenticated
      ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ subject: "testuser", display_name: "量化小周" }) })
      : (meAuthenticated = true, route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ error: { message: "unauthenticated" } }) })),
  );
  await page.goto("/login");
  await page.getByLabel("用户名").fill("testuser");
  await page.getByLabel("密码").fill("password123");
  await page.getByRole("button", { name: "进入" }).click();
  await expect(page).toHaveURL(/\/agent$/);
}

async function loginAsAdmin(page: Page) {
  let meAuthenticated = false;
  await page.route("**/api/auth/login", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ user: { subject: "admin", role: "admin" }, session_id: "session-admin" }),
      headers: { "set-cookie": "byq_session=session-admin; Path=/; HttpOnly; SameSite=Lax" },
    }),
  );
  await page.route("**/api/auth/me", (route) =>
    meAuthenticated
      ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ subject: "admin", role: "admin" }) })
      : (meAuthenticated = true, route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ error: { message: "unauthenticated" } }) })),
  );
  await page.goto("/login");
  await page.getByLabel("用户名").fill("admin");
  await page.getByLabel("密码").fill("adminpass123");
  await page.getByRole("button", { name: "进入" }).click();
  await expect(page).toHaveURL(/\/agent$/);
}

function operationsPayload() {
  return {
    schema_version: "operations.v1",
    services: { gateway: "ready", backend: "ready", runtime_adapter: "ready" },
    database: { engine: "postgresql", status: "ready", name: "byq_domain", server_version: "16.9", size_bytes: 5242880, table_count: 30, estimated_rows: 120, domain_counts: [{ resource: "market_bars", count: 80 }], migration: { single_domain_store: "complete", legacy_sqlite_runtime: false } },
    cache: { kind: "postgresql_market_data", status: "ready", row_count: 80, redis: "not_used", groups: [{ data_source: "tushare", asset_type: "stock", symbol_count: 4, row_count: 80, date_min: "2026-01-01", date_max: "2026-08-22" }] },
    sources: { provider: "tushare", credential_metadata: [], configuration_scope: "phase_39", legacy_providers: [], secrets_exposed: false },
    models: { credential_metadata: [{ provider_key: "deepseek", scope: "system", status: "active", count: 1 }], profiles: 2, bindings: 1, secrets_exposed: false },
    agents: { status_groups: [{ role_id: "quant_orchestrator", status: "completed", count: 3 }], recent_runs: [] },
    graphs: { projection: "normalized_agent_runs", recent_runs: [], raw_dsh_events: false },
    access: { principal_groups: [{ role: "admin", status: "active", count: 1 }], agent_audit: [], operations_audit: [] },
    budget: { policy_id: "product-agent", enabled: false, alert_total_tokens: 400000, alert_requests: 48, version: 1, updated_by: "system-bootstrap", updated_at: "2026-08-22T00:00:00Z" },
    runtime: { schema_version: "runtime-operations.v1", runtime: { status: "ready", sdk: "deepseek-harness-sdk==0.1.1rc1", process_ownership: "one-per-active-session" }, sessions: { active: 1, active_prompts: 0, status_counts: { idle: 1 } }, usage: { input_tokens: 100, output_tokens: 20, cache_read_tokens: 30, cache_write_tokens: 0, reasoning_tokens: 10, model_calls: 1, total_tokens: 150, scope: "adapter_process_lifetime", source: "normalized_dsh_token_usage" }, raw_dsh_events: false },
    observability: { workflow_trace: "normalized", audit: "append_only", raw_dsh_events: false },
  };
}

async function mockAdminOps(page: Page) {
  await page.route("**/api/product/operations/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(operationsPayload()),
    }),
  );
  await page.route("**/api/product/data/status", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok", provider: "tushare", migration: "not_started", backend: "ok" }) }),
  );
  await page.route("**/api/product/data-center/status?*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: "data-center.v3", migration: "not_started", provider: "tushare", legacy_providers: [], quality: "empty", data_tasks: [],
        provider_budget: { schema_version: "provider-budget.v1", profile: "tushare-personal-2000", official_calls_per_minute: 200, official_calls_per_api_per_day: 100000, daily_rows_per_call: 6000, configured_request_interval_seconds: 0.34, actual_credential_tier_detected: false },
        source: { configured: false, effective_source: "none", credentials: [], encryption: { configured: true, status: "ready" }, secrets_exposed: false, can_manage: true },
        jobs: [], security_master_jobs: [], security_master: { schema_version: "security-master.v1", quality: "empty", latest_snapshot: null, total: 0, status_counts: { L: 0, P: 0, D: 0 }, exchange_counts: { SSE: 0, SZSE: 0, BSE: 0 } },
        coverage: { checked_at: "2026-08-24T00:00:00Z", provider: "tushare", scope: "persisted_observations", quality: "empty", completeness_claimed: false, row_count: 0, symbol_count: 0, source_issues: 0, ohlc_issues: 0, groups: [], symbols: [] },
        automation: { schema_version: "market-sync-automation.v1", config: { enabled: false, schedule_time: "18:30", timezone: "Asia/Shanghai", catchup_days: 7, security_master_enabled: true, datasets: ["trade_calendar", "stock_daily"], version: 1, updated_by: "system", updated_at: "2026-08-25T00:00:00Z" }, worker: { healthy: false, heartbeat_at: null, last_error: null }, latest_calendar_open_date: null, latest_complete_session: null, next_run_at: "2026-08-25T18:30:00+08:00", jobs: [], run_requests: [], index_catalog_sync_runs: [] },
        index_catalog: { schema_version: "index-catalogue.v1", total: 6, available_total: 0, indices: [] },
      }),
    }),
  );
  await page.route("**/api/product/settings/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        profile: { configured: true },
        model_provider: { configured: false },
        data_provider: { provider: "tushare", migration: "not_started" },
        storage: { status: "ready" },
        approval_inbox: { pending: 0 },
      }),
    }),
  );
  await page.route("**/api/product/health", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok", service: "byq-gateway" }) }),
  );
  await page.route("**/api/product/admin/users", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ users: [] }) }),
  );
  await page.route("**/api/product/approvals", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ approvals: [] }) }),
  );
}

async function openNav(page: Page, label: string) {
  const primary = page.getByRole("button", { name: label, exact: true });
  if (await primary.count()) {
    await primary.first().click();
    return;
  }
  await page.getByTitle(/用户设置/).click();
  await page.getByRole("menuitem", { name: label }).click();
}

async function mockResearchLists(page: Page) {
  await page.route("**/api/product/research/task-options?*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ tasks: [] }),
    }),
  );
  await page.route("**/api/product/research/tasks", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ tasks: [] }),
    }),
  );
  await page.route("**/api/product/research/artifacts", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ artifacts: [] }),
    }),
  );
  await page.route("**/api/product/approvals", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ approvals: [] }),
    }),
  );
  await page.route("**/api/product/strategies?*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ strategies: [], total: 0, limit: 50, offset: 0 }),
    }),
  );
  await page.route("**/api/product/backtests", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ backtests: [] }) }),
  );
}

test("login page requires username and password", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "BeyondQuant Next" })).toBeVisible();
  await page.getByRole("button", { name: "进入" }).click();
  await expect(page.getByText("请输入用户名和密码")).toBeVisible();
});

test("authenticated dashboard shows resource cards", async ({ page }) => {
  await page.route("**/api/product/dashboard", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ok", resources: { backend: "ok", data: "not_loaded", migration: "not_started" } }),
    }),
  );
  await login(page);
  await page.goto("/dashboard");
  await expect(page.getByText("核心服务", { exact: true }).first()).toBeVisible();
});

test("agent workbench renders a normalized BYQ workflow surface", async ({ page }) => {
  await page.route(/\/v1\/agent\/sessions(?:\?.*)?$/, (route) => {
    const session = { session_id: "session-1", trace_id: "trace-1", status: "ready" };
    return route.fulfill({
      status: route.request().method() === "POST" ? 201 : 200,
      contentType: "application/json",
      body: JSON.stringify(route.request().method() === "POST" ? session : { sessions: [session] }),
    });
  });
  await page.route("**/v1/workflows/session-1/events", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: 'data: {"trace_id":"trace-1","session_id":"session-1","sequence":1,"timestamp":"2026-08-22T00:00:00Z","kind":"agent.activity","source":"runtime-adapter","payload":{"schema_version":"workflow-activity.v1","activity_id":"activity_11111111111111111111111111111111","phase":"understand","state":"started","label":"理解请求"}}\n\n',
    }),
  );
  await page.route("**/v1/agent/sessions/session-1", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        conversation: { session_id: "session-1", trace_id: "trace-1", title: "动量研究", status: "active" },
        messages: [{ message_id: "m1", sequence: 1, role: "user", content: "研究动量", created_at: "2026-08-21T23:59:00Z" }],
        events: [
          { trace_id: "trace-1", session_id: "session-1", sequence: 1, timestamp: "2026-08-22T00:00:00Z", kind: "agent.activity", source: "runtime-adapter", payload: { schema_version: "workflow-activity.v1", activity_id: "activity_11111111111111111111111111111111", phase: "understand", state: "started", label: "理解请求" } },
          { trace_id: "trace-1", session_id: "session-1", sequence: 2, timestamp: "2026-08-22T00:00:01Z", kind: "agent.output.delta", source: "runtime-adapter", payload: { delta: "## 研究结论\n\n- 动量信号有效\n- 需要控制回撤\n\n[查看来源](https://example.com/report)" } },
        ],
      }),
    }),
  );
  await page.route("**/v1/agent/sessions/session-1/turns", async (route) => {
    expect((await route.request().postDataJSON()).content).toBe("快捷发送问题");
    await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ accepted: true }) });
  });
  await page.route("**/api/product/approvals", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ approvals: [{ approval_id: "agent_approval_1", action: "run_backtest", status: "pending" }] }),
    }),
  );
  await page.route("**/api/product/approvals/agent_approval_1/decision", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ approval: { approval_id: "agent_approval_1", status: "approved" } }),
    }),
  );
  await login(page);
  await expect(page.getByRole("heading", { name: "小巴投研" })).toBeVisible();
  await expect(page.getByText("BYQ 规范化工作流 · 持久会话")).toBeVisible();
  await expect(page.getByText("研究动量")).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 600 });
  const scrollLayout = await page.evaluate(() => {
    const content = document.querySelector<HTMLElement>(".content-area");
    const workspace = document.querySelector<HTMLElement>(".conversation-workspace");
    const canvas = document.querySelector<HTMLElement>(".conversation-canvas");
    if (!content || !workspace || !canvas) throw new Error("conversation layout is missing");
    return {
      contentClientHeight: content.clientHeight,
      contentScrollHeight: content.scrollHeight,
      contentOverflowY: getComputedStyle(content).overflowY,
      workspaceHeight: workspace.getBoundingClientRect().height,
      canvasOverflowY: getComputedStyle(canvas).overflowY,
    };
  });
  expect(scrollLayout.contentOverflowY).toBe("hidden");
  expect(scrollLayout.contentScrollHeight).toBe(scrollLayout.contentClientHeight);
  expect(Math.abs(scrollLayout.workspaceHeight - scrollLayout.contentClientHeight)).toBeLessThanOrEqual(1);
  expect(scrollLayout.canvasOverflowY).toBe("auto");
  await page.setViewportSize({ width: 1280, height: 720 });
  await expect(page.locator(".conversation-message.user .message-author")).toHaveText("量化小周");
  await expect(page.getByRole("heading", { name: "研究结论" })).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: "动量信号有效" })).toBeVisible();
  await expect(page.getByRole("link", { name: "查看来源" })).toHaveAttribute("rel", "noopener noreferrer nofollow");
  await expect(page.getByText("Ctrl + Enter 发送")).not.toBeVisible();
  await expect(page.getByText("关键执行仍需 BYQ 审批")).not.toBeVisible();
  await page.getByPlaceholder("向小巴描述你的投研问题…").fill("快捷发送问题");
  const textareaBox = await page.getByPlaceholder("向小巴描述你的投研问题…").boundingBox();
  const sendBox = await page.getByRole("button", { name: "发送", exact: true }).boundingBox();
  expect(textareaBox).not.toBeNull();
  expect(sendBox).not.toBeNull();
  expect(Math.abs((textareaBox!.y + textareaBox!.height / 2) - (sendBox!.y + sendBox!.height / 2))).toBeLessThanOrEqual(1);
  await page.getByPlaceholder("向小巴描述你的投研问题…").press("Control+Enter");
  await expect(page.locator(".assistant-processing")).toBeVisible();
  await expect(page.getByRole("button", { name: "停止本轮" })).toBeVisible();
  await page.getByRole("button", { name: /^活动/ }).click();
  await expect(page.getByLabel("公开执行进度").getByText("理解请求", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "通过" })).not.toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: /待人工审批，1 项/ }).click();
  await expect(page.getByRole("button", { name: "通过" })).toBeVisible();
});

test("selecting a recent conversation loads its replay without refreshing the page", async ({ page }) => {
  const sessions = [
    { session_id: "session-1", trace_id: "trace-1", title: "银行板块研究", status: "active", updated_at: "2026-08-27T10:00:00Z" },
    { session_id: "session-2", trace_id: "trace-2", title: "红利策略研究", status: "active", updated_at: "2026-08-27T09:00:00Z" },
  ];
  await page.route(/\/v1\/agent\/sessions(?:\?.*)?$/, (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ sessions, total: sessions.length }),
  }));
  for (const session of sessions) {
    await page.route(`**/v1/agent/sessions/${session.session_id}`, (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        conversation: session,
        messages: [{
          message_id: `message-${session.session_id}`,
          sequence: 1,
          role: "user",
          content: session.session_id === "session-1" ? "分析银行板块" : "分析红利策略",
          created_at: session.updated_at,
        }],
        events: [],
      }),
    }));
    await page.route(`**/v1/workflows/${session.session_id}/events`, (route) => route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: "",
    }));
  }

  await login(page);
  await expect(page.getByText("分析银行板块")).toBeVisible();
  await expect(page.locator(".history-row").first()).toHaveCSS("font-size", "14px");
  await expect(page.getByRole("button", { name: "对话历史", exact: true })).toHaveCSS("font-size", "12px");
  const historyBox = await page.locator(".history-list").boundingBox();
  const userBarBox = await page.locator(".sidebar-user-bar").boundingBox();
  expect(historyBox).not.toBeNull();
  expect(userBarBox).not.toBeNull();
  expect(Math.abs(userBarBox!.y - (historyBox!.y + historyBox!.height))).toBeLessThan(24);
  await page.getByText("红利策略研究", { exact: true }).click();
  await expect(page).toHaveURL(/\/agent\?session=session-2$/);
  await expect(page.getByText("分析红利策略")).toBeVisible();
  await expect(page.getByText("分析银行板块")).toHaveCount(0);
  const conversationHeader = page.locator(".conversation-header");
  await expect(conversationHeader.getByRole("button", { name: "历史", exact: true })).toHaveCount(0);
  await expect(conversationHeader.getByRole("button", { name: "会话操作", exact: true })).toHaveCount(0);
});

test("failed agent run unlocks the composer and resumes before retry", async ({ page }) => {
  const session = {
    session_id: "session-failed",
    trace_id: "trace-failed",
    title: "中断的投研会话",
    status: "active",
    updated_at: "2026-08-28T04:02:53Z",
  };
  const requestOrder: string[] = [];
  await page.route(/\/v1\/agent\/sessions(?:\?.*)?$/, (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ sessions: [session], total: 1 }),
  }));
  await page.route("**/v1/agent/sessions/session-failed", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      conversation: session,
      messages: [{
        message_id: "message-failed",
        sequence: 1,
        role: "user",
        content: "继续完成指数研究",
        created_at: "2026-08-28T04:02:50Z",
      }],
      events: [
        { trace_id: "trace-failed", session_id: "session-failed", sequence: 1, timestamp: "2026-08-28T04:02:50Z", kind: "session.started", source: "runtime-adapter", payload: {} },
        { trace_id: "trace-failed", session_id: "session-failed", sequence: 2, timestamp: "2026-08-28T04:02:51Z", kind: "agent.activity", source: "runtime-adapter", payload: { schema_version: "workflow-activity.v1", activity_id: "activity_failed111111111111111111111111", phase: "reason", state: "started", label: "分析市场数据" } },
        { trace_id: "trace-failed", session_id: "session-failed", sequence: 3, timestamp: "2026-08-28T04:02:53Z", kind: "session.failed", source: "runtime-adapter", payload: { code: "model-run-failed", retryable: true } },
      ],
    }),
  }));
  await page.route("**/v1/workflows/session-failed/events", (route) => route.fulfill({
    status: 200,
    contentType: "text/event-stream",
    body: ": heartbeat\n\n",
  }));
  await page.route("**/v1/agent/sessions/session-failed/resume", (route) => {
    requestOrder.push("resume");
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "idle" }) });
  });
  await page.route("**/v1/agent/sessions/session-failed/turns", (route) => {
    requestOrder.push("turn");
    return route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ accepted: true }) });
  });
  await page.route("**/api/product/approvals", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ approvals: [] }),
  }));

  await login(page);
  await expect(page.getByText("本轮运行未能完成，与你的问题表述无关。对话内容已保留，可以直接重试；若持续失败，请新建对话并联系管理员。")).toBeVisible();
  await expect(page.locator(".assistant-processing")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeDisabled();
  await page.getByPlaceholder("向小巴描述你的投研问题…").fill("重新尝试");
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect.poll(() => requestOrder).toEqual(["resume", "turn"]);
  await expect(page.getByRole("button", { name: "停止本轮" })).toBeVisible();
});

test("final answer replaces standalone progress before the terminal event arrives", async ({ page }) => {
  const session = {
    session_id: "session-answer-visible",
    trace_id: "trace-answer-visible",
    title: "回答收口复核",
    status: "active",
    updated_at: "2026-08-29T14:00:03Z",
  };
  await page.route(/\/v1\/agent\/sessions(?:\?.*)?$/, (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ sessions: [session], total: 1 }),
  }));
  await page.route("**/v1/agent/sessions/session-answer-visible", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      conversation: session,
      messages: [{
        message_id: "message-answer-question",
        sequence: 1,
        role: "user",
        content: "检查回答收口",
        created_at: "2026-08-29T14:00:00Z",
      }],
      events: [
        { trace_id: session.trace_id, session_id: session.session_id, sequence: 1, timestamp: "2026-08-29T14:00:01Z", kind: "session.started", source: "runtime-adapter", payload: {} },
        { trace_id: session.trace_id, session_id: session.session_id, sequence: 2, timestamp: "2026-08-29T14:00:02Z", kind: "agent.activity", source: "runtime-adapter", payload: { schema_version: "workflow-activity.v1", activity_id: "activity_answer_visible11111111111111111", phase: "reason", state: "started", label: "分析问题" } },
        { trace_id: session.trace_id, session_id: session.session_id, sequence: 3, timestamp: "2026-08-29T14:00:03Z", kind: "agent.output.delta", source: "runtime-adapter", payload: { delta: "最终回答已经可见" } },
      ],
    }),
  }));
  await page.route("**/v1/workflows/session-answer-visible/events", (route) => route.fulfill({
    status: 200,
    contentType: "text/event-stream",
    body: ": heartbeat\n\n",
  }));
  await page.route("**/api/product/approvals", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ approvals: [] }),
  }));

  await login(page);
  await expect(page.getByText("最终回答已经可见", { exact: true })).toBeVisible();
  await expect(page.locator(".assistant-processing")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "停止本轮" })).toBeVisible();
});

test("strategy workspace renders strategy version list and detail", async ({ page }) => {
  await mockResearchLists(page);
  await page.route("**/api/product/research/tasks", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ tasks: [{ task_id: "task_1" }] }) }),
  );
  await page.route("**/api/product/strategies?*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        strategies: [
          {
            artifact_id: "artifact_draft_1",
            kind: "strategy_draft",
            status: "draft",
            content: { snapshot: { strategy_id: "MomentumStrategy", script: "class CustomStrategy:\n    def generate_signals(self, data, parameters=None):\n        return {}" } },
            created_at: "2026-08-16T00:00:00+00:00",
          },
          {
            artifact_id: "artifact_version_1",
            kind: "strategy_version",
            status: "validated",
            content: { snapshot: { strategy_id: "MomentumStrategy", script: "class CustomStrategy:\n    def generate_signals(self, data, parameters=None):\n        return {}" } },
            created_at: "2026-08-16T00:00:00+00:00",
          },
          {
            artifact_id: "artifact_approval_1",
            kind: "strategy_approval",
            status: "validated",
            content: { strategy_version_artifact_id: "artifact_version_1", decision: "approved", execution_authorized: true },
            created_at: "2026-08-16T00:00:00+00:00",
          },
        ],
        total: 3,
        limit: 50,
        offset: 0,
      }),
    }),
  );
  await page.route("**/api/product/research/artifacts/artifact_version_1", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ artifact_id: "artifact_version_1", kind: "strategy_version" }) }),
  );
  await page.route("**/api/product/strategies/versions/artifact_version_1/approval", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        approval: {
          artifact_id: "artifact_approval_1",
          kind: "strategy_approval",
          status: "validated",
          content: { strategy_version_artifact_id: "artifact_version_1", decision: "approved", execution_authorized: true },
        },
      }),
    }),
  );
  await page.route("**/api/product/strategies/MomentumStrategy/versions", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ versions: [], total: 0 }),
    }),
  );
  await page.route("**/api/product/strategies/MomentumStrategy/backtest-count", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ backtest_count: 0, version_count: 1 }),
    }),
  );
  await page.route("**/api/product/research/artifacts", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        artifacts: [
          {
            artifact_id: "artifact_approval_1",
            kind: "strategy_approval",
            status: "validated",
            content: { strategy_version_artifact_id: "artifact_version_1", decision: "approved", execution_authorized: true },
            created_at: "2026-08-16T00:00:00+00:00",
          },
        ],
      }),
    }),
  );
  await login(page);
  await page.goto("/strategy?artifact=artifact_version_1&from=agent&session=session-1");
  await expect(page.getByRole("heading", { name: "策略管理" })).toBeVisible();
  await expect(page.getByText("策略目录与版本谱系", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "返回投研对话" })).toBeVisible();
  await expect(page.getByText("策略编辑器", { exact: true })).not.toBeVisible();
  await expect(page.getByText("技术与审计详情", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "已批准" })).toBeVisible();
  await expect(page.getByRole("button", { name: "开始回测" })).toBeEnabled();
  await page.getByRole("button", { name: "新建策略" }).click();
  await expect(page.getByText("策略编辑器", { exact: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "策略名称", exact: true })).toHaveValue("自定义策略");
  await expect(page.getByRole("textbox", { name: "数据依赖（JSON）", exact: true })).toHaveValue('{\n  "benchmark": "000300.SH"\n}');
});

test("backtest workspace renders backtest result list", async ({ page }) => {
  await mockResearchLists(page);
  let fullResultRequests = 0;
  await page.route(/\/api\/product\/backtests\?.*limit=20.*offset=0/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        backtests: [{ job_id: "backtest_1", status: "completed", summary: { total_return: 0.05, max_drawdown: 0.1, trade_count: 2 }, execution: { initial_capital: 100000 }, created_at: "2026-08-16T00:00:00+00:00" }],
        total: 1,
        limit: 20,
        offset: 0,
      }),
    }),
  );
  await page.route("**/api/product/backtests/backtest_1", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ job: { job_id: "backtest_1", status: "completed", summary: { total_return: 0.05, max_drawdown: 0.1, trade_count: 2 }, execution: { initial_capital: 100000 } } }),
    }),
  );
  await page.route("**/api/product/backtests/backtest_1/analysis?*", (route) => {
    const section = new URL(route.request().url()).searchParams.get("section");
    const analysis = section === "summary"
      ? { section, summary: { total_return: 0.05, max_drawdown: 0.1, trade_count: 1 } }
      : section === "chart"
        ? { section, series: { equity_curve: [{ trade_date: "2026-01-05", equity: 100000 }], benchmark_curve: [] } }
        : { section, page: { items: [], total: 0, limit: 50, offset: 0 } };
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ job_id: "backtest_1", analysis }),
    });
  });
  await page.route("**/api/product/backtests/backtest_1/result", (route) => {
    fullResultRequests += 1;
    return route.abort();
  });
  await page.route("**/api/product/backtests/options", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ options: [{
      strategy_version_artifact_id: "artifact_version_1", task_id: "task_1",
      approval_artifact_id: "artifact_approval_1", strategy_id: "MomentumStrategy",
      strategy_version_id: "version-1", benchmark_symbol: "000300.SH",
    }] }),
  }));
  await page.route("**/api/product/signal-snapshots", (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({ snapshots: [] }),
  }));
  await page.route("**/api/product/paper/pools", (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({ pools: [] }),
  }));
  await login(page);
  await page.goto("/backtest?job=backtest_1&from=agent&session=session-1");
  await expect(page.getByRole("heading", { name: "回测管理" })).toBeVisible();
  await expect(page.getByText("回测任务与完整结果", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "返回投研对话" })).toBeVisible();
  await expect(page.getByText("回测结果", { exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: "权益曲线" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "交易明细" })).toBeVisible();
  expect(fullResultRequests).toBe(0);
  await page.getByRole("button", { name: "新建回测" }).click();
  await page.getByRole("combobox", { name: "已批准策略版本" }).click();
  await page.getByRole("option", { name: /MomentumStrategy/ }).click();
  await expect(page.getByText("对比基准：沪深300（000300.SH）", { exact: true })).toBeVisible();
});

test("my space pages render profile, models, assets, and agent policy", async ({ page }) => {
  let appearance = { schema_version: "ui-preferences.v1", color_mode: "system", accent_theme: "emerald", version: 0, updated_at: null as string | null };
  await page.route("**/api/product/settings/appearance", async (route) => {
    if (route.request().method() === "PUT") {
      const payload = route.request().postDataJSON();
      appearance = { ...appearance, color_mode: payload.color_mode, accent_theme: payload.accent_theme, version: appearance.version + 1, updated_at: "2026-08-24T00:00:00Z" };
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ preferences: appearance }) });
  });
  await page.route("**/api/product/profile", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ profile: { subject: "testuser", display_name: "老李", preferences: "低波动", default_prompt: "先给结论", role: "user", status: "active" } }),
    }),
  );
  await page.route("**/api/product/settings/models", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        provider: "deepseek",
        providers: [
          { provider: "deepseek", display_name: "DeepSeek", credential_label: "DeepSeek API Key" },
          { provider: "opencode-go", display_name: "OpenCode Go", credential_label: "OpenCode Go API Key" },
          { provider: "opencode-zen", display_name: "OpenCode Zen", credential_label: "OpenCode Zen API Key" },
        ],
        configured: false,
        models: [
          { provider: "opencode-go", model: "deepseek-v4-flash", display_name: "DeepSeek V4 Flash", reasoning_supported: false },
          { provider: "opencode-zen", model: "gpt-5.6-sol", display_name: "GPT 5.6 Sol", reasoning_supported: true },
        ],
        agents: [], credential_items: [], profiles: [], bindings: [], audit: [],
        encryption: { configured: true, status: "ready" }, credentials: { masked: true, write_only: true },
      }),
    }),
  );
  await page.route("**/api/product/settings/assets", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ strategies: [], backtests: [], pools: [], paper_accounts: [], summary: { strategies: 0, backtests: 0, pools: 0, paper_accounts: 0 } }),
    }),
  );
  await page.route("**/api/product/settings/agent-policy", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        platform_policy: { automation_enabled: false, paused: false, default_decision_mode: "manual", max_auto_executions_per_hour: 20, max_auto_failures_per_hour: 3 },
        personal_policy: { automation_enabled: false, paused: false, default_decision_mode: "manual", max_auto_executions_per_hour: 20, max_auto_failures_per_hour: 3 },
        rules: [], presets: [{ preset_id: "manual_safe", name: "全部人工确认", description: "安全默认", rules: [] }], audit: [],
        approval_inbox: { pending: 0 },
      }),
    }),
  );
  await page.route("**/api/product/approvals", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ approvals: [] }) }),
  );

  await login(page);
  await openNav(page, "资产管理");
  await expect(page.getByRole("heading", { name: "资产管理" })).toBeVisible();
  await expect(page.getByText("导出资产包")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "用户中心导航" }).getByRole("link", { name: /模拟操盘/ })).toHaveCount(0);

  await page.getByRole("button", { name: "模拟操盘" }).click();
  await expect(page).toHaveURL(/\/paper-trading$/);
  await expect(page.getByRole("heading", { name: "模拟账户与交易监督" })).toBeVisible();

  await openNav(page, "模型配置");
  await expect(page.getByRole("heading", { name: "模型配置" })).toBeVisible();
  await expect(page.getByRole("button", { name: "添加凭据" })).toBeVisible();
  await page.getByRole("button", { name: "添加凭据" }).click();
  await page.getByRole("dialog").locator(".el-select").first().click();
  await page.getByRole("option", { name: "OpenCode Go" }).click();
  await expect(page.getByRole("dialog").getByText("OpenCode Go API Key", { exact: true })).toBeVisible();
  await expect(page.getByRole("dialog").getByLabel("名称")).toHaveValue("个人 OpenCode Go API");
  await page.getByRole("dialog").getByRole("button", { name: "取消" }).click();

  await openNav(page, "智能助手偏好");
  await expect(page.getByRole("heading", { name: "智能助手偏好" })).toBeVisible();
  await expect(page.getByRole("button", { name: "保存" })).toBeVisible();
  await expect(page.getByRole("button", { name: "新建规则" })).toBeVisible();

  await openNav(page, "个性化");
  await page.getByRole("button", { name: /^深色/ }).click();
  await page.getByRole("button", { name: "靛青" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-resolved-mode", "dark");
  await expect(page.locator("html")).toHaveAttribute("data-accent", "indigo");
  await page.getByRole("button", { name: "保存外观" }).click();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-resolved-mode", "dark");
  await expect(page.locator("html")).toHaveAttribute("data-accent", "indigo");

  await page.getByRole("link", { name: /个人资料/ }).click();
  await expect(page.getByLabel("昵称")).toHaveValue("老李");
});

test("paper trading and stock pool pages render", async ({ page }) => {
  await login(page);
  let paperAccountDeleted = false;
  await page.route("**/api/product/paper/pools", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ pools: [{
      pool_id: "stock_pool_1", name: "沪深300", pool_type: "index", description: "指数池",
      symbols: ["000001.SZ", "600000.SH"], weights: { "000001.SZ": 0.6 }, version: "v1",
      status: "active", created_at: "2026-08-16T00:00:00+00:00",
    }] }) }),
  );
  await page.route(/\/api\/product\/paper\/pools\/stock_pool_1$/, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ pool: {
      pool_id: "stock_pool_1", name: "沪深300", pool_type: "index", description: "指数池",
      symbols: ["000001.SZ", "600000.SH"], weights: { "000001.SZ": 0.6 }, version: "v1",
      status: "active", current_snapshot_id: "snapshot_1", metadata_version: 1, member_count: 2,
      snapshot: { snapshot_id: "snapshot_1", pool_id: "stock_pool_1", version_number: 1, membership_fingerprint: "sha256:pool", snapshot_fingerprint: "sha256:snapshot", definition: {}, provenance: { source: "tushare" }, weight_mode: "weighted", member_count: 2, members: [{ symbol: "000001.SZ", weight: "0.6" }, { symbol: "600000.SH", weight: "0.4" }], created_at: "2026-08-16T00:00:00+00:00" },
      created_at: "2026-08-16T00:00:00+00:00",
    } }) }),
  );
  await page.route("**/api/product/paper/pools/stock_pool_1/snapshots", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ snapshots: [] }) }),
  );
  await page.route("**/api/product/paper/pools/stock_pool_1/references", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ references: [] }) }),
  );
  await page.route("**/api/product/paper/accounts", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ accounts: paperAccountDeleted ? [] : [{ account_id: "paper_account_1", name: "sim", cash: 100000, status: "active" }] }),
    }),
  );
  await page.route("**/api/product/paper/accounts/paper_account_1/positions", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ positions: [] }) }),
  );
  await page.route("**/api/product/paper/accounts/paper_account_1/orders", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ orders: [] }) }),
  );
  await page.route("**/api/product/paper/accounts/paper_account_1/fills", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ fills: [] }) }),
  );
  await page.route("**/api/product/paper/accounts/paper_account_1/ledger", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ledger: [] }) }),
  );
  await page.route("**/api/product/paper/accounts/paper_account_1/snapshots", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ snapshots: [] }) }),
  );
  await page.route("**/api/product/paper/accounts/paper_account_1/controls", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ controls: { kill_switch_engaged: false, max_order_notional: null, version: 1 } }) }),
  );
  await page.route("**/api/product/paper/accounts/paper_account_1", (route) => {
    if (route.request().method() === "DELETE") {
      paperAccountDeleted = true;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ account_id: "paper_account_1", deleted: true }) });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ account: { account_id: "paper_account_1", name: "sim", cash: 100000, equity: 100000, version: 1, status: "active" } }) });
  });
  await openNav(page, "模拟操盘");
  await expect(page.getByRole("heading", { name: "模拟账户与交易监督" })).toBeVisible();
  await page.goto("/user/paper-trading?from=backtest&pool_snapshot=snapshot_1");
  await expect(page).toHaveURL(/\/paper-trading\?/);
  expect(new URL(page.url()).searchParams.get("from")).toBe("backtest");
  expect(new URL(page.url()).searchParams.get("pool_snapshot")).toBe("snapshot_1");
  await expect(page.getByText("sim", { exact: true })).toBeVisible();
  await expect(page.getByText("初始资金", { exact: true })).toBeVisible();
  await expect(page.getByTestId("paper-initial-cash")).toContainText("¥");
  await expect(page.getByRole("tab", { name: "资金流水" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "结算快照" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "风险与迁移" })).toBeVisible();
  await page.getByRole("button", { name: "删除账户", exact: true }).click();
  await page.getByRole("dialog", { name: "删除模拟账户" }).getByRole("button", { name: "删除", exact: true }).click();
  await expect(page.getByText("暂无模拟账户")).toBeVisible();
  await page.goto("/stock-pool?pool=stock_pool_1&from=agent&session=session-1");
  await expect(page.getByRole("heading", { name: "股票管理" })).toBeVisible();
  await expect(page.getByText("股票池目录与快照", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "返回投研对话" })).toBeVisible();
  await expect(page.getByRole("radio", { name: "指数" }).first()).toBeVisible();
  await expect(page.getByText("沪深300", { exact: true }).first()).toBeVisible();
});

test("operations page renders safe status projection", async ({ page }) => {
  await page.route("**/api/product/operations/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(operationsPayload()),
    }),
  );
  await loginAsAdmin(page);
  await page.goto("/settings/system/runtime");
  await expect(page.getByRole("heading", { name: "运行时" })).toBeVisible();
  await expect(page.getByText("deepseek-harness-sdk==0.1.1rc1")).toBeVisible();
});

test("admin operations workspace renders database and access sections", async ({ page }) => {
  await mockAdminOps(page);
  await loginAsAdmin(page);
  await page.goto("/settings/system/database");
  await expect(page.getByRole("heading", { name: "数据库" })).toBeVisible();
  await expect(page.getByText("byq_domain")).toBeVisible();

  await page.goto("/settings/system/access");
  await expect(page.getByRole("heading", { name: "访问控制" })).toBeVisible();
  await expect(page.getByText("admin · active")).toBeVisible();

  await page.goto("/admin/graphs");
  await expect(page).toHaveURL(/\/settings\/system\/workflow$/);
  await expect(page.getByRole("heading", { name: "工作流诊断" })).toBeVisible();
});

test("mocked UI navigation covers core product routes", async ({ page }) => {
  await page.route("**/api/product/dashboard", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ok", resources: { backend: "ok", data: "not_loaded", migration: "not_started" } }),
    }),
  );
  await page.route("**/api/product/profile", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ profile: { subject: "testuser", display_name: "老李", preferences: "低波动", default_prompt: "先给结论", role: "user", status: "active" } }),
    }),
  );
  await mockAdminOps(page);
  await mockResearchLists(page);
  await page.route("**/api/product/ml/workspace", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ tasks: [], pools: [], artifacts: [], training_runs: [], prediction_runs: [], backtests: [] }),
    }),
  );

  await loginAsAdmin(page);
  const primaryNavigation = page.getByRole("navigation", { name: "产品主导航" });
  await expect(primaryNavigation.locator(".nav-row")).toHaveText([
    "股票池管理",
    "策略管理",
    "模型研究",
    "回测管理",
    "模拟操盘",
  ]);
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: "工作台" })).toBeVisible();
  await page.goto("/agent");
  await expect(page.getByRole("heading", { name: "小巴投研" })).toBeVisible();
  await openNav(page, "策略管理");
  await expect(page.getByRole("heading", { name: "策略管理" })).toBeVisible();
  await expect(page.getByText("研究任务", { exact: true })).toBeVisible();
  await expect(page.getByText("策略 ID", { exact: true })).toBeVisible();
  await expect(page.getByText("策略名称", { exact: true })).toBeVisible();
  await expect(page.getByText("策略说明", { exact: true })).toBeVisible();
  await expect(page.getByText("参数默认值（JSON）", { exact: true })).toBeVisible();
  await expect(page.getByText("参数规范（JSON Schema）", { exact: true })).toBeVisible();
  await expect(page.getByText("数据依赖（JSON）", { exact: true })).toBeVisible();
  await expect(page.getByText("Python 策略脚本", { exact: true })).toBeVisible();
  await openNav(page, "模型研究");
  await expect(page).toHaveURL(/\/model-research$/);
  await expect(page.getByRole("heading", { name: "模型研究", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "模型研究目录与实验进程" })).toBeVisible();
  await expect(page.getByText("当前仅展示已验证、可审计的模型能力")).toBeVisible();
  await page.getByRole("button", { name: "新建模型研究" }).first().click();
  await expect(page.getByRole("dialog", { name: "新建模型研究" })).toBeVisible();
  await expect(page.getByRole("dialog", { name: "新建模型研究" }).getByText("LightGBM 收益排序", { exact: true })).toBeVisible();
  await expect(page.getByText("当前只开放通过运行验证的能力。")).toBeVisible();
  await page.getByRole("dialog", { name: "新建模型研究" }).getByRole("button", { name: "取消" }).click();
  await openNav(page, "个性化");
  await expect(page.getByRole("heading", { name: "外观与主题" }).first()).toBeVisible();
  await openNav(page, "系统设置");
  await expect(page).toHaveURL(/\/settings\/system\/overview\?returnTo=/);
  expect(new URL(page.url()).searchParams.get("returnTo")).toBe("/user/appearance");
  await expect(page.getByRole("dialog").getByRole("heading", { name: "系统概览" })).toBeVisible();
  const settingsNavigation = page.getByRole("navigation", { name: "系统设置导航" });
  await settingsNavigation.getByRole("button", { name: /数据管理/ }).click();
  await expect(
    page.getByRole("dialog").getByRole("heading", { name: "数据中心" }),
  ).toBeVisible();
  await page.getByRole("dialog").getByRole("tab", { name: "行情同步" }).click();
  await expect(page.getByText("未复权全市场日线", { exact: true })).toBeVisible();
  await expect(page.getByText("创建日线同步", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "关闭系统设置" }).click();
  await expect(page).toHaveURL(/\/user\/appearance$/);
  await openNav(page, "研究与审批");
  await expect(page.getByRole("heading", { name: "研究与审批" })).toBeVisible();
});

test("mobile shell uses a drawer and keeps account destinations reachable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);

  await page.getByRole("button", { name: "打开产品导航" }).click();
  await expect(page.getByRole("navigation", { name: "产品主导航" })).toBeVisible();
  await expect(page.getByText("对话历史", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "历史会话", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "对话历史", exact: true }).click();
  await expect(page).toHaveURL(/\/agent\?history=recent$/);
  await expect(page.getByRole("heading", { name: "历史会话" })).toBeVisible();
  await page.getByRole("heading", { name: "历史会话" }).locator("..").getByRole("button").click();
  await page.getByRole("button", { name: "打开产品导航" }).click();
  await page.getByRole("button", { name: "策略管理", exact: true }).click();
  await expect(page).toHaveURL(/\/strategy$/);

  await page.getByRole("button", { name: "打开产品导航" }).click();
  await page.getByTitle(/用户设置/).click();
  await expect(page.getByRole("menuitem", { name: "资产管理" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "系统设置" })).toHaveCount(0);
});

test("system settings entry is visible only to administrators", async ({ page }) => {
  await loginAsAdmin(page);
  await page.getByTitle(/用户设置/).click();
  await expect(page.getByRole("menuitem", { name: "系统设置" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "数据中心" })).toHaveCount(0);
  await expect(page.getByRole("menuitem", { name: "系统状态" })).toHaveCount(0);
});

test("normal users cannot open a direct system settings route", async ({ page }) => {
  await login(page);
  await page.goto("/settings/system/overview");
  await expect(page).toHaveURL(/\/agent$/);
  await expect(page.getByRole("dialog", { name: /系统设置/ })).toHaveCount(0);
});

test("unknown routes render a recoverable Product state instead of a blank shell", async ({ page }) => {
  await login(page);
  await page.goto("/route-that-does-not-exist");
  await expect(page.getByText("没有找到这个页面")).toBeVisible();
  await expect(page.getByRole("button", { name: "返回小巴" })).toBeVisible();
  await expect(page.locator("main")).toHaveCount(1);
});

test("durable profile edits require confirmation before navigation", async ({ page }) => {
  await page.route("**/api/product/profile", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ profile: { subject: "testuser", display_name: "研究员", preferences: "", default_prompt: "", role: "user", status: "active" } }),
  }));
  await mockResearchLists(page);
  await login(page);
  await page.goto("/user/profile");
  await page.getByLabel("昵称").fill("尚未保存的昵称");
  await expect(page.getByText("有未保存更改")).toBeVisible();

  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "策略管理", exact: true }).click();
  await expect(page).toHaveURL(/\/user\/profile$/);

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "策略管理", exact: true }).click();
  await expect(page).toHaveURL(/\/strategy$/);
});
