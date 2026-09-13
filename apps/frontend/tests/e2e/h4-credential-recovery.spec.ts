import {test,expect} from '@playwright/test';
test.skip(process.env.BYQ_H5_EVIDENCE !== '1','isolated Product stack required');
test('credential acknowledgement survives refresh without persisting the secret or writing twice',async({page})=>{
  await page.goto('/login');await page.getByLabel('用户名').fill('h5-browser');await page.getByLabel('密码').fill('test-password-123');
  await page.getByRole('button',{name:'进入'}).click();await expect(page).toHaveURL(/\/agent$/);
  await page.goto('/user/models');await page.getByRole('button',{name:'添加凭据',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await dialog.locator('.el-form-item').filter({hasText:'名称'}).locator('input').fill('Recovery '+Date.now());
  const secret='synthetic-h79-browser-secret-'+Date.now();
  await dialog.getByPlaceholder('写入后仅显示掩码').fill(secret);
  let identity='',writes=0;
  await page.route('**/api/product/settings/models/credentials',async route=>{
    if(route.request().method()!=='POST')return route.continue();
    writes++;const response=await route.fetch();expect(response.status()).toBe(201);
    identity=(await response.json()).credential.credential_id;await route.abort('failed');
  });
  await dialog.getByRole('button',{name:'安全保存'}).click();
  await expect(page.getByText('有一笔凭据操作尚未确认',{exact:true})).toBeVisible();
  const saved=await page.evaluate(()=>JSON.stringify({...localStorage}));
  expect(saved).not.toContain(secret);expect(saved).not.toContain('ciphertext');expect(saved).toContain('byq.credential-write.v1:');
  await page.reload();const response=page.waitForResponse(r=>r.url().includes('/models/credentials/receipts?'));
  await page.getByRole('button',{name:'核对原凭据操作',exact:true}).click();
  const receipt=await(await response).json();expect(receipt).toEqual({state:'confirmed',operation:'create',credential_id:identity,committed_version:1});
  await expect(page.getByText('有一笔凭据操作尚未确认',{exact:true})).toHaveCount(0);expect(writes).toBe(1);
  expect(await page.evaluate(()=>Object.keys(localStorage).filter(k=>k.startsWith('byq.credential-write.v1:')))).toEqual([]);
});

test('model profile creation recovers the original configuration after refresh',async({page})=>{
  await page.goto('/login');await page.getByLabel('用户名').fill('h5-browser');await page.getByLabel('密码').fill('test-password-123');
  await page.getByRole('button',{name:'进入'}).click();await expect(page).toHaveURL(/\/agent$/);
  const key='profile-browser-'+Date.now();
  await page.evaluate(async key=>{
    const r=await fetch('/api/product/settings/models/credentials',{method:'POST',credentials:'include',headers:{'content-type':'application/json'},
      body:JSON.stringify({provider:'deepseek',label:key,secret:'synthetic-profile-fixture',idempotency_key:key})});
    if(r.status!==201)throw Error('credential fixture failed');
  },key);
  await page.goto('/user/models');await page.getByRole('button',{name:'新建档案',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await dialog.locator('.el-form-item').filter({hasText:'档案名称'}).locator('input').fill(key);
  await dialog.getByPlaceholder('research-fast').fill(key);
  let identity='',writes=0,original:any;
  await page.route('**/api/product/settings/models/profiles',async route=>{
    writes++;original=route.request().postDataJSON();const response=await route.fetch();expect(response.status()).toBe(201);
    identity=(await response.json()).profile.profile_id;await route.abort('failed');
  });
  await dialog.getByRole('button',{name:'创建档案',exact:true}).click();
  await expect(page.getByText('有一笔模型档案创建尚未确认',{exact:true})).toBeVisible();await page.reload();
  const response=page.waitForResponse(r=>r.url().includes('/models/profiles/receipts?'));
  await page.getByRole('button',{name:'核对原模型档案',exact:true}).click();
  expect(await(await response).json()).toEqual({state:'confirmed',profile_id:identity,committed_version:1,input:original});
  await expect(page.getByText('有一笔模型档案创建尚未确认',{exact:true})).toHaveCount(0);expect(writes).toBe(1);
});
