import { createRequestId } from "@/utils/requestId";

const ROOT = "/api/product/ml";

export interface MLArtifact { artifact_id: string; task_id: string; kind: string; status: string; created_at?: string; content: Record<string, any> }
export interface MLRun { training_run_id?: string; prediction_run_id?: string; task_id: string; status: string; ml_strategy_artifact_id: string; approval_artifact_id?: string; model_artifact_id?: string; feature_artifact_id?: string; prediction_artifact_id?: string; signal_artifact_id?: string; stock_pool_snapshot_id: string; error_code?: string; error_detail?: string }
export interface MLWorkspace { tasks: Array<Record<string, any>>; pools: Array<Record<string, any>>; artifacts: MLArtifact[]; training_runs: MLRun[]; prediction_runs: MLRun[]; backtests: Array<Record<string, any>> }
export interface MLPredictionRows { schema_version: string; prediction_run_id: string; prediction_artifact_id: string; rows: Array<Record<string, any>>; total: number; limit: number; offset: number; has_more: boolean }
export interface MLCapabilityComponent { id: string; kind: string; display_name: string; status: string; parameters: Record<string, any>; limits: Record<string, any>; content_sha256: string }
export interface MLCapabilities { schema_version: string; registry: { schema_version: string; components: MLCapabilityComponent[]; content_sha256: string }; capabilities: Array<Record<string, any>>; limitations: string[] }
export interface MLOptions { schema_version: string; tasks: Array<Record<string, any>>; pools: Array<Record<string, any>> }
export interface MLStudySummary { artifact_id: string; task_id: string; task_title: string; status: string; lifecycle_status?: "active" | "archived"; created_at?: string; schema_version: string; name: string; learner_profile?: string; regime_enabled: boolean; horizon_sessions?: string; training_status?: string; prediction_status?: string; backtest_status?: string; stage: string }
export interface MLStudyPage { schema_version: string; studies: MLStudySummary[]; total: number; limit: number; offset: number; has_more: boolean }
export interface MLStudyManagement { lifecycle_status: "active" | "archived"; can_delete: boolean; can_archive: boolean; can_restore: boolean; history_count: number; active_run_count: number; reason: string }
export interface MLStudyDetail { schema_version: string; study: MLArtifact; management: MLStudyManagement; approval_artifact_id?: string; training_runs: { runs: MLRun[]; total: number }; prediction_runs: { runs: MLRun[]; total: number }; backtests: { backtests: Array<Record<string, any>>; total: number }; artifacts: MLArtifact[] }

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${ROOT}${path}`, { ...init, credentials: "include", headers: { ...(init.body ? { "content-type": "application/json" } : {}), ...(init.headers ?? {}) } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body?.error?.message ?? "量化模型请求失败");
  }
  return response.json() as Promise<T>;
}

const post = <T>(path: string, payload?: Record<string, unknown>) => request<T>(path, { method: "POST", ...(payload ? { body: JSON.stringify(payload) } : {}) });
export const getMLWorkspace = () => request<MLWorkspace>("/workspace");
export const getMLCapabilities = () => request<MLCapabilities>("/capabilities");
export const getMLOptions = () => request<MLOptions>("/options");
export const getMLStudies = (query = "", status = "all", limit = 20, offset = 0) => {
  const params = new URLSearchParams({ query, status, limit: String(limit), offset: String(offset) });
  return request<MLStudyPage>(`/studies?${params.toString()}`);
};
export const getMLStudy = (id: string) => request<MLStudyDetail>(`/studies/${encodeURIComponent(id)}`);
export const deleteMLStudy = (id: string) => request<{ schema_version: string; study: MLArtifact; invalidated_approval_ids: string[] }>(
  `/studies/${encodeURIComponent(id)}`,
  { method: "DELETE" },
);
export const setMLStudyLifecycle = (id: string, status: "active" | "archived") => request<{
  schema_version: string; study: MLArtifact; management: MLStudyManagement;
}>(`/studies/${encodeURIComponent(id)}/lifecycle`, {
  method: "POST",
  body: JSON.stringify({ status }),
  headers: { "x-idempotency-key": createRequestId() },
});
export const createMLStrategy = (payload: Record<string, unknown>) => post<any>("/strategies/versions", payload);
export const approveMLStrategy = (payload: Record<string, unknown>) => post<any>("/strategies/approvals", payload);
export const createMLTraining = (payload: Record<string, unknown>, idempotencyKey?: string) => request<{ training_run: MLRun }>(
  "/training-runs",
  {
    method: "POST",
    body: JSON.stringify(payload),
    ...(idempotencyKey ? { headers: { "x-idempotency-key": idempotencyKey } } : {}),
  },
);
export const getMLTraining = (id: string) => request<{ training_run: MLRun }>(`/training-runs/${encodeURIComponent(id)}`);
export const createMLPrediction = (payload: Record<string, unknown>) => post<{ prediction_run: MLRun }>("/prediction-runs", payload);
export const getMLPrediction = (id: string) => request<{ prediction_run: MLRun }>(`/prediction-runs/${encodeURIComponent(id)}`);
export const getMLPredictionRows = (id: string, query = "", limit = 50, offset = 0) => {
  const params = new URLSearchParams({ query, limit: String(limit), offset: String(offset) });
  return request<MLPredictionRows>(`/prediction-runs/${encodeURIComponent(id)}/rows?${params.toString()}`);
};
