import {test,expect} from '@playwright/test';
test.skip(process.env.BYQ_H5_EVIDENCE !== '1','isolated Product stack required');
test('private feedback draft recovers its original commit after refresh',async({page})=>{
  await page.goto('/login');
  await page.getByLabel('用户名').fill(process.env.BYQ_H93_USERNAME ?? 'h5-browser');
  await page.getByLabel('密码').fill('test-password-123');
  await page.getByRole('button',{name:'进入'}).click();
  await expect(page).toHaveURL(/\/agent$/);
  await page.goto('/feedback');
  await page.getByRole('button',{name:'新建',exact:true}).click();
  const title = '隔离恢复测试 '+Date.now();
  await page.getByLabel('标题',{exact:true}).fill(title);
  await page.getByLabel('问题或建议描述').fill('验证保存成功但浏览器未收到回执时可以恢复原草稿。');
  let id = '', writes = 0;
  page.on('request',r=>{if(r.url().endsWith('/feedback/items') && r.method()==='POST') writes++;});
  await page.route('**/api/product/feedback/items',async route=>{
    if(route.request().method() !== 'POST') return route.continue();
    const response = await route.fetch(); expect(response.ok()).toBeTruthy();
    id = (await response.json()).feedback.feedback_id;
    await route.abort('failed');
  });
  await page.getByRole('button',{name:'保存草稿',exact:true}).click();
  await expect(page.getByText('有一笔反馈操作尚未确认',{exact:true})).toBeVisible();
  expect(id).toMatch(/^feedback_[0-9a-f]{32}$/);
  await page.reload();
  await expect(page.getByText('有一笔反馈操作尚未确认',{exact:true})).toBeVisible();
  const receipt = page.waitForResponse(r=>r.url().includes('/feedback/receipts?'));
  await page.getByRole('button',{name:'核对原反馈请求',exact:true}).click();
  const body = await (await receipt).json();
  expect(body.state).toBe('confirmed');expect(body.feedback.feedback_id).toBe(id);
  expect(body.feedback.status).toBe('draft');
  await expect(page.getByText('有一笔反馈操作尚未确认',{exact:true})).toHaveCount(0);
  await expect(page.getByRole('heading',{name:title,exact:true})).toBeVisible();
  expect(writes).toBe(1);
});

test('administrator recovers original moderation after lost replies and refresh',async({page})=>{
  test.setTimeout(90000);
  await page.goto('/login');
  await page.getByLabel('用户名').fill(process.env.BYQ_H93_USERNAME ?? 'h5-browser');
  await page.getByLabel('密码').fill('test-password-123');
  await page.getByRole('button',{name:'进入'}).click();
  await expect(page).toHaveURL(/\/agent$/);
  const ids=await page.evaluate(async()=>{
    const request=async(path:string,body:unknown)=>{
      const r=await fetch('/api/product/feedback'+path,{method:'POST',credentials:'include',headers:{'content-type':'application/json'},body:JSON.stringify(body)});
      if(!r.ok) throw Error('fixture '+r.status+' '+await r.text());return r.json();
    };
    const existing=await fetch('/api/product/feedback/items?status=submitted&query='+encodeURIComponent('审核恢复验证 h93-')+'&limit=100',{credentials:'include'});
    if(!existing.ok) throw Error('fixture list '+existing.status);
    const candidates=(await existing.json()).items;
    if(candidates.length>=3) return candidates.slice(0,3).map((item:{feedback_id:string})=>item.feedback_id);
    const ids:string[]=[];
    for(let i=0;i<3;i++) {
      const key='h93-'+Date.now()+'-'+i;
      const {feedback}=await request('/items',{schema_version:'product-feedback.v1',category:'bug',component:'other',severity:'normal',
        title:'审核恢复验证 '+key,description:'隔离验证审核提交回执丢失后的原操作恢复。',reproduction_steps:[],expected_behavior:'原审核仅执行一次',actual_behavior:'测试主动丢弃响应',diagnostics:{},idempotency_key:key});
      const preview=await request('/items/'+feedback.feedback_id+'/preview',{expected_version:feedback.version});
      await request('/items/'+feedback.feedback_id+'/submit',{expected_version:feedback.version,preview_hash:preview.preview_hash,disclosure_confirmed:true,idempotency_key:key+'-submit'});
      ids.push(feedback.feedback_id);
    }
    return ids;
  });
  let writes=0;
  await page.route('**/api/product/feedback/moderation/items/*/*',async route=>{
    if(route.request().method()!=='POST') return route.continue();
    writes++;
    const r=await route.fetch();expect(r.ok()).toBeTruthy();await route.abort('failed');
  });
  async function action(id:string,label:string,status:string,canonical?:string) {
    await page.goto('/settings/system/feedback');
    await page.locator('.el-select').filter({has:page.getByRole('combobox',{name:'审核状态'})}).click();
    await page.getByRole('option',{name:'全部状态',exact:true}).click();
    await page.getByRole('button').filter({hasText:id}).click();
    await page.getByRole('button',{name:label,exact:true}).click();
    let dialog=page.locator('.el-message-box');
    await dialog.locator('input').fill('验证原审核回执恢复');
    await dialog.getByRole('button',{name:'确定',exact:true}).click();
    if(canonical) {
      dialog=page.locator('.el-message-box').filter({has:page.getByRole('textbox',{name:'填写已分诊或已采纳反馈的反馈编号',exact:true})});
      await page.getByRole('textbox',{name:'填写已分诊或已采纳反馈的反馈编号',exact:true}).fill(canonical);
      await dialog.getByRole('button',{name:'确定',exact:true}).click();
    }
    await expect(page.getByText('上一笔审核结果待确认',{exact:true})).toBeVisible();
    await page.reload();
    await expect(page.getByText('上一笔审核结果待确认',{exact:true})).toBeVisible();
    const response=page.waitForResponse(r=>r.url().includes('/moderation/receipts?'));
    await page.getByRole('button',{name:'核对原审核请求',exact:true}).click();
    const body=await(await response).json();
    expect(body.state).toBe('confirmed');expect(body.feedback.feedback_id).toBe(id);expect(body.feedback.status).toBe(status);
    await expect(page.getByText('上一笔审核结果待确认',{exact:true})).toHaveCount(0);
  }
  await action(ids[0]!,'完成分诊','triaged');await action(ids[0]!,'采纳','accepted');
  await action(ids[1]!,'完成分诊','triaged');await action(ids[1]!,'不采纳','rejected');
  await action(ids[2]!,'完成分诊','triaged');await action(ids[2]!,'标记重复','duplicate',ids[0]);
  expect(writes).toBe(6);
});
