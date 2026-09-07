const ROOT = "/api/product";

export class ResearchRequestError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

async function getJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${ROOT}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init.body ? { "content-type": "application/json" } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
    throw new ResearchRequestError(body.error?.message ?? "research request failed", response.status);
  }
  return (await response.json()) as T;
}

export function getResearchEntity(
  entityType: "tasks" | "experiments" | "artifacts",
  entityId: string,
): Promise<Record<string, unknown>> {
  return getJson(`/research/${entityType}/${encodeURIComponent(entityId)}`);
}

export function getApproval(approvalId: string): Promise<Record<string, unknown>> {
  return getJson(`/approvals/${encodeURIComponent(approvalId)}`);
}

export function listArtifacts(): Promise<{ artifacts: Array<Record<string, unknown>> }> {
  return getJson("/research/artifacts");
}

export function listTasks(): Promise<{ tasks: Array<Record<string, unknown>> }> {
  return getJson("/research/tasks");
}

export function listTaskOptions(limit = 50): Promise<{ tasks: Array<Record<string, unknown>> }> {
  return getJson(`/research/task-options?limit=${limit}`);
}

export async function createTask(
  title: string,
  objective: string,
  idempotencyKey?: string,
): Promise<Record<string, unknown>> {
  try {
    return await getJson("/research/tasks", {
      method: "POST",
      ...(idempotencyKey ? { headers: { "x-idempotency-key": idempotencyKey } } : {}),
      body: JSON.stringify({ title, objective }),
    });
  } catch (error) {
    if (error instanceof ResearchRequestError) throw error;
    throw new ResearchRequestError("提交结果尚未确认，请核对本次提交；不要新建任务。", 503);
  }
}

export function listExperiments(): Promise<{ experiments: Array<Record<string, unknown>> }> {
  return getJson("/research/experiments");
}

export function listApprovals(options: { status?: string; limit?: number; offset?: number } = {}): Promise<{
  approvals: Array<Record<string, unknown>>;
  total: number;
  pending_count: number;
  limit: number;
  offset: number;
}> {
  const params = new URLSearchParams();
  if (options.status) params.set("status", options.status);
  params.set("limit", String(options.limit ?? 50));
  params.set("offset", String(options.offset ?? 0));
  return getJson(`/approvals?${params.toString()}`);
}

export function decideApproval(
  approvalId: string,
  decision: "approved" | "rejected",
  rationale: string,
): Promise<{ approval: Record<string, unknown> }> {
  return getJson(`/approvals/${encodeURIComponent(approvalId)}/decision`, {
    method: "POST",
    body: JSON.stringify({ decision, rationale }),
  });
}

export function continueApproval(
  approvalId: string,
): Promise<{ approval: Record<string, unknown> }> {
  return getJson(`/approvals/${encodeURIComponent(approvalId)}/continue`, { method: "POST" });
}
