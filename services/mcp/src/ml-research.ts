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
  timeoutMs = BACKEND_TIMEOUT_MS,
): Promise<ByqMlResult> {
  try {
    const response = await fetcher(`${backendUrl}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init.headers ?? {}) },
      signal: AbortSignal.timeout(timeoutMs),
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

export function fetchByqMlStudies(
  backendUrl: string,
  request: { query?: string; status?: "all" | "active" | "completed" | "failed"; limit?: number; offset?: number },
  fetcher: Fetcher = fetch,
) {
  const params = new URLSearchParams({
    query: request.query ?? "", status: request.status ?? "all",
    limit: String(request.limit ?? 20), offset: String(request.offset ?? 0),
  });
  return requestMl(backendUrl, `/v1/research/ml/studies?${params.toString()}`, { method: "GET" }, fetcher);
}

export function fetchByqMlStudy(backendUrl: string, artifactId: string, fetcher: Fetcher = fetch) {
  return requestMl(
    backendUrl, `/v1/research/ml/studies/${encodeURIComponent(artifactId)}`,
    { method: "GET" }, fetcher,
  );
}

export function fetchByqMlStrategyCreate(backendUrl: string, request: MlRequest, fetcher: Fetcher = fetch) {
  return requestMl(backendUrl, "/v1/research/ml/strategies/versions", { method: "POST", body: JSON.stringify(request) }, fetcher);
}

export function fetchByqMlStrategyApprove(backendUrl: string, request: MlRequest, fetcher: Fetcher = fetch) {
  return requestMl(backendUrl, "/v1/research/ml/strategies/approvals", { method: "POST", body: JSON.stringify(request) }, fetcher);
}

export function fetchByqMlTrainingCreate(backendUrl: string, request: MlRequest, fetcher: Fetcher = fetch) {
  return createTrainingWithReconciliation(backendUrl, request, fetcher);
}

async function createTrainingWithReconciliation(
  backendUrl: string, request: MlRequest, fetcher: Fetcher,
): Promise<ByqMlResult> {
  const created = await requestMl(
    backendUrl, "/v1/research/ml/training-runs",
    { method: "POST", body: JSON.stringify(request) }, fetcher,
  );
  if (!created.isError) return created;
  let failureStatus = "";
  try {
    const failure = JSON.parse(created.content[0]?.text ?? "{}") as { backend?: { status?: unknown } };
    failureStatus = typeof failure.backend?.status === "string" ? failure.backend.status : "";
  } catch {
    return created;
  }
  if (!new Set(["unreachable", "ml_research_unavailable"]).has(failureStatus)) return created;
  const key = request.idempotency_key;
  if (typeof key !== "string" || key.length === 0) return created;

  const reconciled = await requestMl(
    backendUrl,
    `/v1/research/ml/training-runs/reconcile?${new URLSearchParams({ idempotency_key: key }).toString()}`,
    { method: "GET" }, fetcher, 2500,
  );
  if (!reconciled.isError) {
    try {
      const payload = JSON.parse(reconciled.content[0]?.text ?? "{}") as Record<string, unknown>;
      return result({
        ...payload,
        reconciliation: { status: "confirmed", reason: "create_response_timeout" },
      }, false);
    } catch {
      return reconciled;
    }
  }
  return result({
    service: "beyondquant-mcp",
    status: "outcome_unknown",
    operation: "ml_training_create",
    idempotency_key: key,
    retryable: false,
    reconciliation: {
      status: "not_confirmed",
      next_action: "Call byq_ml_workspace_get once and match task_id, ml_strategy_artifact_id, and stock_pool_snapshot_id before reporting the outcome.",
    },
  }, false);
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
