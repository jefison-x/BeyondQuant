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
  request<{ feedback: ProductFeedbackDetail }>("/items", { method: "POST", body: JSON.stringify({ ...content, idempotency_key: crypto.randomUUID() }) });
export const updateFeedback = (item: ProductFeedbackDetail, content: ProductFeedbackContent) =>
  request<{ feedback: ProductFeedbackDetail }>(`/items/${encodeURIComponent(item.feedback_id)}`, { method: "PUT", body: JSON.stringify({ content, expected_version: item.version, idempotency_key: crypto.randomUUID() }) });
export const previewFeedback = (item: ProductFeedbackDetail) =>
  request<FeedbackPublicationPreview>(`/items/${encodeURIComponent(item.feedback_id)}/preview`, { method: "POST", body: JSON.stringify({ expected_version: item.version }) });
export const submitFeedback = (item: ProductFeedbackDetail, previewHash: string) =>
  request<{ feedback: ProductFeedbackSummary }>(`/items/${encodeURIComponent(item.feedback_id)}/submit`, { method: "POST", body: JSON.stringify({ expected_version: item.version, preview_hash: previewHash, disclosure_confirmed: true, idempotency_key: crypto.randomUUID() }) });
export const withdrawFeedback = (item: ProductFeedbackSummary) =>
  request<{ feedback: ProductFeedbackSummary }>(`/items/${encodeURIComponent(item.feedback_id)}/withdraw`, { method: "POST", body: JSON.stringify({ expected_version: item.version, idempotency_key: crypto.randomUUID() }) });

export const listFeedbackModeration = (params: { status: string; category: string; query: string; limit: number; offset: number }, signal?: AbortSignal) =>
  request<FeedbackModerationPage>(`/moderation/items${query(params)}`, { signal });
export const getFeedbackModeration = (id: string, signal?: AbortSignal) =>
  request<{ feedback: FeedbackModerationItem }>(`/moderation/items/${encodeURIComponent(id)}`, { signal });
export const getFeedbackAudit = (id: string, offset: number, signal?: AbortSignal) =>
  request<FeedbackAuditPage>(`/moderation/items/${encodeURIComponent(id)}/audit${query({ limit: 20, offset })}`, { signal });
export const getFeedbackPublisherStatus = (signal?: AbortSignal) => request<FeedbackPublisherStatus>("/moderation/publisher-status", { signal });
export const moderateFeedback = (item: FeedbackModerationItem, action: "triage" | "accept" | "reject" | "duplicate", rationale: string, canonicalFeedbackId = "") =>
  request<{ feedback: FeedbackModerationItem }>(`/moderation/items/${encodeURIComponent(item.feedback_id)}/${action}`, {
    method: "POST",
    body: JSON.stringify({ expected_version: item.version, rationale, idempotency_key: crypto.randomUUID(), ...(action === "duplicate" ? { canonical_feedback_id: canonicalFeedbackId } : {}) }),
  });
