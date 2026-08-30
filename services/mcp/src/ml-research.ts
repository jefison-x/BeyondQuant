const BACKEND_TIMEOUT_MS = 8000;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;
export type MlRequest = Record<string, unknown>;
export type ByqMlResult = { content: Array<{ type: "text"; text: string }>; isError: boolean };

function result(payload: unknown, isError: boolean): ByqMlResult {
  return { content: [{ type: "text", text: JSON.stringify(payload) }], isError };
}

function errorStatus(status: number): string {
  if (status === 403) return "ml_action_forbidden";
  if (status === 404) return "ml_resource_not_found";
  if (status === 409) return "ml_action_conflict";
  if (status === 422) return "ml_request_invalid";
  return "ml_research_unavailable";
}

async function requestMl(
  backendUrl: string,
  path: string,
  init: RequestInit,
  fetcher: Fetcher,
): Promise<ByqMlResult> {
  try {
    const response = await fetcher(`${backendUrl}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init.headers ?? {}) },
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    let payload: unknown;
    try { payload = await response.json(); } catch { return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true); }
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (!response.ok) {
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: errorStatus(response.status), http_status: response.status } }, true);
    }
    return result({ service: "beyondquant-mcp", status: "ok", ...payload }, false);
  } catch {
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "unreachable" } }, true);
  }
}

export function fetchByqMlCapabilities(backendUrl: string, fetcher: Fetcher = fetch) {
  return requestMl(backendUrl, "/v1/research/ml/capabilities", { method: "GET" }, fetcher);
}

export function fetchByqMlWorkspace(backendUrl: string, fetcher: Fetcher = fetch) {
  return requestMl(backendUrl, "/v1/research/ml/workspace", { method: "GET" }, fetcher);
}

export function fetchByqMlStrategyCreate(backendUrl: string, request: MlRequest, fetcher: Fetcher = fetch) {
  return requestMl(backendUrl, "/v1/research/ml/strategies/versions", { method: "POST", body: JSON.stringify(request) }, fetcher);
}

export function fetchByqMlTrainingCreate(backendUrl: string, request: MlRequest, fetcher: Fetcher = fetch) {
  return requestMl(backendUrl, "/v1/research/ml/training-runs", { method: "POST", body: JSON.stringify(request) }, fetcher);
}

export function fetchByqMlTrainingGet(backendUrl: string, runId: string, fetcher: Fetcher = fetch) {
  return requestMl(backendUrl, `/v1/research/ml/training-runs/${encodeURIComponent(runId)}`, { method: "GET" }, fetcher);
}

export function fetchByqMlTrainingCancel(backendUrl: string, runId: string, fetcher: Fetcher = fetch) {
  return requestMl(backendUrl, `/v1/research/ml/training-runs/${encodeURIComponent(runId)}/cancel`, { method: "POST", body: "{}" }, fetcher);
}

export function fetchByqMlPredictionCreate(backendUrl: string, request: MlRequest, fetcher: Fetcher = fetch) {
  return requestMl(backendUrl, "/v1/research/ml/prediction-runs", { method: "POST", body: JSON.stringify(request) }, fetcher);
}

export function fetchByqMlPredictionGet(backendUrl: string, runId: string, fetcher: Fetcher = fetch) {
  return requestMl(backendUrl, `/v1/research/ml/prediction-runs/${encodeURIComponent(runId)}`, { method: "GET" }, fetcher);
}
