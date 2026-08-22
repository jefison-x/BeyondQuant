import type { OperationsBudget, OperationsBudgetUpdate, OperationsStatus } from "./types";

export async function getOperationsStatus(token: string): Promise<OperationsStatus> {
  const response = await fetch("/api/product/operations/status", {
    credentials: "include",
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
    throw new Error(body.error?.message ?? "operations status request failed");
  }
  return (await response.json()) as OperationsStatus;
}

export async function updateOperationsBudget(payload: OperationsBudgetUpdate): Promise<OperationsBudget> {
  const response = await fetch("/api/product/operations/budget", {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
    throw new Error(body.error?.message ?? "operations budget update failed");
  }
  const body = (await response.json()) as { budget: OperationsBudget };
  return body.budget;
}
