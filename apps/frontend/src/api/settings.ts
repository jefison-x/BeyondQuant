import type { AgentPolicyStatus, AssetImportReport, AssetSummary, ModelSettings, SettingsStatus, UiPreferences, UserProfile } from "./types";

export class SettingsRequestError extends Error {constructor(message:string,readonly status:number){super(message);}}

const ROOT = "/api/product";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${ROOT}${path}`, {
    signal:AbortSignal.timeout(15000),
    ...init,
    credentials: "include",
    headers: {
      ...(init.body ? { "content-type": "application/json" } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: { message?: string }; detail?: string };
    throw new SettingsRequestError(body.error?.message ?? body.detail ?? "settings request failed",response.status);
  }
  return (await response.json()) as T;
}

export function getProfile(): Promise<{ profile: UserProfile }> {
  return request("/profile");
}

export function updateProfile(payload: Partial<Pick<UserProfile, "display_name" | "preferences" | "default_prompt">>): Promise<{ profile: UserProfile }> {
  return request("/profile", { method: "PUT", body: JSON.stringify(payload) });
}

export function getAppearance(): Promise<{ preferences: UiPreferences }> {
  return request("/settings/appearance");
}

export function updateAppearance(
  preferences: Pick<UiPreferences, "schema_version" | "color_mode" | "accent_theme"> & { expected_version: number },
): Promise<{ preferences: UiPreferences }> {
  return request("/settings/appearance", { method: "PUT", body: JSON.stringify(preferences) });
}

export function getModelSettings(): Promise<ModelSettings> {
  return request("/settings/models");
}

export function createModelCredential(payload: Record<string, unknown>): Promise<{ credential: Record<string, unknown> }> {
  return request("/settings/models/credentials", { method: "POST", body: JSON.stringify(payload) });
}

export function updateModelCredential(credentialId: string, payload: Record<string, unknown>): Promise<{ credential: Record<string, unknown> }> {
  return request(`/settings/models/credentials/${credentialId}`, { method: "PUT", body: JSON.stringify(payload) });
}

export function revokeModelCredential(credentialId: string, payload: Record<string, unknown>): Promise<{ credential: Record<string, unknown> }> {
  return request(`/settings/models/credentials/${credentialId}/revoke`, { method: "POST", body: JSON.stringify(payload) });
}

export function createModelProfile(payload: Record<string, unknown>): Promise<{ profile: Record<string, unknown> }> {
  return request("/settings/models/profiles", { method: "POST", body: JSON.stringify(payload) });
}

export function deleteModelProfile(profileId: string, expectedVersion: number): Promise<{ profile: Record<string, unknown> }> {
  return request(`/settings/models/profiles/${profileId}/delete`, { method: "POST", body: JSON.stringify({ expected_version: expectedVersion }) });
}

export function updateModelBinding(agentId: string, profileId: string | null, expectedVersion: number): Promise<{ binding: Record<string, unknown> }> {
  return request(`/settings/models/bindings/${agentId}`, { method: "PUT", body: JSON.stringify({ profile_id: profileId, expected_version: expectedVersion }) });
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

export function createAgentPolicyRule(payload: Record<string, unknown>): Promise<{ rule: Record<string, unknown> }> {
  return request("/settings/agent-policy/rules", { method: "POST", body: JSON.stringify(payload) });
}

export function updateAgentPolicyRule(ruleId: string, payload: Record<string, unknown>): Promise<{ rule: Record<string, unknown> }> {
  return request(`/settings/agent-policy/rules/${ruleId}`, { method: "PUT", body: JSON.stringify(payload) });
}

export function deleteAgentPolicyRule(ruleId: string, expectedVersion: number): Promise<{ deleted: boolean }> {
  return request(`/settings/agent-policy/rules/${ruleId}/delete`, { method: "POST", body: JSON.stringify({ expected_version: expectedVersion }) });
}

export function applyAgentPolicyPreset(presetId: string): Promise<Record<string, unknown>> {
  return request(`/settings/agent-policy/presets/${presetId}/apply`, { method: "POST", body: "{}" });
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

export async function reconcileModelCredential(command:{operation:string;key:string;credential_id?:string}) {
  const params=new URLSearchParams({operation:command.operation,request_id:command.key});
  if(command.credential_id)params.set('credential_id',command.credential_id);
  const value=await request<any>('/settings/models/credentials/receipts?'+params);
  if(value.state==='not_found' && Object.keys(value).length===1)return value;
  if(value.state!=='confirmed' || value.operation!==command.operation || !/^cred_[0-9a-f]{32}$/.test(value.credential_id ?? '')
    || (command.credential_id && value.credential_id!==command.credential_id) || !Number.isSafeInteger(value.committed_version) || value.committed_version<1)throw Error('原凭据回执无法确认');
  return value;
}

export function getModelProfileReceipt(keyName:string):Promise<unknown> {
  return request('/settings/models/profiles/receipts?'+new URLSearchParams({key_name:keyName}));
}
