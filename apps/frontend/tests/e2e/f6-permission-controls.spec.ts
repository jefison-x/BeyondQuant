import { expect, test } from '@playwright/test';
import { selectContinuationStrategy } from './continuation-permission-controls';

// Offline UI contract samples only. All HTTP API responses are intercepted;
// this does not qualify durable Product grants, identity or live F6 execution.
const taskId = 'task_' + '1'.repeat(32);
const artifactId = 'artifact_' + '2'.repeat(32);
const profile = { profile_id: 'task-ready-read.v1', profile_version: 1, profile_sha256: 'a'.repeat(64) };
const limits = { max_provider_calls: 16, max_attempts: 16, max_concurrent: 1,
  max_input_bytes: 262144, max_total_input_bytes: 4194304, max_output_tokens: 8192,
  max_total_output_tokens: 131072, max_tool_payload_bytes: 65536,
  max_total_tool_payload_bytes: 1048576, max_tool_calls: 16, deadline_ms: 180000 };

for (const width of [1440, 390]) {
  test(`offline F6 permission controls and fixed profile at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    let authenticated = false;
    const user = { subject: 'offline-controls-user', role: 'user',
      workspace: { workspace_id: 'workspace_' + '5'.repeat(32), display_name: 'Offline fixture' } };
    let permission: Record<string, unknown> | null = null;
    const mutations: Array<Record<string, unknown>> = [];
    await page.route(/^https?:\/\/[^/]+\/(?:api|v1)\//, async route => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      let status = 200;
      let body: unknown = { conversations: [], sessions: [], artifacts: [], approvals: [] };
      if (path === '/api/auth/login') { authenticated = true; body = { user, session_id: 'offline-session' }; }
      else if (path === '/api/auth/me') { status = authenticated ? 200 : 401; body = authenticated ? user : { error: { message: 'unauthenticated' } }; }
      else if ((path.endsWith('/preferences') || path.endsWith('/appearance'))) body = { preferences: { schema_version: 'ui-preferences.v1', color_mode: 'light', accent_theme: 'emerald', version: 0, updated_at: null } };
      else if (path === '/api/product/research/tasks') body = { tasks: [{ task_id: taskId, owner_principal: user.subject, workspace_id: user.workspace.workspace_id, conversation_id: 'conversation_' + '3'.repeat(32), trace_id: 'byq-trace-' + '4'.repeat(32), title: 'Offline permission controls', status: 'planned', objective: 'No backend or model execution' }] };
      else if (path === '/api/product/research/artifacts') body = { artifacts: [{ artifact_id: artifactId, task_id: taskId, owner_principal: user.subject, workspace_id: user.workspace.workspace_id, kind: 'strategy_version', status: 'validated' }] };
      else if (path.endsWith('/continuation-permission')) {
        if (request.method() === 'POST') {
          const sent = request.postDataJSON();
          mutations.push(sent);
          permission = { schema_version: 'task-continuation-permission.v2', grant_version: 1,
            confirmation_id: sent.idempotency_key, execution_profile: profile, request_limits: limits,
            confirmed_artifact_ids: sent.confirmed_artifact_ids, max_turns: 1,
            turn_timeout_seconds: 86400, expires_at: '2099-01-01T00:00:00Z', revoked_at: null };
          status = 201;
        }
        body = { schema_version: 'task-continuation-permission.v2', task_id: taskId, permission,
          available_profile: { execution_profile: profile, request_limits: limits },
          request_state: { requests_reserved: 0, requests_remaining: 1, unconfirmed_requests: 0, request_usage: null, request_identity: null },
          can_start: false, blocked_reason: permission ? 'waiting_for_event' : 'permission_missing' };
      }
      await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.goto('/login');
    await page.getByLabel('用户名').fill(user.subject);
    await page.getByLabel('密码').fill('offline-password');
    await page.getByRole('button', { name: '进入' }).click();
    await expect(page).toHaveURL(/\/agent$/);
    await page.goto('/user/research');
    await page.getByRole('button', { name: '查看许可', exact: true }).click();
    const panel = page.getByRole('region', { name: '任务后台续接许可' });
    await expect(panel.getByRole('status')).toContainText('尚未授权');
    await expect(panel.getByRole('spinbutton')).toHaveCount(0);
    await selectContinuationStrategy(page, panel);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
    await panel.getByRole('button', { name: '保存单次请求许可' }).click();
    await expect(panel.getByText('请求档案：task-ready-read.v1 v1', { exact: false })).toBeVisible();
    await expect(panel.getByRole('button', { name: '保存单次请求许可' })).toHaveCount(0);
    expect(mutations).toHaveLength(1);
    expect(mutations[0]).toEqual({ idempotency_key: expect.any(String), confirmed_artifact_ids: [artifactId], execution_profile_id: 'task-ready-read.v1' });
  });
}
