import { test, expect } from '@playwright/test';

test.skip(process.env.BYQ_H4_E2E !== '1', 'isolated HTTP Product API fixture required');
test('HTTP research creation persists the exact task across reload', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/login');
  expect(await page.evaluate(() => typeof crypto.randomUUID)).toBe('undefined');
  await page.getByLabel('用户名').fill('mcp-contract');
  await page.getByLabel('密码').fill('test-password-123');
  await page.getByRole('button', { name: '进入' }).click();
  await expect(page).toHaveURL(/\/agent$/);
  await page.goto('/user/research');
  const title = `H4 HTTP ${Date.now()}`;
  await page.getByPlaceholder('任务名称', { exact: true }).fill(title);
  await page.getByPlaceholder('研究目标', { exact: true }).fill('Synthetic HTTP persistence verification');
  const created = page.waitForResponse(r => r.url().endsWith('/api/product/research/tasks') && r.request().method() === 'POST');
  await page.getByRole('button', { name: '创建任务', exact: true }).click();
  const response = await created;
  expect(response.ok()).toBeTruthy();
  const task = await response.json();
  expect(task.task_id).toMatch(/^task_[0-9a-f]{32}$/);
  await expect(page.getByRole('row').filter({ hasText: title })).toHaveCount(1);
  await page.reload();
  await expect(page.getByRole('row').filter({ hasText: title })).toHaveCount(1);
  const readback = await page.evaluate(async id => {
    const response = await fetch(`/api/product/research/tasks/${id}`, { credentials: 'include' });
    return response.json();
  }, task.task_id);
  expect(readback.task_id).toBe(task.task_id);
  expect(readback.title).toBe(title);
  expect(errors).toEqual([]);
});
