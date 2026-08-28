import type { PluginCenter, PluginChangeRequest, PluginDetail } from "./types";

async function body<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) {
    const value = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
    throw new Error(value.error?.message ?? fallback);
  }
  return (await response.json()) as T;
}

export async function getPluginCenter(): Promise<PluginCenter> {
  return body(await fetch("/api/product/plugins", { credentials: "include" }), "插件中心加载失败");
}

export async function getPluginDetail(pluginId: string): Promise<PluginDetail> {
  return body(await fetch(`/api/product/plugins/${encodeURIComponent(pluginId)}`, { credentials: "include" }), "插件详情加载失败");
}

export async function requestPluginChange(payload: Record<string, unknown>): Promise<{ request: PluginChangeRequest }> {
  return body(await fetch("/api/product/plugins/changes", {
    method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  }), "插件变更请求失败");
}

export async function requestPluginQualification(payload: Record<string, unknown>): Promise<{ request: PluginChangeRequest }> {
  return body(await fetch("/api/product/plugins/qualifications", {
    method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  }), "Qualification 请求失败");
}
