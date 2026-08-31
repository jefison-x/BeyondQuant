import type { OperationsBudget, OperationsBudgetUpdate, OperationsStatus } from "./types";

const STATUS_CACHE_TTL_MS = 30_000;
const statusCache = new Map<string, { expiresAt: number; value?: OperationsStatus; pending?: Promise<OperationsStatus> }>();

export function clearOperationsStatusCache(): void {
  statusCache.clear();
}

export async function getOperationsStatus(
  token: string,
  options: { force?: boolean } = {},
): Promise<OperationsStatus> {
  const key = token || "cookie-session";
  const cached = statusCache.get(key);
  if (!options.force && cached?.value && cached.expiresAt > Date.now()) return cached.value;
  if (!options.force && cached?.pending) return cached.pending;

  const pending = fetch("/api/product/operations/status", { credentials: "include" }).then(async (response) => {
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
      throw new Error(body.error?.message ?? "operations status request failed");
    }
    const value = (await response.json()) as OperationsStatus;
    statusCache.set(key, { value, expiresAt: Date.now() + STATUS_CACHE_TTL_MS });
    return value;
  }).catch((error) => {
    statusCache.delete(key);
    throw error;
  });
  statusCache.set(key, { expiresAt: 0, pending });
  return pending;
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
  clearOperationsStatusCache();
  return body.budget;
}
