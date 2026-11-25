import type { DataCenterStatus, DataReadinessResult, DataSyncJob, MarketSyncAutomationConfig, SecurityCataloguePage, SecurityMasterSyncJob } from "./types";
import type { ResearchPreparationScope } from "@/researchPreparation";

const ROOT = "/api/product/data-center";

export class DataCenterRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "DataCenterRequestError";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${ROOT}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init.body ? { "content-type": "application/json" } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: { message?: string }; detail?: string };
    throw new DataCenterRequestError(body.error?.message ?? body.detail ?? "data center request failed", response.status);
  }
  return (await response.json()) as T;
}

export function getDataCenterStatus(view: "summary" | "full" = "summary"): Promise<DataCenterStatus> {
  return request(`/status?view=${view}`);
}

export function queryDataReadiness(payload: {
  symbols: string[]; start_date: string; end_date: string; use_case: "research" | "backtest";
  data_requirements?: { daily_basic?: string[]; fundamentals?: string[] };
}): Promise<DataReadinessResult> {
  return request("/readiness", { method: "POST", body: JSON.stringify(payload) });
}

export interface ResearchPreparationSubmission {
  request_id: string | null;
  status: string;
  retry_token?: string | null;
  failure_reason?: string | null;
  failure_message?: string | null;
  error?: string | null;
}

export interface ConversationResearchPreparationReceipt extends ResearchPreparationSubmission {
  scope: ResearchPreparationScope;
  auto_continuation?: {
    status: "waiting" | "dispatching" | "bound" | "succeeded" | "failed" | "cancelled";
  };
}

export function createResearchPreparation(payload: {
  symbols: string[]; start_date: string; end_date: string; use_case: "research";
  data_requirements?: { daily_basic?: string[]; fundamentals?: string[] };
}): Promise<ResearchPreparationSubmission> {
  return request("/research-preparations", { method: "POST", body: JSON.stringify(payload) });
}

export function getResearchPreparation(requestId: string): Promise<ResearchPreparationSubmission> {
  return request(`/research-preparations/${encodeURIComponent(requestId)}`);
}

export function retryResearchPreparation(
  requestId: string,
  retryToken: string,
): Promise<ResearchPreparationSubmission> {
  return request(`/research-preparations/${encodeURIComponent(requestId)}/retry`, {
    method: "POST", body: JSON.stringify({ retry_token: retryToken }),
  });
}

export function createConversationResearchPreparation(
  conversationId: string,
  scope: ResearchPreparationScope,
): Promise<ConversationResearchPreparationReceipt> {
  return request(`/conversations/${encodeURIComponent(conversationId)}/research-preparations`, {
    method: "POST", body: JSON.stringify(scope),
  });
}

export function listConversationResearchPreparations(
  conversationId: string,
): Promise<{ preparations: ConversationResearchPreparationReceipt[] }> {
  return request(`/conversations/${encodeURIComponent(conversationId)}/research-preparations`);
}

export function getConversationResearchPreparation(
  conversationId: string,
  requestId: string,
): Promise<ConversationResearchPreparationReceipt> {
  return request(`/conversations/${encodeURIComponent(conversationId)}/research-preparations/${encodeURIComponent(requestId)}`);
}

export function retryConversationResearchPreparation(
  conversationId: string,
  requestId: string,
  retryToken: string,
): Promise<ConversationResearchPreparationReceipt> {
  return request(`/conversations/${encodeURIComponent(conversationId)}/research-preparations/${encodeURIComponent(requestId)}/retry`, {
    method: "POST", body: JSON.stringify({ retry_token: retryToken }),
  });
}

export function stopConversationResearchContinuation(
  conversationId: string,
  requestId: string,
): Promise<ConversationResearchPreparationReceipt> {
  return request(`/conversations/${encodeURIComponent(conversationId)}/research-preparations/${encodeURIComponent(requestId)}/stop-continuation`, {
    method: "POST",
  });
}

export function createDataSourceCredential(payload: Record<string, unknown>): Promise<{ credential: Record<string, unknown> }> {
  return request("/source/credentials", { method: "POST", body: JSON.stringify(payload) });
}

export function updateDataSourceCredential(credentialId: string, payload: Record<string, unknown>): Promise<{ credential: Record<string, unknown> }> {
  return request(`/source/credentials/${credentialId}`, { method: "PUT", body: JSON.stringify(payload) });
}

export function revokeDataSourceCredential(credentialId: string, payload: Record<string, unknown>): Promise<{ credential: Record<string, unknown> }> {
  return request(`/source/credentials/${credentialId}/revoke`, { method: "POST", body: JSON.stringify(payload) });
}

export function testDataSource(payload: { symbol: string; trade_date: string }): Promise<{ test: Record<string, unknown> }> {
  return request("/source/test", { method: "POST", body: JSON.stringify(payload) });
}

export function createDataSyncJob(payload: Record<string, unknown>): Promise<{ job: DataSyncJob; created: boolean }> {
  return request("/sync-jobs", { method: "POST", body: JSON.stringify(payload) });
}

export function getDataSyncJob(jobId: string): Promise<{ job: DataSyncJob }> {
  return request(`/sync-jobs/${jobId}`);
}

export function updateMarketSyncAutomation(payload: {
  enabled: boolean;
  schedule_time: string;
  catchup_days: number;
  security_master_enabled: boolean;
  expected_version: number;
  idempotency_key: string;
}): Promise<{ config: MarketSyncAutomationConfig }> {
  return request("/automation/config", { method: "PUT", body: JSON.stringify(payload) });
}

export function runMarketSyncNow(): Promise<{ run_request: Record<string, unknown>; created: boolean }> {
  return request("/automation/run-now", {
    method: "POST",
    body: JSON.stringify({ idempotency_key: `browser-market-run-${Date.now()}` }),
  });
}

export function createSecurityMasterSyncJob(): Promise<{ job: SecurityMasterSyncJob; created: boolean }> {
  return request("/security-master/sync-jobs", {
    method: "POST",
    body: JSON.stringify({ idempotency_key: `browser-security-master-${Date.now()}` }),
  });
}

export function getSecurityMasterSyncJob(jobId: string): Promise<{ job: SecurityMasterSyncJob }> {
  return request(`/security-master/sync-jobs/${encodeURIComponent(jobId)}`);
}

export function listSecurities(params: {
  query?: string;
  statuses?: string[];
  exchanges?: string[];
  limit?: number;
  offset?: number;
} = {}): Promise<SecurityCataloguePage> {
  const query = new URLSearchParams();
  if (params.query) query.set("query", params.query);
  if (params.statuses?.length) query.set("statuses", params.statuses.join(","));
  if (params.exchanges?.length) query.set("exchanges", params.exchanges.join(","));
  query.set("limit", String(params.limit ?? 50));
  query.set("offset", String(params.offset ?? 0));
  return request(`/securities?${query.toString()}`);
}
