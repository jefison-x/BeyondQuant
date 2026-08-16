import type { OperationsStatus } from "./types";

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
