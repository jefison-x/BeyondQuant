import { test, expect } from '@playwright/test';

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  test(`F6 completed original task and comparison are visible at ${viewport.width}px`, async ({ page, baseURL }, info) => {
    await page.setViewportSize(viewport);
    const origin = new URL(baseURL!).origin;
    const foreign: string[] = [], errors: string[] = [];
    page.on('request', request => {
      const url = new URL(request.url());
      if (['http:', 'https:'].includes(url.protocol) && url.origin !== origin) foreign.push(url.origin);
    });
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('/login');
    await page.getByLabel('用户名').fill('f6-chain-user');
    await page.getByLabel('密码').fill('test-password-123');
    await page.getByRole('button', { name: '进入' }).click();
    await expect(page).toHaveURL(/\/agent$/);
    await page.goto('/user/research');
    const taskRow = page.getByRole('row').filter({ hasText: 'F6 自动续接全链验收' });
    await expect(taskRow).toContainText('completed');
    await taskRow.getByRole('button', { name: '查看许可' }).click();
    const panel = page.getByRole('region', { name: '任务后台续接许可' });
    await expect(panel).toContainText('已预留：0');
    await expect(panel).toContainText('剩余回合：5');
    await panel.screenshot({ path: info.outputPath(`f6-settlement-${viewport.width}.png`) });
    const snapshot = await page.evaluate(async () => {
      const tasks = await (await fetch('/api/product/research/tasks', { credentials: 'include' })).json();
      const task = tasks.tasks.find((row: { title: string }) => row.title === 'F6 自动续接全链验收');
      const artifacts = await (await fetch('/api/product/research/artifacts', { credentials: 'include' })).json();
      return { task, report: artifacts.artifacts.find((row: { artifact_id: string }) => row.artifact_id === task.progress.completion_evidence[0]) };
    });
    expect(snapshot.task.status).toBe('completed');
    expect(snapshot.report.kind).toBe('research_report');
    expect(snapshot.report.status).toBe('validated');
    expect(snapshot.report.content.report_type).toBe('strategy_comparison');
    expect(snapshot.report.content.delta_total_return).toBe(snapshot.report.content.candidate.total_return - snapshot.report.content.baseline.total_return);
    expect(foreign).toEqual([]);
    expect(errors).toEqual([]);
  });
}
