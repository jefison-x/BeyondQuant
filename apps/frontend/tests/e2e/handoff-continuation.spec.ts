import { test, expect } from '@playwright/test';

test.skip(process.env.BYQ_H3_E2E !== '1', 'isolated H3 fixture and Backend test origin required');
for (const width of [1440, 390]) {
  test(`explicit handoff permission queues once and revocation prevents dispatch at ${width}px`, async ({ page, request }, info) => {
    const owner = process.env.BYQ_H3_BROWSER_USER ?? 'h3-browser-user';
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [], foreign: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', req => {
      const url = new URL(req.url());
      if (url.protocol.startsWith('http') && url.origin !== new URL(process.env.BYQ_REAL_BASE_URL!).origin) foreign.push(url.origin);
    });
    await page.goto('/login');
    await page.getByLabel('用户名').fill(owner);
    await page.getByLabel('密码').fill('test-password-123');
    await page.getByRole('button', { name: '进入' }).click();
    await expect(page).toHaveURL(/\/agent$/);
    await page.goto('/user/research');
    const row = page.getByRole('row').filter({ hasText: `H3 synthetic ${width}` });
    await row.getByRole('button', { name: '查看许可' }).click();
    const panel = page.getByRole('region', { name: '任务后台续接许可' });
    await expect(panel).toContainText('新许可允许在交接条件满足时接续原任务');
    await panel.getByRole('spinbutton').fill('8000000');
    await panel.getByText('选择已验证资产', { exact: true }).click();
    await page.getByRole('option').first().click();
    await page.keyboard.press('Escape');
    await panel.getByText('我确认上述任务、资产、额度与有效期，并允许按上述条件续接；实际执行仍须通过准入检查。', { exact: true }).click();
    await panel.getByRole('button', { name: '保存续接许可' }).click();
    await expect(panel).toContainText('总额度：8000000');
    const view = await page.evaluate(async (name) => {
      const body = await (await fetch('/api/product/research/tasks', { credentials: 'include' })).json();
      const task = body.tasks.find((t: { title: string }) => t.title === name);
      return (await fetch(`/api/product/research/tasks/${task.task_id}/continuation-permission`, { credentials: 'include' })).json();
    }, `H3 synthetic ${width}`);
    // Test-side trusted consumer only. Browser requests above use Product API;
    // no Adapter/model is started in this isolated grant/revoke test.
    const root = process.env.BYQ_H3_BACKEND_URL!;
    const headers = { 'x-byq-owner-principal': owner, 'x-byq-actor-principal': owner,
      'x-byq-workspace-id': view.permission.workspace_id };
    const peek = await request.post(`${root}/internal/task-continuation/${view.permission.conversation_id}/peek`, { headers });
    expect(peek.ok()).toBeTruthy();
    expect((await peek.json()).status).toBe('eligible');
    const claim = await request.post(`${root}/internal/task-continuation/${view.permission.conversation_id}/claim`, { headers });
    expect(claim.ok()).toBeTruthy();
    const intent = await claim.json();
    expect(intent.task_id).toBe(view.task_id);
    expect(intent.receipt.event_key).toMatch(/^handoff-v1:/);
    await row.getByRole('button', { name: '查看交接' }).click();
    const handoff = page.getByRole('region', { name: '任务交接状态' });
    await expect(handoff).toContainText('后台续接已排队');
    await handoff.screenshot({ path: info.outputPath(`h3-queued-${width}.png`) });
    await panel.getByRole('button', { name: '撤销后台续接许可' }).click();
    await expect(panel).toContainText('许可已撤销');
    const dispatch = await request.post(`${root}/internal/task-continuation/${view.task_id}/dispatch`, {
      headers, data: { reservation_id: intent.receipt.reservation_id },
    });
    expect(dispatch.ok()).toBeTruthy();
    expect((await dispatch.json()).dispatch).toBe(false);
    await page.reload();
    await row.getByRole('button', { name: '查看许可' }).click();
    await expect(panel).toContainText('许可已撤销');
    expect(errors).toEqual([]);
    expect(foreign).toEqual([]);
  });
}
