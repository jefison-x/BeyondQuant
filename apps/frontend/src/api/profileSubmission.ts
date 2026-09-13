export type ProfileInput={credential_id:string;key_name:string;display_name:string;provider:string;model:string;temperature:number;reasoning_enabled:boolean};
const fields=['credential_id','key_name','display_name','provider','model','temperature','reasoning_enabled'] as const;
const storageKey=(scope:string)=>'byq.profile-creation.v1:'+scope;
export function profileInput(value:unknown):ProfileInput {
  if(!value || typeof value!=='object' || Array.isArray(value))throw Error('模型档案参数无效');
  const v=value as Record<string,unknown>;
  if(Object.keys(v).some(k=>!fields.includes(k as typeof fields[number])))throw Error('模型档案参数无效');
  for(const field of fields.slice(0,5))if(typeof v[field]!=='string' || !(v[field] as string).trim())throw Error('模型档案参数无效');
  if(!/^cred_[0-9a-f]{32}$/.test(String(v.credential_id)) || typeof v.temperature!=='number' || !Number.isFinite(v.temperature) || v.temperature<0 || v.temperature>2 || typeof v.reasoning_enabled!=='boolean')throw Error('模型档案参数无效');
  return Object.fromEntries(fields.map(k=>[k,typeof v[k]==='string'?(v[k] as string).trim():v[k]])) as ProfileInput;
}
export function readProfileSubmission(scope:string):ProfileInput|null {
  const raw=localStorage.getItem(storageKey(scope));if(raw===null)return null;
  if(raw.length>4096)throw Error('原模型档案记录超出范围');return profileInput(JSON.parse(raw));
}
export function beginProfileSubmission(scope:string,payload:unknown):ProfileInput {
  const input=profileInput(payload),prior=readProfileSubmission(scope);
  if(prior && JSON.stringify(prior)!==JSON.stringify(input))throw Error('上一笔模型档案尚未确认，请先核对原请求');
  const raw=JSON.stringify(input);if(raw.length>4096)throw Error('模型档案参数超出范围');
  if(!prior)localStorage.setItem(storageKey(scope),raw);return prior ?? input;
}
export function finishProfileSubmission(scope:string,input:ProfileInput){
  if(JSON.stringify(readProfileSubmission(scope))===JSON.stringify(input))localStorage.removeItem(storageKey(scope));
}
export function confirmProfileReceipt(value:any,input:ProfileInput):string|null {
  if(value?.state==='not_found' && Object.keys(value).length===1)return null;
  if(value?.state!=='confirmed' || !/^profile_[0-9a-f]{32}$/.test(value.profile_id ?? '') || value.committed_version!==1
    || JSON.stringify(profileInput(value.input))!==JSON.stringify(input))throw Error('原模型档案回执与提交内容不一致');
  return value.profile_id;
}
