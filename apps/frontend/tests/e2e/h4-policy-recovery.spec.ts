import {test,expect} from '@playwright/test';
test.skip(process.env.BYQ_H5_EVIDENCE!=='1','isolated Product stack required');
test('all five personal policy commands recover after refresh without repeating writes',async({page})=>{
  await page.goto('/login');await page.getByLabel('用户名').fill('h5-browser');await page.getByLabel('密码').fill('test-password-123');
  await page.getByRole('button',{name:'进入'}).click();await expect(page).toHaveURL(/\/agent$/);await page.goto('/user/agent-policy');
  const name='Policy recovery '+Date.now(),writes:Array<{key:string;body:any}>=[];
  await page.route('**/api/product/settings/agent-policy**',async route=>{
    if(route.request().method()==='GET')return route.continue();
    const response=await route.fetch();expect(response.ok()).toBe(true);
    writes.push({key:route.request().postDataJSON().request_id,body:await response.json()});await route.abort('failed');
  });
  async function recover(operation:string){
    await expect(page.getByText('有一笔审批策略操作尚未确认',{exact:true})).toBeVisible();await page.reload();
    const response=page.waitForResponse(r=>r.url().includes('/agent-policy/receipts?'));
    await page.getByRole('button',{name:'核对原审批策略操作',exact:true}).click();
    const receipt=await(await response).json();expect(receipt.state).toBe('confirmed');expect(receipt.operation).toBe(operation);expect(receipt.request_id).toBe(writes.at(-1)!.key);
    await expect(page.getByText('有一笔审批策略操作尚未确认',{exact:true})).toHaveCount(0);return receipt;
  }
  await page.getByRole('button',{name:'新建规则',exact:true}).click();
  await page.getByRole('dialog').locator('.el-form-item').filter({hasText:'名称'}).locator('input').fill(name);
  await page.getByRole('button',{name:'保存规则',exact:true}).click();
  const created=await recover('rule_create'),id=created.result.rule_id;expect(created.result.version).toBe(1);
  await page.getByRole('row').filter({hasText:name}).getByRole('button',{name:'编辑',exact:true}).click();
  await page.getByRole('dialog').locator('.el-form-item').filter({hasText:'名称'}).locator('input').fill(name+' changed');
  await page.getByRole('button',{name:'保存规则',exact:true}).click();
  const updated=await recover('rule_update');expect(updated.result.rule_id).toBe(id);expect(updated.result.version).toBe(2);
  await page.getByRole('row').filter({hasText:name+' changed'}).getByRole('button',{name:'删除',exact:true}).click();
  await page.locator('.el-message-box__btns button').last().click();
  expect((await recover('rule_delete')).result).toEqual({rule_id:id,deleted:true});
  await page.locator('.preset-card').filter({hasText:'全部人工确认'}).getByRole('button',{name:'应用',exact:true}).click();
  await page.locator('.el-message-box__btns button').last().click();
  const preset=await recover('preset');expect(preset.result.preset_id).toBe('manual_safe');expect(preset.result.rules).toEqual([]);
  const settings=page.locator('.el-card').filter({has:page.getByText('个人审批偏好',{exact:true})});
  await settings.locator('.setting-item').filter({hasText:'个人暂停自动审批'}).locator('.el-switch').click();
  await settings.getByRole('button',{name:'保存',exact:true}).click();
  const saved=await recover('settings');expect(saved.result.paused).toBe(true);
  expect(writes).toHaveLength(5);expect(new Set(writes.map(v=>v.key)).size).toBe(5);
  const current=await page.evaluate(async()=>(await fetch('/api/product/settings/agent-policy',{credentials:'include'})).json());
  expect(current.rules).toEqual([]);expect(current.personal_policy.paused).toBe(true);
});
