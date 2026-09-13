import {readPendingText,writePendingText} from './pendingStorage';
import { createRequestId } from "@/utils/requestId";

// One unresolved submission per owner/workspace. Never silently replace its identity.
export interface TaskSubmission { key: string; title: string; objective: string }
const storageKey = (scope: string) => `byq.research-submission.v1:${scope}`;

export function readTaskSubmission(scope: string): TaskSubmission | null {
  const raw = readPendingText(storageKey(scope),32768,'上次提交记录超出范围，请先核查研究任务。');
  if (raw === null) return null;
  const value = JSON.parse(raw) as TaskSubmission;
  if (!value || typeof value.key !== "string" || !/^[a-zA-Z0-9_-]{8,96}$/.test(value.key)
      || typeof value.title !== "string" || !value.title.trim() || value.title.length > 200
      || typeof value.objective !== "string" || !value.objective.trim() || value.objective.length > 4000) {
    throw new Error("上次提交记录无法读取，请先核查研究任务，勿重复创建。");
  }
  return { key: value.key, title: value.title, objective: value.objective };
}

export function beginTaskSubmission(scope: string, title: string, objective: string): TaskSubmission {
  const pending = readTaskSubmission(scope);
  if (pending) {
    if (pending.title !== title || pending.objective !== objective) {
      throw new Error("上次提交结果尚未确认，请先核对原任务。");
    }
    return pending;
  }
  const value = { key: createRequestId(), title, objective };
  // Fail before the write request if durable browser storage is unavailable.
  writePendingText(storageKey(scope),JSON.stringify(value),32768,'上次提交记录超出范围，请先核查研究任务。');
  return value;
}

export function finishTaskSubmission(scope: string, key: string): void {
  if (readTaskSubmission(scope)?.key === key) localStorage.removeItem(storageKey(scope));
}
