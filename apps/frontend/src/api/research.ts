const ROOT = "/api/product";

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
    throw new Error(body.error?.message ?? "research request failed");
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

export function createTask(
  title: string,
  objective: string,
): Promise<Record<string, unknown>> {
  return getJson("/research/tasks", {
    method: "POST",
    body: JSON.stringify({ title, objective }),
  });
}

export function listExperiments(): Promise<{ experiments: Array<Record<string, unknown>> }> {
  return getJson("/research/experiments");
}

export function listApprovals(): Promise<{ approvals: Array<Record<string, unknown>> }> {
  return getJson("/approvals");
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
