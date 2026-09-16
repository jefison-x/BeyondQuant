import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';

test.skip(process.env.BYQ_H5_EVIDENCE !== '1', 'explicit isolated synthetic Product stack required');
test('historical demand survives lost receipt and materializes only the selected past', async ({page}) => {
  const errors:string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/login');
  await page.getByLabel('用户名').fill('h5-browser');
  await page.getByLabel('密码').fill('test-password-123');
  await page.getByRole('button',{name:'进入'}).click();
  await expect(page).toHaveURL(/\/agent$/);
  async function selectScope() {
    await page.goto('/stock-pool');
    await page.getByRole('button',{name:'新建股票池',exact:true}).click();
    await page.getByText('指数型股票池',{exact:true}).click();
    await page.getByText('固定历史快照',{exact:true}).click();
    await page.getByRole('combobox',{name:'指数',exact:true}).click();
    await page.getByRole('option').filter({hasText:'沪深300'}).click();
    await page.getByPlaceholder('选择历史截至日期').fill('2021-08-15');
    await page.getByPlaceholder('选择历史截至日期').press('Tab');
  }
  await selectScope();
  let originalId = '';
  await page.route('**/api/product/data-center/demands', async route => {
    const response = await route.fetch();
    expect(response.status()).toBe(202);
    originalId = (await response.json()).demand.demand_id;
    await route.abort('failed'); // real commit occurred; only browser acknowledgement is lost
  }, {times:1});
  await page.getByRole('button',{name:'准备历史成分',exact:true}).click();
  await expect(page.getByRole('button',{name:'查询准备进度',exact:true})).toBeEnabled();
  expect(originalId).toMatch(/^datademand_[0-9a-f]{32}$/);
  await page.reload();
  await selectScope();
  const readback = page.waitForResponse(r => r.url().endsWith('/data-center/demands/'+originalId));
  await page.getByRole('button',{name:'查询准备进度',exact:true}).click();
  expect((await (await readback).json()).demand.status).toBe('queued');
  execFileSync('docker',['exec','-e','BYQ_H5_EVIDENCE=1','byq-h5-backend-0913','python','/evidence/h5-index-fixture.py','prepare']);
  await page.getByRole('button',{name:'查询准备进度',exact:true}).click();
  await expect(page.getByText('该时点指数成分已验证，可创建固定历史快照；不表示历史调仓序列或行情已就绪',{exact:true})).toBeVisible();
  await page.getByPlaceholder('Pool name').fill('H5 synthetic historical pool');
  const created = page.waitForResponse(r => r.url().endsWith('/paper/index-pools') && r.request().method()==='POST');
  await page.getByRole('button',{name:'创建并生成快照',exact:true}).click();
  const response = await created;
  expect(response.ok()).toBeTruthy();
  const poolId = (await response.json()).pool.pool_id;
  execFileSync('docker',['exec','-e','BYQ_H5_EVIDENCE=1','byq-h5-backend-0913','python','/evidence/h5-index-fixture.py','materialize']);
  const detail = await page.evaluate(async id => (await fetch('/api/product/paper/pools/'+id,{credentials:'include'})).json(), poolId);
  expect(detail.pool.pool_type).toBe('index');
  expect(detail.pool.current_snapshot_id).toBeTruthy();
  expect(errors).toEqual([]);
});
