import {createRequestId} from '@/utils/requestId';
export type CredentialWrite = {operation:'create'|'update'|'revoke';key:string;credential_id?:string;metadata:Record<string,string|number|boolean>};
const storageKey=(scope:string)=>'byq.credential-write.v1:'+scope;
const metadataFields=['provider','label','status','expected_version','has_secret'];
export function readCredentialWrite(scope:string):CredentialWrite|null {
  const raw=localStorage.getItem(storageKey(scope));if(raw===null)return null;
  if(raw.length>4096)throw Error('原凭据请求标识无法读取');
  const value=JSON.parse(raw);
  if(!value || Object.keys(value).some(k=>!['operation','key','credential_id','metadata'].includes(k))
    || !['create','update','revoke'].includes(value.operation) || !/^[A-Za-z0-9_-]{8,96}$/.test(value.key ?? '')
    || (value.operation!=='create' && !/^cred_[0-9a-f]{32}$/.test(value.credential_id ?? ''))
    || !value.metadata || typeof value.metadata!=='object' || Array.isArray(value.metadata)
    || Object.keys(value.metadata).some(k=>!metadataFields.includes(k) || !['string','number','boolean'].includes(typeof value.metadata[k]))) throw Error('原凭据请求标识无法读取');
  return value;
}
export function beginCredentialWrite(scope:string,operation:CredentialWrite['operation'],payload:Record<string,unknown>,credential_id?:string):CredentialWrite {
  // Never spread a credential request into persistent storage; secret remains memory-only.
  const metadata:CredentialWrite['metadata']={has_secret:typeof payload.secret==='string'};
  for(const field of metadataFields.filter(k=>k!=='has_secret'))if(payload[field]!==undefined) {
    if(!['string','number','boolean'].includes(typeof payload[field]))throw Error('凭据请求参数无效');
    metadata[field]=payload[field] as string|number|boolean;
  }
  const input={operation,...(credential_id?{credential_id}:{}),metadata},pending=readCredentialWrite(scope);
  if(pending) {
    const {key,...original}=pending;
    if(JSON.stringify(original)!==JSON.stringify(input))throw Error('上一笔凭据操作尚未确认，请先核对原请求');
    return pending;
  }
  const value={...input,key:createRequestId()},raw=JSON.stringify(value);
  if(raw.length>4096)throw Error('凭据请求标识超出范围');
  localStorage.setItem(storageKey(scope),raw);return value;
}
export function finishCredentialWrite(scope:string,key:string) {
  if(readCredentialWrite(scope)?.key===key)localStorage.removeItem(storageKey(scope));
}
