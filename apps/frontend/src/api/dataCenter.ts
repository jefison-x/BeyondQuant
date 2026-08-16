import type { DataCenterStatus } from "./types";

export async function getDataCenterStatus(): Promise<DataCenterStatus> {
  const response = await fetch("/api/product/data-center/status", { credentials: "include" });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
    throw new Error(body.error?.message ?? "data center request failed");
  }
  return (await response.json()) as DataCenterStatus;
}
