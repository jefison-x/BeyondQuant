import {test,expect} from '@playwright/test';
test.skip(process.env.BYQ_H5_EVIDENCE !== '1','isolated Product stack required');
test('account and order acknowledgements recover after refresh without a second write',async({page})=>{
  await page.goto('/login');await page.getByLabel('用户名').fill('h5-browser');await page.getByLabel('密码').fill('test-password-123');
  await page.getByRole('button',{name:'进入'}).click();await expect(page).toHaveURL(/\/agent$/);
  const suffix=Date.now().toString();
  await page.evaluate(async id=>{
    const response=await fetch('/api/product/paper/pools',{method:'POST',credentials:'include',headers:{'content-type':'application/json'},
      body:JSON.stringify({name:'Paper recovery pool '+id,symbols:['000001.SZ'],idempotency_key:'paper-recovery-pool-'+id})});
    if(!response.ok) throw Error('pool setup failed');
  },suffix);
  await page.goto('/paper-trading');await page.getByTestId('paper-account-name').fill('Paper recovery '+suffix);
  await page.getByTestId('paper-initial-cash').locator('input').fill('1500');
  let accountId='',orderId='',accountWrites=0,orderWrites=0;
  page.on('request',r=>{if(r.method()==='POST'){if(r.url().endsWith('/paper/accounts'))accountWrites++;if(r.url().endsWith('/paper/orders'))orderWrites++;}});
  await page.route('**/api/product/paper/accounts',async route=>{
    if(route.request().method()!=='POST') return route.continue();
    const response=await route.fetch();expect(response.status()).toBe(201);accountId=(await response.json()).account.account_id;await route.abort('failed');
  });
  await page.getByTestId('paper-create-account').click();
  await expect(page.getByText('有一笔模拟账户操作尚未确认',{exact:true})).toBeVisible();
  await page.reload();
  await page.getByRole('button',{name:'核对原模拟操作',exact:true}).click();
  await expect(page.getByText('有一笔模拟账户操作尚未确认',{exact:true})).toHaveCount(0);
  await page.getByTestId('paper-trade-pool').click();
  await page.getByRole('option').filter({hasText:'Paper recovery pool '+suffix}).click();
  await page.getByTestId('paper-symbol').fill('000001.SZ');
  await page.getByTestId('paper-quantity').locator('input').fill('100');await page.getByTestId('paper-price').locator('input').fill('10');
  await page.getByTestId('paper-trade-date').fill('20260105');
  await page.route('**/api/product/paper/orders',async route=>{
    const response=await route.fetch();expect(response.status()).toBe(201);const body=await response.json();
    expect(body.order.status).toBe('filled');orderId=body.order.order_id;await route.abort('failed');
  });
  await page.getByTestId('paper-submit-order').click();
  await expect(page.getByText('有一笔模拟账户操作尚未确认',{exact:true})).toBeVisible();await page.reload();
  const receipt=page.waitForResponse(r=>r.url().includes('/paper/receipts?'));
  await page.getByRole('button',{name:'核对原模拟操作',exact:true}).click();
  const body=await (await receipt).json();expect(body.order.order_id).toBe(orderId);expect(body.account_id).toBe(accountId);
  await expect(page.getByText('有一笔模拟账户操作尚未确认',{exact:true})).toHaveCount(0);
  const account=await page.evaluate(async id=>(await fetch('/api/product/paper/accounts/'+id,{credentials:'include'})).json(),accountId);
  expect(Number(account.account.cash)).toBe(495);expect(accountWrites).toBe(1);expect(orderWrites).toBe(1);
});

test('account import acknowledgement is recovered without importing twice',async({page})=>{
  await page.goto('/login');await page.getByLabel('用户名').fill('h5-browser');await page.getByLabel('密码').fill('test-password-123');
  await page.getByRole('button',{name:'进入'}).click();await expect(page).toHaveURL(/\/agent$/);
  const bundle = await page.evaluate(async()=>{
    const id = Date.now().toString();
    const create = await fetch('/api/product/paper/accounts',{method:'POST',credentials:'include',headers:{'content-type':'application/json'},
      body:JSON.stringify({name:'Import recovery '+id,cash:1500,idempotency_key:'import-source-'+id})});
    if(create.status!==201) throw Error('create fixture failed');
    const account = (await create.json()).account;
    const response=await fetch('/api/product/paper/accounts/'+account.account_id+'/export',{credentials:'include'});
    if(!response.ok) throw Error('export fixture failed');return (await response.json()).bundle;
  });
  await page.goto('/paper-trading');let importedId='',writes=0;
  page.on('request',r=>{if(r.method()==='POST' && r.url().endsWith('/paper/accounts/import'))writes++;});
  await page.route('**/api/product/paper/accounts/import',async route=>{
    const response=await route.fetch();expect(response.status()).toBe(201);importedId=(await response.json()).account.account_id;await route.abort('failed');
  });
  await page.locator('input[type=file]').setInputFiles({name:'account.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(bundle))});
  await expect(page.getByText('有一笔模拟账户操作尚未确认',{exact:true})).toBeVisible();await page.reload();
  const receipt=page.waitForResponse(r=>r.url().includes('/paper/receipts?'));
  await page.getByRole('button',{name:'核对原模拟操作',exact:true}).click();
  const body=await(await receipt).json();expect(body.account_id).toBe(importedId);expect(body.operation).toBe('import');
  await expect(page.getByText('有一笔模拟账户操作尚未确认',{exact:true})).toHaveCount(0);expect(writes).toBe(1);
});

test('a rejected retry cannot erase an earlier unknown committed account',async({page})=>{
  await page.goto('/login');await page.getByLabel('用户名').fill('h5-browser');await page.getByLabel('密码').fill('test-password-123');
  await page.getByRole('button',{name:'进入'}).click();await expect(page).toHaveURL(/\/agent$/);
  await page.goto('/paper-trading');await page.getByTestId('paper-account-name').fill('Retry auth '+Date.now());
  let committedId='',attempts=0;
  await page.route('**/api/product/paper/accounts',async route=>{
    if(route.request().method()!=='POST')return route.continue();
    attempts++;
    if(attempts>1)return route.fulfill({status:401,contentType:'application/json',body:JSON.stringify({error:{message:'synthetic expired session'}})});
    const response=await route.fetch();expect(response.status()).toBe(201);committedId=(await response.json()).account.account_id;await route.abort('failed');
  });
  await page.getByTestId('paper-create-account').click();await expect(page.getByText('有一笔模拟账户操作尚未确认',{exact:true})).toBeVisible();
  await page.reload();await page.getByRole('button',{name:'使用原模拟操作重试',exact:true}).click();
  await expect(page.getByText('synthetic expired session',{exact:true})).toBeVisible();
  await expect(page.getByText('有一笔模拟账户操作尚未确认',{exact:true})).toBeVisible();
  const recovered=page.waitForResponse(r=>r.url().includes('/paper/receipts?'));
  await page.getByRole('button',{name:'核对原模拟操作',exact:true}).click();
  expect((await(await recovered).json()).account_id).toBe(committedId);
  await expect(page.getByText('有一笔模拟账户操作尚未确认',{exact:true})).toHaveCount(0);expect(attempts).toBe(2);
});
