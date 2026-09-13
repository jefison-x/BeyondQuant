export type ModelCommand={operation:'binding'|'delete_profile';resource_id:string;expected_version:number;profile_id:string|null};
const storageKey=(scope:string)=>'byq.model-command.v1:'+scope;
function normalize(value:unknown):ModelCommand {
  if(!value || typeof value!=='object' || Array.isArray(value))throw Error('原模型操作记录无效');
  const v=value as ModelCommand;
  if(Object.keys(v).some(k=>!['operation','resource_id','expected_version','profile_id'].includes(k))
    || !Number.isSafeInteger(v.expected_version) || v.expected_version<0)throw Error('原模型操作记录无效');
  if(v.operation==='binding'){
    if(v.resource_id!=='byq-product' || (v.profile_id!==null && !/^profile_[0-9a-f]{32}$/.test(v.profile_id)))throw Error('原模型绑定记录无效');
  }else if(v.operation==='delete_profile'){
    if(v.expected_version<1 || !/^profile_[0-9a-f]{32}$/.test(v.resource_id) || v.profile_id!==v.resource_id)throw Error('原模型删除记录无效');
  }else throw Error('不支持的模型操作');
  return {operation:v.operation,resource_id:v.resource_id,expected_version:v.expected_version,profile_id:v.profile_id};
}
export function readModelCommand(scope:string):ModelCommand|null {
  const raw=localStorage.getItem(storageKey(scope));if(raw===null)return null;
  if(raw.length>2048)throw Error('原模型操作记录超出范围');return normalize(JSON.parse(raw));
}
export function beginModelCommand(scope:string,value:ModelCommand):ModelCommand{
  const command=normalize(value),original=readModelCommand(scope);
  if(original && JSON.stringify(original)!==JSON.stringify(command))throw Error('上一笔模型操作尚未确认，请先核对');
  if(!original)localStorage.setItem(storageKey(scope),JSON.stringify(command));return original ?? command;
}
export function finishModelCommand(scope:string,command:ModelCommand){
  if(JSON.stringify(readModelCommand(scope))===JSON.stringify(command))localStorage.removeItem(storageKey(scope));
}
export function confirmModelCommand(value:any,command:ModelCommand):boolean{
  if(value?.state==='not_found' && Object.keys(value).length===1)return false;
  if(value?.state!=='confirmed' || value.operation!==command.operation || value.resource_id!==command.resource_id
    || value.profile_id!==command.profile_id || value.expected_version!==command.expected_version
    || value.committed_version!==command.expected_version+1)throw Error('原模型操作回执不一致');
  return true;
}
