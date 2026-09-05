const SECURITY_HEADERS = {
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
  "referrer-policy": "no-referrer",
  "x-frame-options": "DENY",
  "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
  "cross-origin-resource-policy": "same-origin"
};

export const ADMIN_CONSOLE_HTML = `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>BeyondQuant 中央反馈审核</title>
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%232563eb'/%3E%3Cpath d='M17 17h18c9 0 14 4 14 11 0 4-2 7-6 9 5 2 7 5 7 10 0 8-6 12-16 12H17V17zm11 9v8h7c3 0 5-1 5-4s-2-4-5-4h-7zm0 16v8h8c4 0 5-1 5-4s-2-4-5-4h-8z' fill='white'/%3E%3C/svg%3E">
  <link rel="stylesheet" href="/admin/assets/app.css">
  <script type="module" src="/admin/assets/app.js"></script>
</head>
<body>
  <a class="skip-link" href="#main">跳到主要内容</a>
  <main id="main">
    <section id="login-view" class="login-shell" hidden>
      <form id="login-form" class="login-card">
        <p class="eyebrow">BEYONDQUANT OPERATOR</p>
        <h1>中央反馈审核</h1>
        <p class="muted">请输入管理员密码。验证后密码不会写入 Cookie 或应用浏览器存储。</p>
        <label for="admin-password">管理员密码</label>
        <input id="admin-password" name="password" type="password" required minlength="16" maxlength="256"
          autocomplete="current-password" autocapitalize="off" spellcheck="false">
        <button id="login-button" class="primary" type="submit">进入审核台</button>
        <p id="login-error" class="message error" role="alert" hidden></p>
      </form>
    </section>

    <section id="console-view" class="console" hidden>
      <header class="topbar">
        <div>
          <p class="eyebrow">BEYONDQUANT OPERATOR</p>
          <h1>中央反馈审核</h1>
          <p class="muted">审核匿名公开候选内容，采纳后才会进入 GitHub Issue 发布队列。</p>
        </div>
        <div class="top-actions">
          <button id="refresh-button" class="secondary" type="button">刷新</button>
          <button id="logout-button" class="ghost" type="button">退出</button>
        </div>
      </header>

      <section class="toolbar" aria-label="反馈筛选">
        <label for="status-filter">状态</label>
        <select id="status-filter">
          <option value="received">待分诊</option>
          <option value="triaged">待决策</option>
          <option value="accepted">已采纳</option>
          <option value="publishing">发布中</option>
          <option value="published">已发布</option>
          <option value="rejected">未采纳</option>
          <option value="duplicate">重复</option>
          <option value="all">全部</option>
        </select>
        <span id="result-summary" class="muted" aria-live="polite"></span>
      </section>

      <p id="console-message" class="message" role="status" hidden></p>
      <div class="workspace">
        <section class="catalogue" aria-label="反馈列表">
          <div id="loading-state" class="state">正在加载反馈…</div>
          <div id="empty-state" class="state" hidden>当前筛选下没有反馈。</div>
          <div id="feedback-list" class="feedback-list" aria-live="polite"></div>
          <nav class="pagination" aria-label="反馈分页">
            <button id="previous-page" class="secondary" type="button">上一页</button>
            <span id="page-summary" class="muted"></span>
            <button id="next-page" class="secondary" type="button">下一页</button>
          </nav>
        </section>

        <section id="detail-panel" class="detail" aria-label="反馈详情" tabindex="-1">
          <div id="detail-empty" class="state">选择一条反馈查看详情。</div>
          <article id="detail-content" hidden>
            <div class="detail-heading">
              <div>
                <span id="detail-status" class="status-pill"></span>
                <h2 id="detail-title"></h2>
                <p id="detail-meta" class="muted"></p>
              </div>
            </div>
            <dl id="detail-fields" class="detail-fields"></dl>
            <section id="moderation-actions" class="moderation-actions" aria-label="审核操作"></section>
          </article>
        </section>
      </div>
    </section>
  </main>

  <dialog id="moderation-dialog">
    <form id="moderation-form" method="dialog">
      <p class="eyebrow">CENTRAL MODERATION</p>
      <h2 id="moderation-title">确认审核操作</h2>
      <p id="moderation-warning" class="warning"></p>
      <label for="moderation-rationale">审核理由</label>
      <textarea id="moderation-rationale" required minlength="3" maxlength="1000" rows="4"></textarea>
      <div id="duplicate-field" hidden>
        <label for="duplicate-receipt">重复反馈 Receipt</label>
        <input id="duplicate-receipt" pattern="central_feedback_[0-9a-f]{32}" maxlength="49"
          autocomplete="off" autocapitalize="off" spellcheck="false">
      </div>
      <p id="moderation-error" class="message error" role="alert" hidden></p>
      <div class="dialog-actions">
        <button id="cancel-moderation" class="secondary" type="button">取消</button>
        <button id="confirm-moderation" class="primary" type="submit">确认</button>
      </div>
    </form>
  </dialog>
</body>
</html>`;

export const ADMIN_CONSOLE_CSS = `
:root{font-family:Inter,"PingFang SC","Microsoft YaHei",system-ui,sans-serif;color:#172033;background:#f3f6fa;color-scheme:light;--brand:#2563eb;--brand-dark:#1d4ed8;--surface:#fff;--surface-soft:#f8fafc;--border:#dce3ed;--muted:#64748b;--danger:#b42318;--warning:#9a6700;--shadow:0 20px 60px rgba(30,41,59,.12)}
*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;min-width:320px;background:radial-gradient(circle at top left,#e8f0ff 0,transparent 34rem),#f3f6fa;color:#172033}button,input,select,textarea{font:inherit}button{cursor:pointer}button:disabled{cursor:not-allowed;opacity:.5}.skip-link{position:fixed;left:12px;top:-80px;z-index:20;background:#111827;color:#fff;padding:10px 14px;border-radius:8px}.skip-link:focus{top:12px}.login-shell{min-height:100vh;display:grid;place-items:center;padding:24px}.login-card{width:min(440px,100%);display:grid;gap:14px;padding:32px;background:var(--surface);border:1px solid var(--border);border-radius:18px;box-shadow:var(--shadow)}h1,h2,p{margin-top:0}.login-card h1,.topbar h1{margin-bottom:8px}.eyebrow{margin-bottom:6px;color:var(--brand);font-size:12px;font-weight:800;letter-spacing:.12em}.muted{color:var(--muted)}label{font-size:13px;font-weight:750}input,select,textarea{width:100%;border:1px solid #c8d2df;border-radius:9px;background:var(--surface);color:inherit;padding:10px 12px}textarea{resize:vertical}input:focus,select:focus,textarea:focus,button:focus-visible{outline:3px solid rgba(37,99,235,.25);outline-offset:2px;border-color:var(--brand)}button{border:1px solid transparent;border-radius:9px;padding:9px 14px;font-weight:750}.primary{background:var(--brand);color:#fff}.primary:hover{background:var(--brand-dark)}.secondary{background:var(--surface);border-color:var(--border);color:#263449}.ghost{background:transparent;border-color:transparent;color:var(--muted)}.message{margin:0;padding:10px 12px;border-radius:9px;background:#eef6ff;color:#1e4d8f}.message.error{background:#fff0ef;color:var(--danger)}.console{width:min(1500px,100%);margin:0 auto;padding:24px}.topbar{display:flex;align-items:flex-start;justify-content:space-between;gap:24px;margin-bottom:20px}.top-actions{display:flex;gap:8px}.toolbar{display:grid;grid-template-columns:auto minmax(160px,240px) 1fr;align-items:center;gap:10px;margin-bottom:12px;padding:12px 14px;background:rgba(255,255,255,.82);border:1px solid var(--border);border-radius:12px}.toolbar #result-summary{text-align:right}.workspace{display:grid;grid-template-columns:minmax(330px,38%) minmax(0,1fr);min-height:680px;background:var(--surface);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow);overflow:hidden}.catalogue{display:flex;flex-direction:column;min-height:0;border-right:1px solid var(--border);background:var(--surface-soft)}.feedback-list{display:grid;align-content:start;gap:8px;flex:1;overflow-y:auto;padding:12px}.feedback-card{display:grid;gap:6px;width:100%;padding:13px;text-align:left;background:var(--surface);border:1px solid var(--border);border-radius:11px;color:inherit}.feedback-card:hover,.feedback-card[aria-current="true"]{border-color:#93b4ef;box-shadow:0 5px 18px rgba(37,99,235,.09)}.feedback-card[aria-current="true"]{background:#eff6ff}.feedback-card strong{line-height:1.4}.card-meta{display:flex;justify-content:space-between;gap:8px;color:var(--muted);font-size:12px}.state{padding:36px 18px;text-align:center;color:var(--muted)}.pagination{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:8px;padding:12px;border-top:1px solid var(--border)}.pagination button:last-child{justify-self:end}.detail{min-width:0;overflow-y:auto;padding:24px}.detail-heading{display:flex;justify-content:space-between;gap:16px;border-bottom:1px solid var(--border);padding-bottom:16px}.detail-heading h2{margin:10px 0 7px;font-size:23px;line-height:1.35}.status-pill{display:inline-flex;border-radius:999px;background:#e7eefb;color:#294a80;padding:5px 9px;font-size:12px;font-weight:800}.detail-fields{display:grid;grid-template-columns:minmax(110px,150px) minmax(0,1fr);gap:12px 18px;margin:22px 0}.detail-fields dt{font-size:12px;font-weight:800;color:var(--muted)}.detail-fields dd{margin:0;line-height:1.65;white-space:pre-wrap;overflow-wrap:anywhere}.detail-fields ol{margin:0;padding-left:20px}.issue-link{color:var(--brand);font-weight:750}.moderation-actions{display:flex;flex-wrap:wrap;gap:10px;border-top:1px solid var(--border);padding-top:18px}.danger{background:#fff1f0;border-color:#ffccc7;color:var(--danger)}dialog{width:min(560px,calc(100% - 32px));border:1px solid var(--border);border-radius:16px;padding:0;color:inherit;background:var(--surface);box-shadow:var(--shadow)}dialog::backdrop{background:rgba(15,23,42,.55)}dialog form{display:grid;gap:13px;padding:24px}.warning{color:var(--warning);background:#fff8db;border:1px solid #f2d67c;border-radius:9px;padding:11px;line-height:1.5}.dialog-actions{display:flex;justify-content:flex-end;gap:9px;margin-top:5px}
@media(max-width:820px){.console{padding:14px}.topbar{align-items:stretch;flex-direction:column}.top-actions button{flex:1}.toolbar{grid-template-columns:auto 1fr}.toolbar #result-summary{grid-column:1/-1;text-align:left}.workspace{display:block;min-height:0}.catalogue{height:44vh;border-right:0;border-bottom:1px solid var(--border)}.detail{min-height:48vh;padding:18px}.detail-fields{grid-template-columns:1fr;gap:5px}.detail-fields dd{margin-bottom:10px}}
@media(prefers-color-scheme:dark){:root{color:#e5edf8;background:#0f172a;--surface:#151f31;--surface-soft:#111a29;--border:#334155;--muted:#9caec4;--shadow:0 20px 60px rgba(0,0,0,.35)}body{background:radial-gradient(circle at top left,#172b53 0,transparent 34rem),#0f172a}.toolbar{background:rgba(21,31,49,.88)}input,select,textarea{border-color:#475569}.secondary{color:#dce7f6}.feedback-card[aria-current="true"]{background:#172d50}.message{background:#172d50;color:#b9d4ff}.message.error{background:#3a1d24;color:#ffb4ae}.warning{background:#382f16;border-color:#6c5719;color:#f2d67c}.danger{background:#3a1d24;border-color:#6b3035;color:#ffb4ae}}
`;

export const ADMIN_CONSOLE_JS = `
const labels={status:{received:'待分诊',triaged:'待决策',accepted:'已采纳',publishing:'发布中',published:'已发布',rejected:'未采纳',duplicate:'重复'},category:{bug:'缺陷',feature:'功能建议',performance:'性能',usability:'易用性',other:'其他'},severity:{low:'低',normal:'一般',high:'高'},component:{xiaoba:'小巴',stock_pool:'股票池',strategy:'策略',model_research:'模型研究',backtest:'回测',data_center:'数据中心',system_settings:'系统设置',auth:'登录与权限',runtime:'运行时',other:'其他'},environment:{product_version:'产品版本',deployment_kind:'部署类型',browser_family:'浏览器',os_family:'操作系统',performance_summary:'性能摘要'}};
const state={items:[],total:0,limit:20,offset:0,selected:null,action:null};
const byId=(id)=>document.getElementById(id);
const loginView=byId('login-view');
const consoleView=byId('console-view');
const loginForm=byId('login-form');
const passwordInput=byId('admin-password');
const loginButton=byId('login-button');
const loginError=byId('login-error');
const consoleMessage=byId('console-message');
const statusFilter=byId('status-filter');
const list=byId('feedback-list');
const loadingState=byId('loading-state');
const emptyState=byId('empty-state');
const detailPanel=byId('detail-panel');
const detailEmpty=byId('detail-empty');
const detailContent=byId('detail-content');
const detailFields=byId('detail-fields');
const actions=byId('moderation-actions');
const dialog=byId('moderation-dialog');
const moderationForm=byId('moderation-form');
const moderationRationale=byId('moderation-rationale');
const duplicateField=byId('duplicate-field');
const duplicateReceipt=byId('duplicate-receipt');
const moderationError=byId('moderation-error');

function show(element,visible){element.hidden=!visible}
function text(element,value){element.textContent=value==null?'':String(value)}
function element(tag,className,value){const node=document.createElement(tag);if(className)node.className=className;if(value!=null)text(node,value);return node}
function setMessage(value,type){text(consoleMessage,value);consoleMessage.className='message'+(type==='error'?' error':'');show(consoleMessage,Boolean(value))}
function setLoginError(value){text(loginError,value);show(loginError,Boolean(value))}
function formatTime(value){if(!value)return '—';const date=new Date(value);return Number.isNaN(date.getTime())?String(value):date.toLocaleString('zh-CN',{hour12:false})}
function errorText(payload,status){if(payload&&typeof payload.detail==='string')return payload.detail;if(status===401)return '管理员会话已失效，请重新登录。';if(status===403)return '请求来源验证失败，请刷新页面重试。';if(status===409)return '反馈状态已经变化，请刷新后重试。';return '请求失败，请稍后重试。'}

async function request(path,options){
  const init=options||{};const headers=new Headers(init.headers||{});const method=String(init.method||'GET').toUpperCase();
  if(init.body)headers.set('content-type','application/json');
  if(method!=='GET'&&method!=='HEAD')headers.set('x-byq-feedback-admin-request','ui-v1');
  const response=await fetch(path,{...init,method,headers,credentials:'same-origin'});
  const contentType=response.headers.get('content-type')||'';
  const payload=contentType.includes('application/json')?await response.json():null;
  if(!response.ok){const failure=new Error(errorText(payload,response.status));failure.status=response.status;throw failure}
  return payload;
}

function enterLogin(message){
  show(consoleView,false);show(loginView,true);state.items=[];state.selected=null;passwordInput.value='';setLoginError(message||'');queueMicrotask(()=>passwordInput.focus());
}
function enterConsole(){show(loginView,false);show(consoleView,true);setLoginError('')}

async function checkSession(){
  try{const result=await request('/v1/admin/session');if(result&&result.authenticated){enterConsole();await loadFeedback()}else enterLogin('')}
  catch(error){enterLogin(error.message)}
}

loginForm.addEventListener('submit',async(event)=>{
  event.preventDefault();setLoginError('');loginButton.disabled=true;let supplied=passwordInput.value;
  try{await request('/v1/admin/session',{method:'POST',body:JSON.stringify({password:supplied})});passwordInput.value='';supplied='';enterConsole();await loadFeedback()}
  catch(error){passwordInput.value='';supplied='';setLoginError(error.message);passwordInput.focus()}
  finally{loginButton.disabled=false}
});

byId('logout-button').addEventListener('click',async()=>{
  try{await request('/v1/admin/session',{method:'DELETE'})}catch(_error){}finally{enterLogin('已安全退出。')}
});
byId('refresh-button').addEventListener('click',()=>loadFeedback());
statusFilter.addEventListener('change',()=>{state.offset=0;state.selected=null;loadFeedback()});
byId('previous-page').addEventListener('click',()=>{if(state.offset>0){state.offset=Math.max(0,state.offset-state.limit);state.selected=null;loadFeedback()}});
byId('next-page').addEventListener('click',()=>{if(state.offset+state.limit<state.total){state.offset+=state.limit;state.selected=null;loadFeedback()}});

async function loadFeedback(){
  show(loadingState,true);show(emptyState,false);list.replaceChildren();setMessage('');
  try{
    const query=new URLSearchParams({status:statusFilter.value,limit:String(state.limit),offset:String(state.offset)});
    const result=await request('/v1/admin/feedback?'+query.toString());
    state.items=Array.isArray(result.items)?result.items:[];state.total=Number(result.total||0);
    if(state.offset>=state.total&&state.offset>0){state.offset=Math.max(0,state.offset-state.limit);return loadFeedback()}
    renderList();renderPagination();
    if(state.selected){const current=state.items.find((item)=>item.receipt_id===state.selected.receipt_id);state.selected=current||null}
    if(!state.selected&&state.items.length)state.selected=state.items[0];renderDetail();
  }catch(error){if(error.status===401){enterLogin(error.message);return}setMessage(error.message,'error');state.items=[];state.total=0;renderList();renderPagination();renderDetail()}
  finally{show(loadingState,false)}
}

function renderList(){
  list.replaceChildren();show(emptyState,state.items.length===0);show(list,state.items.length>0);
  for(const item of state.items){
    const content=item.snapshot_json&&item.snapshot_json.public_content?item.snapshot_json.public_content:{};
    const button=element('button','feedback-card');button.type='button';button.dataset.receipt=item.receipt_id;
    button.setAttribute('aria-current',state.selected&&state.selected.receipt_id===item.receipt_id?'true':'false');
    button.append(element('strong','',content.title||'未命名反馈'));
    const meta=element('span','card-meta');meta.append(element('span','',labels.status[item.status]||item.status));meta.append(element('time','',formatTime(item.created_at)));button.append(meta);
    button.addEventListener('click',()=>{state.selected=item;renderList();renderDetail();detailPanel.focus({preventScroll:true})});list.append(button);
  }
}

function renderPagination(){
  const page=Math.floor(state.offset/state.limit)+1;const pages=Math.max(1,Math.ceil(state.total/state.limit));
  text(byId('result-summary'),'共 '+state.total+' 条');text(byId('page-summary'),'第 '+page+' / '+pages+' 页');
  byId('previous-page').disabled=state.offset===0;byId('next-page').disabled=state.offset+state.limit>=state.total;
}

function addField(label,value){
  detailFields.append(element('dt','',label));const description=element('dd');
  if(value instanceof Node)description.append(value);else text(description,value===''?'未填写':value==null?'—':value);detailFields.append(description);
}
function safeIssueLink(item){
  if(!item.github_html_url)return null;
  try{const url=new URL(item.github_html_url);if(url.protocol!=='https:'||url.hostname!=='github.com'||!url.pathname.startsWith('/jefison-x/BeyondQuant/issues/'))return null;
    const link=element('a','issue-link','打开 GitHub Issue #'+item.github_issue_number);link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';return link
  }catch(_error){return null}
}
function renderDetail(){
  const item=state.selected;show(detailEmpty,!item);show(detailContent,Boolean(item));detailFields.replaceChildren();actions.replaceChildren();if(!item)return;
  const snapshot=item.snapshot_json||{};const content=snapshot.public_content||{};
  text(byId('detail-status'),labels.status[item.status]||item.status);text(byId('detail-title'),content.title||'未命名反馈');
  text(byId('detail-meta'),(labels.category[content.category]||content.category||'其他')+' · '+(labels.component[content.component]||content.component||'其他')+' · '+(labels.severity[content.severity]||content.severity||'一般'));
  addField('问题描述',content.description||'');
  const steps=element('ol');for(const step of Array.isArray(content.reproduction_steps)?content.reproduction_steps:[])steps.append(element('li','',step));addField('复现步骤',steps.childNodes.length?steps:'未填写');
  addField('期望行为',content.expected_behavior||'');addField('实际行为',content.actual_behavior||'');
  const environment=element('dl','environment-list');for(const [key,value] of Object.entries(content.environment||{})){environment.append(element('dt','',labels.environment[key]||key));environment.append(element('dd','',value))}addField('环境信息',environment.childNodes.length?environment:'未提供');
  addField('Receipt',item.receipt_id);addField('内容指纹',item.fingerprint);addField('创建时间',formatTime(item.created_at));addField('更新时间',formatTime(item.updated_at));
  if(item.duplicate_of)addField('重复于',item.duplicate_of);const issue=safeIssueLink(item);if(issue)addField('公开 Issue',issue);
  if(item.status==='received')actions.append(actionButton('triage','完成分诊','primary'));
  if(item.status==='triaged'){actions.append(actionButton('accept','采纳并进入发布队列','primary'));actions.append(actionButton('duplicate','标记重复','secondary'));actions.append(actionButton('reject','不采纳','danger'))}
  if(!actions.childNodes.length)actions.append(element('span','muted','当前状态没有可执行的人工审核操作。'));
}

function actionButton(action,label,className){const button=element('button',className,label);button.type='button';button.addEventListener('click',()=>openModeration(action));return button}
function openModeration(action){
  state.action=action;moderationForm.reset();setModerationError('');const names={triage:'完成分诊',accept:'采纳反馈',reject:'不采纳',duplicate:'标记重复'};
  const warnings={triage:'确认内容完整、可复现且不包含敏感信息。',accept:'采纳后将进入固定官方仓库的 GitHub Issue 发布队列。',reject:'不采纳会终止这条反馈的公开发布流程。',duplicate:'请填写已存在的中央反馈 Receipt。'};
  text(byId('moderation-title'),names[action]||'确认审核操作');text(byId('moderation-warning'),warnings[action]||'');show(duplicateField,action==='duplicate');duplicateReceipt.required=action==='duplicate';
  text(byId('confirm-moderation'),action==='accept'?'确认采纳并发布':'确认');dialog.showModal();moderationRationale.focus();
}
function setModerationError(value){text(moderationError,value);show(moderationError,Boolean(value))}
byId('cancel-moderation').addEventListener('click',()=>dialog.close());
moderationForm.addEventListener('submit',async(event)=>{
  event.preventDefault();if(!state.selected||!state.action)return;setModerationError('');const confirmButton=byId('confirm-moderation');confirmButton.disabled=true;
  try{
    const body={rationale:moderationRationale.value.trim()};if(state.action==='duplicate')body.duplicate_of=duplicateReceipt.value.trim();
    await request('/v1/admin/feedback/'+encodeURIComponent(state.selected.receipt_id)+'/'+state.action,{method:'POST',body:JSON.stringify(body)});
    const completed=state.action;dialog.close();state.selected=null;setMessage(completed==='accept'?'已采纳，正在等待 GitHub Issue 发布。':'审核操作已完成。');await loadFeedback();
  }catch(error){if(error.status===401){dialog.close();enterLogin(error.message);return}setModerationError(error.message)}finally{confirmButton.disabled=false}
});

checkSession();
`;

function assetResponse(body: string, contentType: string, extra: Record<string, string> = {}): Response {
  return new Response(body, { headers: { ...SECURITY_HEADERS, "content-type": contentType, ...extra } });
}

export function adminConsoleAsset(pathname: string): Response | null {
  if (pathname === "/admin" || pathname === "/admin/") {
    return assetResponse(ADMIN_CONSOLE_HTML, "text/html; charset=utf-8", {
      "content-security-policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'"
    });
  }
  if (pathname === "/admin/assets/app.css") return assetResponse(ADMIN_CONSOLE_CSS, "text/css; charset=utf-8");
  if (pathname === "/admin/assets/app.js") return assetResponse(ADMIN_CONSOLE_JS, "text/javascript; charset=utf-8");
  return null;
}
