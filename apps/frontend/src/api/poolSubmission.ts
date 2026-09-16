import {readPendingText,writePendingText} from './pendingStorage';
import { createRequestId } from '@/utils/requestId';
import type { PoolCreationKind } from './paper';
export interface PoolSubmission {key:string; kind:PoolCreationKind; payload:Record<string,unknown>}
const storageKey = (scope:string) => 'byq.pool-creation.v1:'+scope;
export function readPoolSubmission(scope:string): PoolSubmission | null {
  const raw = readPendingText(storageKey(scope),128*1024,'股票池原请求超出范围');
  if (raw === null) return null;

  const value = JSON.parse(raw);
  if (!value || typeof value.key !== "string" || !/^[A-Za-z0-9_-]{8,96}$/.test(value.key) || !['custom','index','dynamic'].includes(value.kind)
      || !value.payload || typeof value.payload !== 'object' || Array.isArray(value.payload)) throw new Error('原股票池提交记录无法读取，请先核查。');
  return value;
}
export function beginPoolSubmission(scope:string, kind:PoolCreationKind, payload:Record<string,unknown>): PoolSubmission {
  const pending = readPoolSubmission(scope);
  const clean = JSON.parse(JSON.stringify(payload));
  if (pending) {
    if (pending.kind !== kind || JSON.stringify(pending.payload) !== JSON.stringify(clean)) throw new Error('上次股票池提交尚未确认，请先核对原请求。');
    return pending;
  }
  const value = {key:createRequestId(), kind, payload:clean};
  const raw = JSON.stringify(value);

  writePendingText(storageKey(scope),raw,128*1024,'股票池原请求超出范围'); // Before any network write.
  return value;
}
export function finishPoolSubmission(scope:string, key:string) {
  if (readPoolSubmission(scope)?.key === key) localStorage.removeItem(storageKey(scope));
}
