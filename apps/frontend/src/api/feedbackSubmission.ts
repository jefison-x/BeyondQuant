import { createRequestId } from '@/utils/requestId';
import type { FeedbackCommand } from './feedback';
const name = (scope:string) => 'byq.feedback-command.v1:'+scope;
export function readFeedbackSubmission(scope:string):FeedbackCommand|null {
  const raw = localStorage.getItem(name(scope));
  if(raw === null) return null;
  if(raw.length > 128*1024) throw Error('反馈原请求超出范围');
  const value = JSON.parse(raw);
  if(!value || typeof value.key !== 'string' || !/^[A-Za-z0-9_-]{8,96}$/.test(value.key)
    || !['create','update','submit','withdraw'].includes(value.operation) || !value.payload || typeof value.payload !== 'object' || Array.isArray(value.payload)
    || (value.operation !== 'create' && !/^feedback_[0-9a-f]{32}$/.test(value.feedback_id ?? ''))) throw Error('反馈原请求记录无法读取');
  return value;
}
export function beginFeedbackSubmission(scope:string, input:Omit<FeedbackCommand,'key'>):FeedbackCommand {
  const pending = readFeedbackSubmission(scope);
  const clean = JSON.parse(JSON.stringify(input));
  if(pending) {
    const {key,...original} = pending;
    if(JSON.stringify(original) !== JSON.stringify(clean)) throw Error('上一笔反馈尚未确认，请先核对原请求');
    return pending;
  }
  const value = {...clean,key:createRequestId()};
  const raw = JSON.stringify(value);
  if(raw.length > 128*1024) throw Error('反馈请求超出范围');
  localStorage.setItem(name(scope),raw);
  return value;
}
export function finishFeedbackSubmission(scope:string,key:string) {
  if(readFeedbackSubmission(scope)?.key === key) localStorage.removeItem(name(scope));
}
