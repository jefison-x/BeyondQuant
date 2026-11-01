import { expect, test } from '@playwright/test';

// Offline UI contract samples only. All HTTP responses are intercepted;
// this does not qualify live F6 execution or durable Product state.
for (const width of [1440, 390]) {
  test(`offline F6 automatic continuation settings at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    let authenticated = false;
    const user = { subject: 'offline-controls-user', role: 'user',
      workspace: { workspace_id: 'workspace_' + '5'.repeat(32), display_name: 'Offline fixture' } };
    const conversationId = 'session-1';
    const options = {
      auto_continue: true,
      max_provider_calls: null, max_provider_attempts: null, max_tool_calls: null,
      max_concurrent_provider_calls: null, max_input_bytes_per_call: null,
      max_input_bytes_total: null, max_output_tokens_per_call: null,
      max_output_tokens_total: null, max_tool_payload_bytes_per_call: null,
      max_tool_payload_bytes_total: null, max_continuations: null,
      max_runtime_seconds: null, max_no_progress_seconds: null,
      max_child_runtime_seconds: null, max_child_no_progress_seconds: null,
    };
    let revision = 0;
    let currentOptions = options;
    const mutations: Array<Record<string, unknown>> = [];
    let permissionRequests = 0;
    await page.route(/^https?:\/\/[^/]+\/(?:api|v1)\//, async route => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      let status = 200;
      let body: unknown = { conversations: [], sessions: [], approvals: [], requests: [], total: 0 };
      if (path === '/api/auth/login') { authenticated = true; body = { user, session_id: 'offline-session' }; }
      else if (path === '/api/auth/me') { status = authenticated ? 200 : 401; body = authenticated ? user : { error: { message: 'unauthenticated' } }; }
      else if (path === '/v1/agent/sessions') body = { sessions: [{ session_id: conversationId, trace_id: 'trace-1', title: 'F6 会话' }], total: 1, limit: 50, offset: 0 };
      else if (path === '/api/product/settings/agent-execution-options') {
        if (request.method() === 'PUT') {
          const sent = request.postDataJSON();
          mutations.push(sent);
          if (sent.expected_revision !== revision) status = 409;
          else { revision += 1; currentOptions = sent.options; }
        }
        body = { schema_version: 'agent-execution-options.v1', scope: 'user',
          owner_principal: user.subject,
          revision, options: currentOptions, updated_at: null };
      }
      else if (path === '/api/product/settings/agent-policy') body = {
        platform_policy: { automation_enabled: false, paused: false, default_decision_mode: 'manual', max_auto_executions_per_hour: 20, max_auto_failures_per_hour: 3 },
        approval_inbox: { pending: 0 }, personal_policy: {}, rules: [], presets: [], audit: [],
      };
      else if (path.endsWith('/continuation-permission')) { permissionRequests += 1; status = 404; }
      await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.goto('/login');
    await page.getByLabel('用户名').fill(user.subject);
    await page.getByLabel('密码').fill('offline-password');
    await page.getByRole('button', { name: '进入' }).click();
    await expect(page).toHaveURL(/\/agent$/);
    await page.goto('/user/agent-policy');
    const settings = page.locator('.runtime-settings');
    await expect(settings.getByRole('heading', { name: 'Agent运行参数' })).toBeVisible();
    await expect(settings.getByText('自动接续默认开启', { exact: false })).toBeVisible();
    const autoContinue = settings.getByRole('switch', { name: '允许自动接续' });
    await expect(autoContinue).toBeChecked();
    await settings.locator('.setting-value .el-switch').click();
    await expect(autoContinue).not.toBeChecked();
    await settings.getByRole('button', { name: '保存参数' }).click();
    await expect(settings.getByText('用户运行参数已保存', { exact: false })).toBeVisible();
    expect(mutations).toEqual([{ schema_version: 'agent-execution-options.v1',
      expected_revision: 0, options: { ...options, auto_continue: false } }]);
    expect(permissionRequests).toBe(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
    await page.goto('/user/research');
    await expect(page.locator('.research-history').getByRole('heading', { name: '审批历史' })).toBeVisible();
    await expect(page.getByRole('button', { name: '保存单次请求许可' })).toHaveCount(0);
    expect(permissionRequests).toBe(0);
  });
}
