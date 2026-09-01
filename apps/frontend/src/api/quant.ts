import type { BacktestJob, BacktestResult } from "./types";

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

export async function getBacktest(jobId: string, token: string): Promise<BacktestJob> {
  const body = await request<{ job: BacktestJob }>(`/backtests/${encodeURIComponent(jobId)}`, token);
  return body.job ?? (body as unknown as BacktestJob);
}

export function getBacktestResult(jobId: string, token: string): Promise<{ job_id: string; result: BacktestResult }> {
  return request(`/backtests/${encodeURIComponent(jobId)}/result`, token);
}

export function getBacktestManifest(jobId: string, token: string): Promise<{ job_id: string; input_manifest: Record<string, unknown> }> {
  return request(`/backtests/${encodeURIComponent(jobId)}/manifest`, token);
}

export async function runBacktest(jobId: string, token: string): Promise<BacktestJob> {
  const body = await request<{ job: BacktestJob }>(`/backtests/${encodeURIComponent(jobId)}/run`, token, { method: "POST" });
  return body.job ?? (body as unknown as BacktestJob);
}

export async function cancelBacktest(jobId: string, token: string): Promise<BacktestJob> {
  const body = await request<{ job: BacktestJob }>(`/backtests/${encodeURIComponent(jobId)}/cancel`, token, { method: "POST" });
  return body.job ?? (body as unknown as BacktestJob);
}

export async function deleteBacktest(jobId: string, token: string): Promise<BacktestJob> {
  const body = await request<{ job: BacktestJob }>(`/backtests/${encodeURIComponent(jobId)}`, token, { method: "DELETE" });
  return body.job ?? (body as unknown as BacktestJob);
}

export function exportStrategyVersion(artifactId: string, token: string): Promise<Record<string, unknown>> {
  return request(`/strategies/versions/${encodeURIComponent(artifactId)}/export`, token);
}

export function listStrategies(
  token: string,
  options: { lifecycle?: "active" | "superseded" | "all"; limit?: number; offset?: number } = {},
): Promise<{ strategies: Array<Record<string, unknown>>; total: number; limit: number; offset: number }> {
  const params = new URLSearchParams({
    lifecycle: options.lifecycle ?? "active",
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
  });
  return request(`/strategies?${params.toString()}`, token);
}

export function listFactors(token: string): Promise<{ factors: Array<Record<string, unknown>> }> {
  return request(`/factors`, token);
}

export function listBacktests(token: string): Promise<{ backtests: Array<Record<string, unknown>> }> {
  return request(`/backtests`, token);
}

export function listBacktestOptions(token: string): Promise<{ options: Array<Record<string, unknown>> }> {
  return request(`/backtests/options`, token);
}

export function listSignalSnapshots(token: string): Promise<{ snapshots: Array<Record<string, unknown>> }> {
  return request(`/signal-snapshots`, token);
}

export function createSignalProducerJob(
  payload: Record<string, unknown>,
  token: string,
): Promise<{ job: Record<string, unknown> }> {
  return request(`/signal-producer/jobs`, token, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getSignalProducerJob(
  jobId: string,
  token: string,
): Promise<{ job: Record<string, unknown> }> {
  return request(`/signal-producer/jobs/${encodeURIComponent(jobId)}`, token);
}

export function listSignalProducerJobs(
  token: string,
): Promise<{ jobs: Array<Record<string, unknown>> }> {
  return request(`/signal-producer/jobs`, token);
}

export function submitBacktest(
  payload: Record<string, unknown>,
  token: string,
): Promise<{ job: BacktestJob }> {
  return request(`/backtests`, token, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function validateStrategy(payload: Record<string, unknown>, token: string): Promise<Record<string, unknown>> {
  return request(`/strategies/validate`, token, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function saveStrategyDraft(payload: Record<string, unknown>, token: string): Promise<Record<string, unknown>> {
  return request(`/strategies/drafts`, token, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteStrategyDraft(artifactId: string, token: string): Promise<Record<string, unknown>> {
  return request(`/strategies/drafts/${encodeURIComponent(artifactId)}`, token, { method: "DELETE" });
}

export function getStrategyVersions(strategyId: string, token: string): Promise<Record<string, unknown>> {
  return request(`/strategies/${encodeURIComponent(strategyId)}/versions`, token);
}

export function getStrategyBacktestCount(strategyId: string, token: string): Promise<Record<string, unknown>> {
  return request(`/strategies/${encodeURIComponent(strategyId)}/backtest-count`, token);
}

export function getStrategyApproval(artifactId: string, token: string): Promise<{ approval: Record<string, unknown> | null }> {
  return request(`/strategies/versions/${encodeURIComponent(artifactId)}/approval`, token);
}

export function createStrategyVersion(payload: Record<string, unknown>, token: string): Promise<Record<string, unknown>> {
  return request(`/strategies/versions`, token, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function approveStrategyVersion(
  payload: Record<string, unknown>,
  token: string,
): Promise<Record<string, unknown>> {
  return request(`/strategies/approvals`, token, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}
