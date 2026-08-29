const ROOT = "/api/product/ml";

export interface MLArtifact { artifact_id: string; task_id: string; kind: string; status: string; created_at?: string; content: Record<string, any> }
export interface MLRun { training_run_id?: string; prediction_run_id?: string; task_id: string; status: string; ml_strategy_artifact_id: string; approval_artifact_id?: string; model_artifact_id?: string; feature_artifact_id?: string; prediction_artifact_id?: string; signal_artifact_id?: string; stock_pool_snapshot_id: string; error_code?: string; error_detail?: string }
export interface MLWorkspace { tasks: Array<Record<string, any>>; pools: Array<Record<string, any>>; artifacts: MLArtifact[]; training_runs: MLRun[]; prediction_runs: MLRun[]; backtests: Array<Record<string, any>> }

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
export const createMLStrategy = (payload: Record<string, unknown>) => post<any>("/strategies/versions", payload);
export const approveMLStrategy = (payload: Record<string, unknown>) => post<any>("/strategies/approvals", payload);
export const createMLTraining = (payload: Record<string, unknown>) => post<{ training_run: MLRun }>("/training-runs", payload);
export const getMLTraining = (id: string) => request<{ training_run: MLRun }>(`/training-runs/${encodeURIComponent(id)}`);
export const createMLPrediction = (payload: Record<string, unknown>) => post<{ prediction_run: MLRun }>("/prediction-runs", payload);
export const getMLPrediction = (id: string) => request<{ prediction_run: MLRun }>(`/prediction-runs/${encodeURIComponent(id)}`);
