const BACKEND_TIMEOUT_MS = 8000;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

export type BacktestRequest = Record<string, unknown>;

export type ByqBacktestResult = {
  content: Array<{ type: "text"; text: string }>;
  isError: boolean;
};

function result(payload: unknown, isError: boolean): ByqBacktestResult {
  return { content: [{ type: "text", text: JSON.stringify(payload) }], isError };
}

function errorStatus(status: number): string {
  if (status === 404) return "backtest_not_found";
  if (status === 409) return "backtest_conflict";
  if (status === 422) return "backtest_request_invalid";
  return "backtest_unavailable";
}

async function requestBacktest(
  backendUrl: string,
  path: string,
  init: RequestInit,
  fetcher: Fetcher,
): Promise<ByqBacktestResult> {
  try {
    const response = await fetcher(`${backendUrl}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init.headers ?? {}) },
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (!response.ok) {
      return result(
        { service: "beyondquant-mcp", status: "error", backend: { status: errorStatus(response.status), http_status: response.status } },
        true,
      );
    }
    return result({ service: "beyondquant-mcp", status: "ok", ...payload }, false);
  } catch {
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "unreachable" } }, true);
  }
}

export function fetchByqBacktestSubmit(
  backendUrl: string,
  request: BacktestRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  return requestBacktest(
    backendUrl,
    "/v1/research/backtests",
    { method: "POST", body: JSON.stringify(request) },
    fetcher,
  );
}

export function fetchByqBacktestGet(
  backendUrl: string,
  jobId: string,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  return requestBacktest(backendUrl, `/v1/research/backtests/${encodeURIComponent(jobId)}`, { method: "GET" }, fetcher);
}

export function fetchByqSignalSnapshotGet(
  backendUrl: string,
  artifactId: string,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  return requestBacktest(backendUrl, `/v1/research/signal-snapshots/${encodeURIComponent(artifactId)}`, { method: "GET" }, fetcher);
}

export function fetchByqBacktestRun(
  backendUrl: string,
  jobId: string,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  return requestBacktest(backendUrl, `/v1/research/backtests/${encodeURIComponent(jobId)}/run`, { method: "POST", body: "{}" }, fetcher);
}

export function fetchByqBacktestCancel(
  backendUrl: string,
  jobId: string,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  return requestBacktest(backendUrl, `/v1/research/backtests/${encodeURIComponent(jobId)}/cancel`, { method: "POST", body: "{}" }, fetcher);
}

export function fetchByqBacktestTaskPrepare(
  backendUrl: string,
  request: BacktestRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  return requestBacktest(
    backendUrl,
    "/v1/research/backtest-tasks/prepare",
    { method: "POST", body: JSON.stringify(request) },
    fetcher,
  );
}

export function fetchByqBacktestTaskCreate(
  backendUrl: string,
  request: BacktestRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  return requestBacktest(
    backendUrl,
    "/v1/research/backtest-tasks",
    { method: "POST", body: JSON.stringify(request) },
    fetcher,
  );
}

export function fetchByqBacktestTaskGet(
  backendUrl: string,
  taskId: string,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  return requestBacktest(
    backendUrl,
    `/v1/research/backtest-tasks/${encodeURIComponent(taskId)}`,
    { method: "GET" },
    fetcher,
  );
}

export function fetchByqBacktestTaskExecute(
  backendUrl: string,
  taskId: string,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  return requestBacktest(
    backendUrl,
    `/v1/research/backtest-tasks/${encodeURIComponent(taskId)}/execute`,
    { method: "POST", body: "{}" },
    fetcher,
  );
}

export function fetchByqBacktestTaskCancel(
  backendUrl: string,
  taskId: string,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  return requestBacktest(
    backendUrl,
    `/v1/research/backtest-tasks/${encodeURIComponent(taskId)}/cancel`,
    { method: "POST", body: "{}" },
    fetcher,
  );
}
