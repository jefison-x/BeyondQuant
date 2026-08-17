import type { AgentPolicyStatus, AssetImportReport, AssetSummary, ModelSettings, SettingsStatus, UserProfile } from "./types";

const ROOT = "/api/product";

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
    throw new Error(body.error?.message ?? body.detail ?? "settings request failed");
  }
  return (await response.json()) as T;
}

export function getProfile(): Promise<{ profile: UserProfile }> {
  return request("/profile");
}

export function updateProfile(payload: Partial<Pick<UserProfile, "display_name" | "preferences" | "default_prompt">>): Promise<{ profile: UserProfile }> {
  return request("/profile", { method: "PUT", body: JSON.stringify(payload) });
}

export function getModelSettings(): Promise<ModelSettings> {
  return request("/settings/models");
}

export function getAssetSummary(): Promise<AssetSummary> {
  return request("/settings/assets");
}

export function exportAssets(): Promise<Record<string, unknown>> {
  return request("/settings/assets/export");
}

export function importAssets(bundle: Record<string, unknown>): Promise<AssetImportReport> {
  return request("/settings/assets/import", { method: "POST", body: JSON.stringify(bundle) });
}

export function getAgentPolicyStatus(): Promise<AgentPolicyStatus> {
  return request("/settings/agent-policy");
}

export function updateAgentPolicy(payload: Record<string, unknown>): Promise<{ personal_policy: AgentPolicyStatus["personal_policy"] }> {
  return request("/settings/agent-policy", { method: "PUT", body: JSON.stringify(payload) });
}

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
