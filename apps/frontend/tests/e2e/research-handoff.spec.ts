import { test, expect } from '@playwright/test';

test.skip(process.env.BYQ_HANDOFF_E2E !== '1', 'requires isolated H2 fixture and real Product API');
for (const width of [1440, 390]) {
  test(`durable handoff does not claim an orphaned task is executing at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const failures: string[] = [], foreign: string[] = [];
    page.on('pageerror', error => failures.push(error.message));
    page.on('request', request => {
      const url = new URL(request.url());
      if (url.protocol.startsWith('http') && url.origin !== new URL(process.env.BYQ_REAL_BASE_URL!).origin) foreign.push(url.origin);
    });
    await page.goto('/login');
    await page.getByLabel('用户名').fill('budget-user');
    await page.getByLabel('密码').fill('test-password-123');
    await page.getByRole('button', { name: '进入' }).click();
    await expect(page).toHaveURL(/\/agent$/);
    await page.goto('/user/research');
    const row = page.getByRole('row').filter({ hasText: 'Synthetic permission' });
    await expect(row).toContainText('未完成');
    await row.getByRole('button', { name: '查看交接' }).click();
    const panel = page.getByRole('region', { name: '任务交接状态' });
    await expect(panel).toContainText('需要确认后台续接许可');
    await expect(panel).toContainText('No execution');
    await expect(panel).not.toContainText('后台续接已排队');
    await panel.screenshot({ path: info.outputPath(`handoff-${width}.png`) });
    await page.reload();
    await row.getByRole('button', { name: '查看交接' }).click();
    await expect(panel).toContainText('需要确认后台续接许可');
    await panel.getByRole('button', { name: '刷新交接状态' }).click();
    await expect(panel).toContainText('尚未授权后台续接');
    expect(failures).toEqual([]);
    expect(foreign).toEqual([]);
  });
}
