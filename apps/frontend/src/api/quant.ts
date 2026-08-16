import type { BacktestJob } from "./types";

const ROOT = "/api/product";

async function request<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${ROOT}${path}`, {
    ...init,
    credentials: "include",
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
    throw new Error(body.error?.message ?? "quant request failed");
  }
  return (await response.json()) as T;
}

export function getResearchEntity(
  entityType: "tasks" | "experiments" | "artifacts",
  entityId: string,
  token: string,
): Promise<Record<string, unknown>> {
  return request(`/research/${entityType}/${encodeURIComponent(entityId)}`, token);
}

export function getBacktest(jobId: string, token: string): Promise<BacktestJob> {
  return request(`/backtests/${encodeURIComponent(jobId)}`, token);
}

export function runBacktest(jobId: string, token: string): Promise<BacktestJob> {
  return request(`/backtests/${encodeURIComponent(jobId)}/run`, token, { method: "POST" });
}

export function cancelBacktest(jobId: string, token: string): Promise<BacktestJob> {
  return request(`/backtests/${encodeURIComponent(jobId)}/cancel`, token, { method: "POST" });
}

export function exportStrategyVersion(artifactId: string, token: string): Promise<Record<string, unknown>> {
  return request(`/strategies/versions/${encodeURIComponent(artifactId)}/export`, token);
}

export function listStrategies(token: string): Promise<{ strategies: Array<Record<string, unknown>> }> {
  return request(`/strategies`, token);
}

export function listFactors(token: string): Promise<{ factors: Array<Record<string, unknown>> }> {
  return request(`/factors`, token);
}

export function listBacktests(token: string): Promise<{ backtests: Array<Record<string, unknown>> }> {
  return request(`/backtests`, token);
}
