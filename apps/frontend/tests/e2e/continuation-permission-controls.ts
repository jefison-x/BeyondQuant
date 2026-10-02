import { expect, type Locator, type Page } from '@playwright/test';

// Element Plus places the clickable placeholder over its readonly combobox
// input. Exercise the visible control without force or DOM mutation.
export async function selectContinuationStrategy(page: Page, panel: Locator) {
  await panel.getByText('选择已验证策略版本', { exact: true }).click();
  await page.getByRole('option', { name: /^strategy_version ·/ }).click();
  await panel.getByRole('combobox').press('Escape');
  await panel.getByText('我确认任务、所选策略版本和系统显示的请求档案，并允许该许可按有效交接执行一次只读研究请求。', { exact: true }).click();
  await expect(panel.getByRole('checkbox')).toBeChecked();
}
