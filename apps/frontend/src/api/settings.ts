import type { SettingsStatus } from "./types";

export async function getSettingsStatus(token: string): Promise<SettingsStatus> {
  const response = await fetch("/api/product/settings/status", {
    credentials: "include",
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
    throw new Error(body.error?.message ?? "settings request failed");
  }
  return (await response.json()) as SettingsStatus;
}
