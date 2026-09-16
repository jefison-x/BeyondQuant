import type {
  FeedbackAuditPage,
  FeedbackModerationItem,
  FeedbackModerationPage,
  FeedbackPublicationPreview,
  FeedbackPublisherStatus,
  ProductFeedbackContent,
  ProductFeedbackDetail,
  ProductFeedbackOptions,
  ProductFeedbackPage,
  ProductFeedbackSummary,
} from "./types";
import { ProductApiError } from "./client";
import { createRequestId } from "@/utils/requestId";

const ROOT = "/api/product/feedback";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${ROOT}${path}`, {
    ...init,
    credentials: "include",
    headers: { "content-type": "application/json", ...(init.headers ?? {}) },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { error?: { code?: string; message?: string }; detail?: string };
    throw new ProductApiError(response.status, body.error?.code ?? "feedback_request_failed", body.error?.message ?? body.detail ?? "反馈请求失败");
  }
  return response.json() as Promise<T>;
}

function query(params: Record<string, string | number>): string {
  return `?${new URLSearchParams(Object.entries(params).map(([key, value]) => [key, String(value)])).toString()}`;
}

export const getFeedbackOptions = (signal?: AbortSignal) => request<ProductFeedbackOptions>("/options", { signal });
export const listFeedback = (params: { status: string; category: string; query: string; limit: number; offset: number }, signal?: AbortSignal) =>
  request<ProductFeedbackPage>(`/items${query(params)}`, { signal });
export const getFeedback = (id: string, signal?: AbortSignal) =>
  request<{ feedback: ProductFeedbackDetail }>(`/items/${encodeURIComponent(id)}`, { signal });
export const createFeedback = (content: ProductFeedbackContent) =>
  request<{ feedback: ProductFeedbackDetail }>("/items", { method: "POST", body: JSON.stringify({ ...content, idempotency_key: createRequestId() }) });
export const updateFeedback = (item: ProductFeedbackDetail, content: ProductFeedbackContent) =>
  request<{ feedback: ProductFeedbackDetail }>(`/items/${encodeURIComponent(item.feedback_id)}`, { method: "PUT", body: JSON.stringify({ content, expected_version: item.version, idempotency_key: createRequestId() }) });
export const previewFeedback = (item: ProductFeedbackDetail) =>
  request<FeedbackPublicationPreview>(`/items/${encodeURIComponent(item.feedback_id)}/preview`, { method: "POST", body: JSON.stringify({ expected_version: item.version }) });
export const submitFeedback = (item: ProductFeedbackDetail, previewHash: string) =>
  request<{ feedback: ProductFeedbackSummary }>(`/items/${encodeURIComponent(item.feedback_id)}/submit`, { method: "POST", body: JSON.stringify({ expected_version: item.version, preview_hash: previewHash, disclosure_confirmed: true, idempotency_key: createRequestId() }) });
export const withdrawFeedback = (item: ProductFeedbackSummary) =>
  request<{ feedback: ProductFeedbackSummary }>(`/items/${encodeURIComponent(item.feedback_id)}/withdraw`, { method: "POST", body: JSON.stringify({ expected_version: item.version, idempotency_key: createRequestId() }) });

export const listFeedbackModeration = (params: { status: string; category: string; query: string; limit: number; offset: number }, signal?: AbortSignal) =>
  request<FeedbackModerationPage>(`/moderation/items${query(params)}`, { signal });
export const getFeedbackModeration = (id: string, signal?: AbortSignal) =>
  request<{ feedback: FeedbackModerationItem }>(`/moderation/items/${encodeURIComponent(id)}`, { signal });
export const getFeedbackAudit = (id: string, offset: number, signal?: AbortSignal) =>
  request<FeedbackAuditPage>(`/moderation/items/${encodeURIComponent(id)}/audit${query({ limit: 20, offset })}`, { signal });
export const getFeedbackPublisherStatus = (signal?: AbortSignal) => request<FeedbackPublisherStatus>("/moderation/publisher-status", { signal });
export type FeedbackCommand = {operation:'create'|'update'|'submit'|'withdraw';key:string;feedback_id?:string;payload:Record<string,unknown>};
export async function sendFeedbackCommand(command:FeedbackCommand) {
  const path = command.operation === 'create' ? '/items' : '/items/'+encodeURIComponent(command.feedback_id!)+(command.operation === 'update' ? '' : '/'+command.operation);
  const value = await request<{feedback:ProductFeedbackSummary}>(path,{method:command.operation === 'update'?'PUT':'POST',
    signal:AbortSignal.timeout(15000),body:JSON.stringify({...command.payload,idempotency_key:command.key})});
  if(!/^feedback_[0-9a-f]{32}$/.test(value.feedback?.feedback_id ?? '') || (command.feedback_id && value.feedback.feedback_id !== command.feedback_id)) throw Error('反馈回执未确认，请核对原请求');
  return value;
}
export async function reconcileFeedbackCommand(command:FeedbackCommand) {
  const value = await request<{state:'confirmed';feedback:ProductFeedbackSummary}|{state:'not_found'}>('/receipts'+query({operation:command.operation,idempotency_key:command.key,...(command.feedback_id ? {feedback_id:command.feedback_id}:{})}),{signal:AbortSignal.timeout(15000)});
  if(value.state === 'not_found' && Object.keys(value).length === 1) return value;
  if(value.state !== 'confirmed' || !/^feedback_[0-9a-f]{32}$/.test(value.feedback?.feedback_id ?? '') || (command.feedback_id && value.feedback.feedback_id !== command.feedback_id)) throw Error('反馈原请求核对结果不完整');
  return value;
}

export type FeedbackModerationCommand = {action:'triage'|'accept'|'reject'|'duplicate';key:string;feedback_id:string;payload:{expected_version:number;rationale:string;canonical_feedback_id?:string}};
function validateModerationResult(command:FeedbackModerationCommand,feedback:FeedbackModerationItem) {
  const status = {triage:'triaged',accept:'accepted',reject:'rejected',duplicate:'duplicate'}[command.action];
  if(feedback?.feedback_id !== command.feedback_id || feedback.status !== status || feedback.version !== command.payload.expected_version+1)
    throw Error('审核原回执未确认，请核对原请求');
}
export async function sendFeedbackModerationCommand(command:FeedbackModerationCommand) {
  const value = await request<{feedback:FeedbackModerationItem}>(`/moderation/items/${encodeURIComponent(command.feedback_id)}/${command.action}`,{
    method:'POST',signal:AbortSignal.timeout(15000),body:JSON.stringify({...command.payload,idempotency_key:command.key})});
  validateModerationResult(command,value.feedback);return value;
}
export async function reconcileFeedbackModerationCommand(command:FeedbackModerationCommand) {
  const value = await request<{state:'confirmed';feedback:FeedbackModerationItem}|{state:'not_found'}>('/moderation/receipts'+query({
    feedback_id:command.feedback_id,action:command.action,idempotency_key:command.key}),{signal:AbortSignal.timeout(15000)});
  if(value.state==='not_found' && Object.keys(value).length===1) return value;
  if(value.state!=='confirmed') throw Error('审核原请求核对结果不完整');
  validateModerationResult(command,value.feedback);return value;
}
