import type { DataCenterStatus, DataSyncJob } from "./types";

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
