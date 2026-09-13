import { createRequestId } from '@/utils/requestId';
import type { FeedbackModerationCommand } from './feedback';
const name=(scope:string)=>'byq.feedback-moderation-command.v1:'+scope;
export function readModerationSubmission(scope:string):FeedbackModerationCommand|null {
  const raw=localStorage.getItem(name(scope));
  if(raw===null) return null;
  if(raw.length>16*1024) throw Error('审核原请求记录超出范围');
  const value=JSON.parse(raw);
  if(!value || !['triage','accept','reject','duplicate'].includes(value.action)
    || typeof value.key!=='string' || !/^[A-Za-z0-9_-]{8,96}$/.test(value.key)
    || !/^feedback_[0-9a-f]{32}$/.test(value.feedback_id ?? '')
    || !Number.isInteger(value.payload?.expected_version) || value.payload.expected_version<1
    || typeof value.payload.rationale!=='string' || value.payload.rationale.length<2 || value.payload.rationale.length>1000
    || (value.action==='duplicate' && !/^feedback_[0-9a-f]{32}$/.test(value.payload.canonical_feedback_id ?? '')))
    throw Error('审核原请求记录无法读取');
  return value;
}
export function beginModerationSubmission(scope:string,input:Omit<FeedbackModerationCommand,'key'>):FeedbackModerationCommand {
  if(readModerationSubmission(scope)) throw Error('上一笔审核尚未确认，请先核对原请求');
  const value={...input,key:createRequestId()};
  const raw=JSON.stringify(value);
  if(raw.length>16*1024) throw Error('审核请求超出范围');
  localStorage.setItem(name(scope),raw);return value;
}
export function finishModerationSubmission(scope:string,key:string) {
  if(readModerationSubmission(scope)?.key===key) localStorage.removeItem(name(scope));
}
