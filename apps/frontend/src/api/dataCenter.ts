import type { DataCenterStatus, DataSyncJob, MarketSyncAutomationConfig, SecurityCataloguePage, SecurityMasterSyncJob } from "./types";

const ROOT = "/api/product/data-center";

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
    throw new Error(body.error?.message ?? body.detail ?? "data center request failed");
  }
  return (await response.json()) as T;
}

export function getDataCenterStatus(): Promise<DataCenterStatus> {
  return request("/status");
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
