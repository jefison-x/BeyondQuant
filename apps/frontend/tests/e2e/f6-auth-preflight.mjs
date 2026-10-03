// Engineering-only CI preflight: no Agent, model, Job or business writes.
import {chromium} from '@playwright/test';
import {openSync,writeFileSync,closeSync} from 'node:fs';
const project=process.env.COMPOSE_PROJECT_NAME||'';
if(!/^byq-ci-stack-[A-Za-z0-9][A-Za-z0-9_-]{0,80}$/.test(project)||process.env.BYQ_F6_AUTH_CI_PROJECT!==project)throw new Error('dedicated CI project required');
const target=new URL(process.env.BYQ_REAL_BASE_URL||'');
if(target.protocol!=='http:'||target.hostname!=='127.0.0.1'||!target.port||target.username||target.password||target.pathname!=='/'||target.search||target.hash)throw new Error('loopback frontend origin required');
const origin=target.origin;
const out=process.env.BYQ_F6_AUTH_EVIDENCE_DIR;
if(!out||!process.env.BYQ_E2E_ADMIN_USERNAME||!process.env.BYQ_E2E_ADMIN_PASSWORD) throw new Error('missing private test launch inputs');
const evidence={schema:'f6-ci-browser-auth-preflight.v1',scope:'dedicated_CI_login_only_before_Agent_or_Job',status:'RUNNING',project,frontend_port:target.port,auth:[],unexpected_writes:0,foreign_requests:0,page_errors:0,login_posts:0,logout_posts:0,model_inputs:0,business_inputs:0,new_jobs:0,service_mutations:0};
const save=()=>{const fd=openSync(out+'/browser-result.json','wx',0o600);try{writeFileSync(fd,JSON.stringify(evidence,null,2)+'\n')}finally{closeSync(fd)}};
let browser,context,page;let authenticated=false;let browserClosing;
const closeBrowser=()=>{if(!browser)return Promise.resolve();browserClosing??=Promise.resolve().then(()=>browser.close());return browserClosing};
process.once('SIGTERM',()=>{evidence.abort_signal=true;void closeBrowser().catch(()=>{});});
try {
 browser=await chromium.launch({headless:true});if(evidence.abort_signal)throw new Error('aborted_before_context');context=await browser.newContext({viewport:{width:1440,height:1000}});page=await context.newPage();page.setDefaultTimeout(5000);
 await context.route('**/*',async route=>{const r=route.request(),u=new URL(r.url());
  if(['http:','https:'].includes(u.protocol)&&u.origin!==origin){evidence.foreign_requests++;await route.abort();return;}
  if(!['GET','HEAD','OPTIONS'].includes(r.method())){
   if(evidence.abort_signal){evidence.blocked_after_abort=(evidence.blocked_after_abort||0)+1;await route.abort();return;}
   if(r.method()==='POST'&&u.pathname==='/api/auth/login'&&evidence.login_posts===0)evidence.login_posts++;
   else if(r.method()==='POST'&&u.pathname==='/api/auth/logout'&&evidence.logout_posts===0)evidence.logout_posts++;
   else{evidence.unexpected_writes++;await route.abort();return;}
  }
  await route.continue();
 });
 page.on('response',r=>{const u=new URL(r.url());if(u.origin===origin&&['/api/auth/login','/api/auth/me','/api/auth/logout'].includes(u.pathname)&&evidence.auth.length<16)evidence.auth.push({path:u.pathname,method:r.request().method(),status:r.status()})});
 page.on('pageerror',()=>{evidence.page_errors=Math.min(evidence.page_errors+1,8)});
 await page.goto(origin+'/login?redirect=%2Fuser%2Fprofile');await page.getByLabel('用户名').fill(process.env.BYQ_E2E_ADMIN_USERNAME);await page.getByLabel('密码').fill(process.env.BYQ_E2E_ADMIN_PASSWORD);
 if(evidence.abort_signal)throw new Error('aborted_before_login');
 const [login]=await Promise.all([page.waitForResponse(r=>new URL(r.url()).origin===origin&&new URL(r.url()).pathname==='/api/auth/login'&&r.request().method()==='POST'),page.getByRole('button',{name:'进入',exact:true}).click()]);evidence.login_status=login.status();
 if(login.status()!==200)throw new Error('login_http_not_200');
 await page.waitForURL(origin+'/user/profile');
 const me=await page.evaluate(async()=>{const r=await fetch('/api/auth/me',{credentials:'include',signal:AbortSignal.timeout(5000)});if(!r.ok)return{status:r.status};const b=await r.json();return{status:r.status,subject:b.subject,workspace_present:typeof b.workspace?.workspace_id==='string'}});
 evidence.me_status=me.status;evidence.exact_user=me.subject===process.env.BYQ_E2E_ADMIN_USERNAME;evidence.workspace_present=me.workspace_present===true;authenticated=me.status===200&&evidence.exact_user;
 if(!authenticated||!evidence.workspace_present||evidence.unexpected_writes||evidence.foreign_requests||evidence.page_errors)throw new Error('identity_or_browser_scope_unconfirmed');
 evidence.status='PASS_SCOPED_CI_F6_LOGIN';
}catch(e){evidence.status='FAIL_SCOPED_LOGIN';evidence.error_type=e?.constructor?.name||'unknown';evidence.private_error_text='SUPPRESSED';}
finally{
 if(page){evidence.final_route=new URL(page.url()).pathname==='/user/profile'?'profile':new URL(page.url()).pathname==='/login'?'login':'other';
  // Query existing cookie once before the one exact logout; never retry login.
  try{const me=await page.evaluate(async()=>{const r=await fetch('/api/auth/me',{credentials:'include',signal:AbortSignal.timeout(5000)});if(!r.ok)return{status:r.status};const b=await r.json();return{status:r.status,subject:b.subject}});evidence.closeout_me_status=me.status;evidence.closeout_exact_user=me.subject===process.env.BYQ_E2E_ADMIN_USERNAME;if(me.status===200&&evidence.closeout_exact_user&&!evidence.abort_signal){const revoke=await page.evaluate(async()=>{const r=await fetch('/api/auth/logout',{method:'POST',credentials:'include',signal:AbortSignal.timeout(5000)});return{status:r.status,body:await r.json()}});evidence.logout_status=revoke.status;evidence.logout_receipt_confirmed=revoke.status===200&&revoke.body?.status==='ok'&&Object.keys(revoke.body).length===1;
   const after=await page.evaluate(async()=>{const r=await fetch('/api/auth/me',{credentials:'include',signal:AbortSignal.timeout(5000)});return r.status});evidence.logout_readback=after;if(!evidence.logout_receipt_confirmed||after!==401)evidence.status='FAIL_LOGOUT_UNCONFIRMED_NO_REPLAY';}
  }catch{evidence.cleanup_auth='UNKNOWN_NO_REPLAY';evidence.status='FAIL_AUTH_CLOSEOUT_UNKNOWN';}
 }
 try{if(context)await context.close();}catch{evidence.context_close_error=true;evidence.status='FAIL_BROWSER_CLOSEOUT';}
 try{await closeBrowser();evidence.browser_closed=true;}catch{evidence.browser_closed=false;evidence.status='FAIL_BROWSER_CLOSEOUT';}
 if(evidence.abort_signal)evidence.status='ABORTED_NO_REPLAY';
 // Authorize the next CI stage only from the complete final closed outcome.
 // An earlier healthy identity never substitutes for verified auth closeout.
 if(evidence.status==='PASS_SCOPED_CI_F6_LOGIN'&&!(
   evidence.login_posts===1&&evidence.logout_posts===1
   &&evidence.me_status===200&&evidence.exact_user===true&&evidence.workspace_present===true
   &&evidence.final_route==='profile'
   &&evidence.closeout_me_status===200&&evidence.closeout_exact_user===true
   &&evidence.logout_status===200&&evidence.logout_receipt_confirmed===true
   &&evidence.logout_readback===401&&evidence.browser_closed===true
   &&!evidence.context_close_error&&!evidence.abort_signal
   &&evidence.unexpected_writes===0&&evidence.foreign_requests===0&&evidence.page_errors===0
 ))evidence.status='FAIL_AUTH_OR_BROWSER_CLOSEOUT_UNCONFIRMED_NO_REPLAY';
 // Preserve the result even when connection cleanup rejects; no automatic retry.
 save();
}
// The CI artifact contains redacted console output: keep every closed auth fact.
console.log(JSON.stringify(evidence));
process.exitCode=evidence.status==='PASS_SCOPED_CI_F6_LOGIN'?0:1;
