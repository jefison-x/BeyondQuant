import { readFileSync } from 'node:fs';
import { test, expect } from '@playwright/test';
import { F6_BROWSER_LOGIN_PATH, f6AuthResponse, f6BrowserRoute, f6BrowserWriteAllowed, f6TaskRecordColumn, f6TaskRecordLabel, readF6Snapshot } from './f6-browser-observer';

type F6Evidence = {
  status: string;
  identities: Record<string, string>;
  structured_agent_audits: Record<string, {
    runtime_root_id: string;
    agent_run_id: string;
    owner_principal: string;
    workspace_id: string;
    session_id: string;
    trace_id: string;
    terminal: string;
    audit_events: Array<Record<string, string | null>>;
    settlement_status: string | null;
  }>;
};

function currentF6Evidence(): F6Evidence {
  const path = process.env.BYQ_F6_EVIDENCE_PATH;
  if (!path) throw new Error('BYQ_F6_EVIDENCE_PATH is required for current F6 browser acceptance');
  return JSON.parse(readFileSync(path, 'utf8')) as F6Evidence;
}


for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  test(`F6 exact settled read-only request and durable signal result at ${viewport.width}px`, async ({ page, baseURL }, info) => {
    const evidence = currentF6Evidence();
    expect(evidence.status).toBe('passed');
    const ids = evidence.identities;
    for (const key of [
      'conversation_id', 'trace_id', 'task_id', 'strategy_version_artifact_id', 'backtest_task_id',
      'signal_job_id', 'signal_snapshot_artifact_id', 'background_runtime_root_id', 'background_agent_run_id',
    ]) expect(ids[key]).toBeTruthy();
    const audits = evidence.structured_agent_audits;
    expect(Object.keys(audits).sort()).toEqual(['background', 'fg1', 'fg2']);
    expect(audits.background).toMatchObject({
      runtime_root_id: ids.background_runtime_root_id,
      agent_run_id: ids.background_agent_run_id,
      owner_principal: 'f6-chain-user',
      session_id: expect.stringMatching(/^byq-session-[0-9a-f]{32}$/),
      trace_id: ids.trace_id,
      terminal: 'completed/closed',
      settlement_status: 'settled',
    });
    expect(audits.background.audit_events).toEqual(expect.arrayContaining([
      { action: 'byq_research_get', outcome: 'authorized', resource_type: 'research_task', resource_id: ids.task_id },
      { action: 'byq_research_get', outcome: 'success', resource_type: 'research_task', resource_id: ids.task_id },
      { action: 'byq_backtest_task_get', outcome: 'authorized', resource_type: 'backtest_task', resource_id: ids.backtest_task_id },
      { action: 'byq_backtest_task_get', outcome: 'success', resource_type: 'backtest_task', resource_id: ids.backtest_task_id },
    ]));

    await page.setViewportSize(viewport);
    const origin = new URL(baseURL!).origin;
    const foreign: string[] = [];
    const writes: string[] = [];
    const errors: string[] = [];
    const authResponses: Array<{ step: 'login' | 'me'; status: number }> = [];
    let authResponseOverflow = false;
    let loginStatus: number | 'not_observed' = 'not_observed';
    page.on('request', request => {
      const url = new URL(request.url());
      if (['http:', 'https:'].includes(url.protocol) && url.origin !== origin) foreign.push(url.origin);
      if (!f6BrowserWriteAllowed(request.method(), url.pathname)) {
        writes.push(`${request.method()} ${url.pathname}`);
      }
    });
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', response => {
      const url = new URL(response.url());
      if (url.origin !== origin) return;
      const record = f6AuthResponse(response.request().method(), url.pathname, response.status());
      if (!record) return;
      if (authResponses.length < 8) authResponses.push(record);
      else authResponseOverflow = true;
    });

    const target = `/agent?session=${encodeURIComponent(ids.conversation_id)}`;
    await page.goto(`/login?redirect=${encodeURIComponent(target)}`);
    await page.getByLabel('用户名').fill('f6-chain-user');
    await page.getByLabel('密码').fill('test-password-123');
    try {
      const [loginResponse] = await Promise.all([
        page.waitForResponse(response => new URL(response.url()).origin === origin
          && new URL(response.url()).pathname === F6_BROWSER_LOGIN_PATH
          && response.request().method() === 'POST', { timeout: 5000 }),
        page.getByRole('button', { name: '进入' }).click(),
      ]);
      loginStatus = loginResponse.status();
      expect(loginStatus, 'one browser login HTTP result').toBe(200);
      await expect(page).toHaveURL(/\/agent\?session=/);
    } finally {
      // CI uploads only redacted console output, so preserve closed auth facts
      // before assertions terminate the page. Never log bodies, URLs or cookies.
      console.info('F6 browser auth diagnostics: ' + JSON.stringify({
        schema_version: 'f6-browser-auth.v1', viewport_width: viewport.width,
        login_status: loginStatus, responses: authResponses, overflow: authResponseOverflow,
        route: f6BrowserRoute(new URL(page.url()).pathname),
        page_error_count: Math.min(errors.length, 8),
        unexpected_write_count: Math.min(writes.length, 8),
      }));
    }
    let authorityConfirmed = false;
    let observerStage = 'answer';
    try {
      const transcript = page.locator('.conversation-message.agent .message-body');
      await expect.poll(async () => (await transcript.allTextContents()).some(text =>
        text.includes(ids.task_id) && text.includes(ids.backtest_task_id)
        && text.includes(ids.signal_job_id) && text.includes(ids.signal_snapshot_artifact_id)
        && text.includes('No domain writes were made.'))).toBe(true);
      await page.screenshot({ path: info.outputPath(`f6-readonly-answer-${viewport.width}.png`), fullPage: true });

      observerStage = 'structured_snapshot';
      expect(foreign).toEqual([]);
      expect(writes).toEqual([]);
      expect(errors).toEqual([]);
      const snapshot = await readF6Snapshot(page, ids);
      expect(snapshot.task).toMatchObject({
        task_id: ids.task_id, owner_principal: 'f6-chain-user', conversation_id: ids.conversation_id,
        trace_id: ids.trace_id,
      });
      expect(snapshot.task.status).not.toBe('completed');
      f6TaskRecordLabel(snapshot.task.status);
      expect(snapshot.job).toMatchObject({
        job_id: ids.signal_job_id, task_id: ids.task_id, status: 'completed',
        strategy_version_artifact_id: ids.strategy_version_artifact_id,
        result_artifact_id: ids.signal_snapshot_artifact_id,
      });
      expect(snapshot.artifact).toMatchObject({
        artifact_id: ids.signal_snapshot_artifact_id, task_id: ids.task_id,
        kind: 'signal_snapshot', status: 'validated',
      });
      expect(snapshot.permission).toMatchObject({ schema_version: 'task-continuation-permission.v2', task_id: ids.task_id });
      expect(snapshot.permission.permission).toMatchObject({ grant_version: 1 });
      expect(snapshot.permission.permission.revoked_at).toBeTruthy();
      expect(snapshot.permission.request_state).toMatchObject({ requests_reserved: 1, requests_remaining: 0, unconfirmed_requests: 0 });
      expect(snapshot.permission.request_state.request_identity).toMatchObject({
        status: 'settled', dispatch_attempts: 1, run_id: ids.background_runtime_root_id,
      });
      expect(snapshot.permission.request_state.request_usage.actual_usage).toEqual({
        input_tokens: 'unknown', cache_read_tokens: 'unknown', output_tokens: 'unknown',
        provider_attempts: 'unknown', usage_source: 'unknown', completeness: 'unknown',
      });
      expect(snapshot.conversation.conversation).toMatchObject({
        session_id: ids.conversation_id, trace_id: ids.trace_id,
      });
      expect(snapshot.conversation.messages.some((message: { role: string; content: string }) =>
        message.role === 'assistant' && message.content.includes(ids.task_id)
        && message.content.includes(ids.backtest_task_id) && message.content.includes(ids.signal_snapshot_artifact_id)
        && message.content.includes('No domain writes were made.'))).toBe(true);
      authorityConfirmed = true;
      observerStage = 'task_record';
      await page.goto('/user/research');
      const taskRow = page.getByRole('row').filter({ hasText: ids.task_id });
      await expect(taskRow).toHaveCount(1);
      await expect(taskRow).toBeVisible();
      const recordColumn = f6TaskRecordColumn(await page.getByRole('columnheader').allTextContents());
      await expect(taskRow.getByRole('cell').nth(recordColumn)).toHaveText(f6TaskRecordLabel(snapshot.task.status));
      observerStage = 'permission_panel';
      await taskRow.getByRole('button', { name: '查看许可' }).click();
      const panel = page.getByRole('region', { name: '任务后台续接许可' });
      await expect(panel).toContainText('task-ready-read.v1');
      await expect(panel).toContainText('已预留请求：1；剩余请求：0；未确认请求：0');
      await expect(panel).toContainText('实际用量：输入 未知 token，缓存读取 未知 token');
      await expect(panel).toContainText('输出 未知 token；模型尝试 未知 次；完整性：未知');
      await expect(panel).toContainText('许可已撤销，不会启动新的后台请求。');
      await expect(panel.getByRole('button', { name: '撤销后台续接许可' })).toHaveCount(0);
      await panel.screenshot({ path: info.outputPath(`f6-settlement-${viewport.width}.png`) });

      observerStage = 'safety';
      expect(foreign).toEqual([]);
      expect(writes).toEqual([]);
      expect(errors).toEqual([]);
    } catch (error) {
      // Save closed facts first. Preserve the original failure after a bounded,
      // read-only reconciliation only when exact authority and no side effects
      // were already confirmed. Never re-login, reconnect, or replay a command.
      const safeToReconcile = () => authorityConfirmed && loginStatus === 200
        && foreign.length === 0 && writes.length === 0 && errors.length === 0 && !page.isClosed();
      console.info('F6 browser observer failure: ' + JSON.stringify({
        schema_version: 'f6-browser-observer-failure.v1', viewport_width: viewport.width,
        stage: observerStage, authority_confirmed: authorityConfirmed,
        safe_to_reconcile: safeToReconcile(),
        unexpected_write_count: Math.min(writes.length, 8), foreign_request_count: Math.min(foreign.length, 8),
        page_error_count: Math.min(errors.length, 8),
      }));
      const logStoppedReconciliation = () => console.info(
        'F6 browser read-only reconciliation: ' + JSON.stringify({
          schema_version: 'f6-browser-reconciliation.v1', viewport_width: viewport.width,
          status: 'stopped_safety_changed_not_replayed',
          unexpected_write_count: Math.min(writes.length, 8), foreign_request_count: Math.min(foreign.length, 8),
          page_error_count: Math.min(errors.length, 8), page_closed: page.isClosed(),
        }));
      if (safeToReconcile()) {
        await page.screenshot({ path: info.outputPath(`f6-observer-failure-${viewport.width}.png`),
          fullPage: true, timeout: 1000 }).catch(() => undefined);
        if (!safeToReconcile()) {
          logStoppedReconciliation();
        } else try {
          const observed = await readF6Snapshot(page, ids);
          if (!safeToReconcile()) {
            logStoppedReconciliation();
          } else console.info('F6 browser read-only reconciliation: ' + JSON.stringify({
            schema_version: 'f6-browser-reconciliation.v1', viewport_width: viewport.width,
            status: 'observed_not_a_pass',
            conversation_identity_matches: observed.conversation?.conversation?.session_id === ids.conversation_id
              && observed.conversation?.conversation?.trace_id === ids.trace_id,
            task_identity_matches: observed.task?.task_id === ids.task_id,
            task_status: ['planned', 'running', 'completed', 'failed', 'cancelled'].includes(observed.task?.status)
              ? observed.task.status : 'unknown',
            job_identity_matches: observed.job?.job_id === ids.signal_job_id,
            job_completed: observed.job?.status === 'completed',
            artifact_identity_matches: observed.artifact?.artifact_id === ids.signal_snapshot_artifact_id,
            request_root_matches: observed.permission?.request_state?.request_identity?.run_id === ids.background_runtime_root_id,
            request_settled: observed.permission?.request_state?.request_identity?.status === 'settled',
            no_unconfirmed_requests: observed.permission?.request_state?.unconfirmed_requests === 0,
            permission_revoked: !!observed.permission?.permission?.revoked_at,
            answer_persisted: Array.isArray(observed.conversation?.messages)
              && observed.conversation.messages.some((message: { role: string; content: string }) =>
                message.role === 'assistant' && typeof message.content === 'string'
                && message.content.includes(ids.task_id) && message.content.includes(ids.signal_snapshot_artifact_id)
                && message.content.includes('No domain writes were made.')),
          }));
        } catch {
          if (!safeToReconcile()) {
            logStoppedReconciliation();
          } else console.info('F6 browser read-only reconciliation: ' + JSON.stringify({
            schema_version: 'f6-browser-reconciliation.v1', viewport_width: viewport.width,
            status: 'unavailable_not_replayed',
          }));
        }
      }
      throw error;
    }
  });
}
