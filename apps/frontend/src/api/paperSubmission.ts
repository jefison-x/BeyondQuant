import {createRequestId} from '@/utils/requestId';
import type {PaperCommand} from './paper';
const name = (scope:string) => 'byq.paper-command.v1:'+scope;
export function readPaperSubmission(scope:string):PaperCommand|null {
  const raw = localStorage.getItem(name(scope));if(raw === null) return null;
  if(raw.length > 4*1024*1024) throw Error('原模拟账户操作记录超出范围');
  const value = JSON.parse(raw);
  if(!value || typeof value.key !== 'string' || !/^[A-Za-z0-9_-]{8,96}$/.test(value.key)
    || !['create','import','order','settlement','controls','rebind','delete'].includes(value.operation)
    || !value.payload || typeof value.payload !== 'object' || Array.isArray(value.payload)
    || (!['create','import'].includes(value.operation) && !/^paper_account_[0-9a-f]{32}$/.test(value.account_id ?? ''))) throw Error('原模拟账户操作记录无法读取');
  return value;
}
export function beginPaperSubmission(scope:string,input:Omit<PaperCommand,'key'>):PaperCommand {
  const pending = readPaperSubmission(scope), clean = JSON.parse(JSON.stringify(input));
  if(pending) {
    const {key,...original} = pending;
    if(JSON.stringify(original) !== JSON.stringify(clean)) throw Error('上一笔模拟账户操作尚未确认，请先核对原请求');
    return pending;
  }
  const value = {...clean,key:createRequestId()}, raw = JSON.stringify(value);
  if(raw.length > 4*1024*1024) throw Error('模拟账户操作超出范围');
  localStorage.setItem(name(scope),raw); return value;
}
export function finishPaperSubmission(scope:string,key:string) {
  if(readPaperSubmission(scope)?.key === key) localStorage.removeItem(name(scope));
}
