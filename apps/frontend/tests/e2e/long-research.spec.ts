import { test, expect } from '@playwright/test';

// Dedicated isolated fixture: long-research-user and long-research-{old,new}.
// Never point this acceptance scenario at a production deployment.
for (const width of [1440, 390]) {
  test(`long research permission preserves old and new deadlines at ${width}px`, async ({ page, baseURL }, info) => {
    if (!baseURL || !/^http:\/\/127\.0\.0\.1:18280$/.test(baseURL)) throw new Error('isolated long-research fixture required');
    await page.setViewportSize({width, height: 1000});
    const invalidRequests: string[] = [];
    page.on('request', request => {
      const url = new URL(request.url());
      if (['http:', 'https:'].includes(url.protocol) && (url.origin !== baseURL ||
        (['fetch', 'xhr'].includes(request.resourceType()) && !(/^\/api\/(product|auth)\//.test(url.pathname) || /^\/v1\/agent\/sessions(?:\/[^/]+)?$/.test(url.pathname))))) invalidRequests.push(url.pathname);
    });
    await page.goto('/login');
    await page.getByLabel('用户名').fill('long-research-user');
    await page.getByLabel('密码').fill('test-password-123');
    await page.getByRole('button', {name:'进入'}).click();
    await expect(page).toHaveURL(/\/agent$/);
    await page.goto('/user/research');
    await page.getByRole('row').filter({hasText:'long-research-old'}).getByRole('button',{name:'查看许可'}).click();
    const panel = page.getByRole('region',{name:'任务后台续接许可'});
    await expect(panel).toContainText('当前许可每回合期限：900 秒');
    await expect(panel).not.toContainText('每回合最多 15 分钟');
    await panel.screenshot({path:info.outputPath(`old-permission-${width}.png`)});
    await page.getByRole('row').filter({hasText:'long-research-new'}).getByRole('button',{name:'查看许可'}).click();
    if (width === 1440 && await panel.getByText('尚未授权', {exact:false}).count()) {
      await expect(panel).toContainText('尚未授权');
      await panel.getByRole('spinbutton').fill('2000000');
      await panel.getByText('选择已验证资产', {exact:true}).click();
      await page.getByRole('option').first().click();
      await page.keyboard.press('Escape');
      await panel.getByText('我确认上述任务、资产、额度与有效期；已保存许可不代表后台执行已启用。', {exact:true}).click();
      await expect(panel.getByRole('checkbox')).toBeChecked();
      const saved = page.waitForResponse(r => r.url().endsWith('/continuation-permission') && r.request().method() === 'POST');
      await panel.getByRole('button',{name:'保存续接许可'}).click();
      const response = await saved;
      expect(response.ok()).toBeTruthy();
      const value = await response.json();
      expect(value.permission.turn_timeout_seconds).toBe(86400);
      expect(value.permission.token_limit).toBe(2000000);
    }
    await expect(panel).toContainText('当前许可每回合期限：86400 秒');
    await page.reload();
    await page.getByRole('row').filter({hasText:'long-research-new'}).getByRole('button',{name:'查看许可'}).click();
    await expect(panel).toContainText('当前许可每回合期限：86400 秒');
    await panel.screenshot({path:info.outputPath(`new-permission-${width}.png`)});
    expect(invalidRequests).toEqual([]);
  });
}
