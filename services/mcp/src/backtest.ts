import type { PageBudgetDecision } from "./page-budget.js";

const BACKEND_TIMEOUT_MS = 8000;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

export type BacktestRequest = Record<string, unknown>;

export type ByqBacktestResult = {
  content: Array<{ type: "text"; text: string }>;
  isError: boolean;
};

export type BacktestAnalysisBudget = {
  status: "available" | "exhausted";
  call_limit: number;
  remaining_calls: number;
  backend_accessed: boolean;
  must_answer_from_collected_evidence: boolean;
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
  return requestBacktest(
    backendUrl,
    `/v1/research/backtests/${encodeURIComponent(jobId)}/summary`,
    { method: "GET" },
    fetcher,
  );
}

export function fetchByqBacktestAnalysis(
  backendUrl: string,
  jobId: string,
  options: { section: string; limit: number; offset: number },
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  const query = new URLSearchParams({
    section: options.section,
    limit: String(options.limit),
    offset: String(options.offset),
  });
  return requestBacktest(
    backendUrl,
    `/v1/research/backtests/${encodeURIComponent(jobId)}/analysis?${query.toString()}`,
    { method: "GET" },
    fetcher,
  );
}

function analysisBudgetPayload(
  decision: PageBudgetDecision,
  backendAccessed: boolean,
): BacktestAnalysisBudget {
  return {
    status: decision.remaining > 0 ? "available" : "exhausted",
    call_limit: decision.limit,
    remaining_calls: decision.remaining,
    backend_accessed: backendAccessed,
    must_answer_from_collected_evidence: decision.remaining === 0,
  };
}

export async function fetchBudgetedByqBacktestAnalysis(
  backendUrl: string,
  jobId: string,
  options: { section: string; limit: number; offset: number },
  decision: PageBudgetDecision,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  if (!decision.allowed) {
    return result({
      service: "beyondquant-mcp",
      status: "bounded",
      analysis_page_budget: {
        ...analysisBudgetPayload(decision, false),
        code: "analysis_page_budget_exceeded",
        retryable: false,
      },
    }, false);
  }

  const fetched = await fetchByqBacktestAnalysis(
    backendUrl, jobId, options, fetcher,
  );
  if (fetched.isError) return fetched;
  const text = fetched.content[0]?.text;
  if (typeof text !== "string") return fetched;
  try {
    const payload = JSON.parse(text) as unknown;
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) return fetched;
    return result({
      ...(payload as Record<string, unknown>),
      analysis_page_budget: analysisBudgetPayload(decision, true),
    }, false);
  } catch {
    return fetched;
  }
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
