import {createRequestId} from '@/utils/requestId';
export type PolicyOperation='settings'|'rule_create'|'rule_update'|'rule_delete'|'preset';
export type PolicySubmission={key:string;operation:PolicyOperation;resource_id?:string;payload:Record<string,string|number|boolean>};
const fields={settings:['automation_enabled','paused','default_decision_mode','max_auto_executions_per_hour','max_auto_failures_per_hour'],rule_create:['name','description','action','agent_id','decision_mode','risk_level','priority','enabled'],rule_update:['name','description','action','agent_id','decision_mode','risk_level','priority','enabled','expected_version'],rule_delete:['expected_version'],preset:[]} as const;
const storageKey=(scope:string)=>'byq.policy-command.v1:'+scope;
function normalize(operation:PolicyOperation,payload:Record<string,unknown>,resource_id?:string){
  if(!Object.hasOwn(fields,operation) || !payload || typeof payload!=='object' || Array.isArray(payload))throw Error('原审批策略操作无效');
  const allowed:readonly string[]=fields[operation];
  if(Object.keys(payload).some(k=>!allowed.includes(k) || !['string','number','boolean'].includes(typeof payload[k]) || (typeof payload[k]==='number' && !Number.isFinite(payload[k]))))throw Error('审批策略参数无效');
  if(operation==='rule_update'||operation==='rule_delete'){
    if(!/^policy_rule_[0-9a-f]{32}$/.test(resource_id ?? '') || !Number.isSafeInteger(payload.expected_version) || Number(payload.expected_version)<1)throw Error('原规则标识或版本无效');
  }else if(operation==='preset'){
    if(!['manual_safe','deny_backtests'].includes(resource_id ?? ''))throw Error('策略预设无效');
  }else if(resource_id!==undefined)throw Error('审批策略目标无效');
  return {operation,...(resource_id===undefined?{}:{resource_id}),payload:Object.fromEntries(Object.keys(payload).sort().map(k=>[k,payload[k]])) as PolicySubmission['payload']};
}
export function readPolicySubmission(scope:string):PolicySubmission|null{
  const raw=localStorage.getItem(storageKey(scope));if(raw===null)return null;
  if(raw.length>8192)throw Error('原审批策略记录超出范围');const v=JSON.parse(raw);
  if(!v || Object.keys(v).some(k=>!['key','operation','resource_id','payload'].includes(k)) || !/^[A-Za-z0-9_-]{8,96}$/.test(v.key ?? ''))throw Error('原审批策略记录无效');
  return {key:v.key,...normalize(v.operation,v.payload,v.resource_id)};
}
export function beginPolicySubmission(scope:string,operation:PolicyOperation,payload:Record<string,unknown>,resource_id?:string):PolicySubmission{
  const value=normalize(operation,payload,resource_id),prior=readPolicySubmission(scope);
  if(prior){const {key,...original}=prior;if(JSON.stringify(original)!==JSON.stringify(value))throw Error('上一笔审批策略操作尚未确认，请先核对');return prior;}
  const command={key:createRequestId(),...value},raw=JSON.stringify(command);
  if(raw.length>8192)throw Error('审批策略操作超出范围');localStorage.setItem(storageKey(scope),raw);return command;
}
export function finishPolicySubmission(scope:string,key:string){if(readPolicySubmission(scope)?.key===key)localStorage.removeItem(storageKey(scope));}
export function validatePolicyResult(result:any,command:PolicySubmission){
  if(!result || typeof result!=='object')throw Error('审批策略回执不完整');
  if(command.operation==='rule_create'||command.operation==='rule_update'){
    if(!/^policy_rule_[0-9a-f]{32}$/.test(result.rule_id ?? '') || (command.resource_id && result.rule_id!==command.resource_id)
      || result.version!==(command.operation==='rule_create'?1:Number(command.payload.expected_version)+1))throw Error('原规则回执不一致');
  }else if(command.operation==='rule_delete'){
    if(result.rule_id!==command.resource_id || result.deleted!==true)throw Error('原删除回执不一致');return;
  }else if(command.operation==='preset'){
    if(result.preset_id!==command.resource_id || !Array.isArray(result.rules) || result.rules.some((v:any)=>!/^policy_rule_[0-9a-f]{32}$/.test(v?.rule_id ?? '')))throw Error('原预设回执不一致');return;
  }
  for(const [field,original] of Object.entries(command.payload)){
    if(field==='expected_version')continue;
    if(result[field]!== (typeof original==='string'?original.trim():original))throw Error('审批策略回执内容不一致');
  }
}
export function confirmPolicyReceipt(value:any,command:PolicySubmission):boolean{
  if(value?.state==='not_found' && Object.keys(value).length===1)return false;
  if(value?.state!=='confirmed' || value.operation!==command.operation || value.request_id!==command.key || value.resource_id!==(command.resource_id ?? null))throw Error('原审批策略回执不一致');
  validatePolicyResult(value.result,command);return true;
}
