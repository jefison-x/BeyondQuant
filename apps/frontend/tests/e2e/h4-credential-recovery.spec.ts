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

test('binding and profile deletion recover their original command after lost acknowledgements',async({page})=>{
  await page.goto('/login');await page.getByLabel('用户名').fill('h5-browser');await page.getByLabel('密码').fill('test-password-123');
  await page.getByRole('button',{name:'进入'}).click();await expect(page).toHaveURL(/\/agent$/);
  const name='Command recovery '+Date.now();
  const profile=await page.evaluate(async name=>{
    const post=async(path:string,payload:unknown)=>{
      const r=await fetch('/api/product/settings/models/'+path,{method:'POST',credentials:'include',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
      if(r.status!==201)throw Error('model fixture failed');return r.json();
    };
    const {credential}=await post('credentials',{provider:'deepseek',label:name,secret:'synthetic-command-fixture',idempotency_key:name});
    return (await post('profiles',{credential_id:credential.credential_id,key_name:name,display_name:name,provider:'deepseek',model:'deepseek-v4-flash',temperature:0.2,reasoning_enabled:false})).profile;
  },name);
  let bindingWrites=0,deleteWrites=0,bindingVersion=0;
  await page.goto('/user/models');
  await page.route('**/api/product/settings/models/bindings/byq-product',async route=>{
    bindingWrites++;const r=await route.fetch();expect(r.status()).toBe(200);bindingVersion=(await r.json()).binding.version;await route.abort('failed');
  });
  await page.locator('.binding-row .el-select__wrapper').scrollIntoViewIfNeeded();
  await page.locator('.binding-row .el-select__wrapper').click();
  await expect(page.getByRole('combobox',{name:'小巴 Product Agent 模型档案'})).toHaveAttribute('aria-expanded','true');
  await page.getByRole('option').filter({hasText:name}).click();
  await expect(page.getByText('有一笔模型操作尚未确认',{exact:true})).toBeVisible();await page.reload();
  let received=page.waitForResponse(r=>r.url().includes('/models/commands/receipts?'));
  await page.getByRole('button',{name:'核对原模型操作',exact:true}).click();
  expect(await(await received).json()).toEqual({state:'confirmed',operation:'binding',resource_id:'byq-product',expected_version:bindingVersion-1,profile_id:profile.profile_id,committed_version:bindingVersion});
  await expect(page.getByText('有一笔模型操作尚未确认',{exact:true})).toHaveCount(0);
  await page.getByPlaceholder('筛选档案、厂商、模型或状态').fill(name);
  await page.route('**/api/product/settings/models/profiles/'+profile.profile_id+'/delete',async route=>{
    deleteWrites++;const r=await route.fetch();expect(r.status()).toBe(200);expect((await r.json()).profile.status).toBe('deleted');await route.abort('failed');
  });
  await page.getByRole('row').filter({hasText:name}).getByRole('button',{name:'删除',exact:true}).click();
  await page.locator('.el-message-box__btns button').last().click();
  await expect(page.getByText('有一笔模型操作尚未确认',{exact:true})).toBeVisible();await page.reload();
  received=page.waitForResponse(r=>r.url().includes('/models/commands/receipts?'));
  await page.getByRole('button',{name:'核对原模型操作',exact:true}).click();
  expect(await(await received).json()).toEqual({state:'confirmed',operation:'delete_profile',resource_id:profile.profile_id,expected_version:1,profile_id:profile.profile_id,committed_version:2});
  await expect(page.getByText('有一笔模型操作尚未确认',{exact:true})).toHaveCount(0);
  const settings=await page.evaluate(async()=>(await fetch('/api/product/settings/models',{credentials:'include'})).json());
  const binding=settings.bindings.find((v:any)=>v.agent_id==='byq-product');expect(binding.profile_id).toBeNull();expect(binding.version).toBe(bindingVersion+1);
  expect(bindingWrites).toBe(1);expect(deleteWrites).toBe(1);
});
