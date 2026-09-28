import { unknownWriteResult } from "./write-outcome.js";

const BACKEND_TIMEOUT_MS = 8000;
const JOB_ID = /^optimizationjob_[0-9a-f]{32}$/;
const TASK_ID = /^task_[0-9a-f]{32}$/;
const BACKTEST_ID = /^backtest_[0-9a-f]{32}$/;
const ARTIFACT_ID = /^artifact_[0-9a-f]{32}$/;
const IDEMPOTENCY_KEY = /^[A-Za-z0-9_.:-]{1,128}$/;
const STATUSES = ["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"];

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;
export type OptimizationCandidate = { backtest_job_id: string; parameters: Record<string, unknown> };
export type OptimizationRequest = {
  task_id: string;
  experiment_id?: string;
  trace_id?: string;
  idempotency_key: string;
  objective: "total_return" | "sharpe_ratio" | "max_drawdown";
  candidates: OptimizationCandidate[];
};
export type OptimizationLookup = { job_id?: string; task_id?: string; idempotency_key?: string };
export type ByqOptimizationResult = {
  content: Array<{ type: "text"; text: string }>;
  isError: boolean;
};

function result(payload: unknown, isError: boolean): ByqOptimizationResult {
  return { content: [{ type: "text", text: JSON.stringify(payload) }], isError };
}

function errorStatus(status: number): string {
  if (status === 401) return "research_unauthorized";
  if (status === 403) return "research_forbidden";
  if (status === 404) return "research_not_found";
  if (status === 409) return "optimization_conflict";
  if (status === 422) return "optimization_request_invalid";
  return "research_unavailable";
}

function validJob(payload: Record<string, any>, taskId?: string, jobId?: string): boolean {
  const job = payload.job;
  const projection = payload.business_job;
  return job && JOB_ID.test(job.job_id ?? "") && (taskId === undefined || job.task_id === taskId)
    && (jobId === undefined || job.job_id === jobId)
    && job.type === "OPTIMIZATION" && STATUSES.includes(job.status)
    && Number.isInteger(job.candidate_count) && job.candidate_count >= 2 && job.candidate_count <= 20
    && (job.result_artifact_id == null || ARTIFACT_ID.test(job.result_artifact_id))
    && projection && projection.job_id === job.job_id && projection.type === "OPTIMIZATION"
    && projection.status === job.status;
}

function unknownSubmit(request: OptimizationRequest): ByqOptimizationResult {
  const body = { method: "POST", body: JSON.stringify(request) };
  const response = unknownWriteResult(body);
  const payload = JSON.parse(response.content[0].text);
  if (TASK_ID.test(request.task_id) && IDEMPOTENCY_KEY.test(request.idempotency_key)) {
    payload.reconciliation = {
      tool: "byq_optimization_get",
      arguments: { task_id: request.task_id, idempotency_key: request.idempotency_key },
    };
  }
  return result(payload, false);
}

function unknownOptimizationWrite(
  init: RequestInit, identity: { jobId?: string; lookup?: OptimizationLookup },
): ByqOptimizationResult {
  if (identity.lookup) return unknownSubmit(identity.lookup as OptimizationRequest);
  const response = unknownWriteResult(init);
  const payload = JSON.parse(response.content[0].text);
  if (identity.jobId && JOB_ID.test(identity.jobId)) {
    payload.reconciliation = { tool: "byq_optimization_get", arguments: { job_id: identity.jobId } };
  }
  return result(payload, false);
}

async function requestOptimization(
  backendUrl: string, path: string, init: RequestInit, fetcher: Fetcher,
  identity?: { taskId?: string; jobId?: string; lookup?: OptimizationLookup },
): Promise<ByqOptimizationResult> {
  const isWrite = (init.method ?? "GET").toUpperCase() !== "GET";
  try {
    const response = await fetcher(`${backendUrl}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init.headers ?? {}) },
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    if (isWrite && response.status >= 500 && identity) return unknownOptimizationWrite(init, identity);
    const payload: unknown = await response.json().catch(() => undefined);
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      return isWrite && identity
        ? unknownOptimizationWrite(init, identity)
        : result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (!response.ok) {
      return result({ service: "beyondquant-mcp", status: "error", backend: {
        status: errorStatus(response.status), http_status: response.status,
      } }, true);
    }
    const value = payload as Record<string, any>;
    if (identity?.taskId || identity?.jobId) {
      if (!validJob(value, identity.taskId, identity.jobId)) {
        return isWrite && identity
          ? unknownOptimizationWrite(init, identity)
          : result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
      }
    }
    return result({ service: "beyondquant-mcp", status: "ok", ...value }, false);
  } catch {
    if (isWrite && identity) return unknownOptimizationWrite(init, identity);
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "unreachable" } }, true);
  }
}

export function fetchByqOptimizationSubmit(
  backendUrl: string, request: OptimizationRequest, fetcher: Fetcher = fetch,
): Promise<ByqOptimizationResult> {
  if (!TASK_ID.test(request.task_id) || !IDEMPOTENCY_KEY.test(request.idempotency_key)
      || !["total_return", "sharpe_ratio", "max_drawdown"].includes(request.objective)
      || !Array.isArray(request.candidates) || request.candidates.length < 2 || request.candidates.length > 20
      || request.candidates.some(candidate => !BACKTEST_ID.test(candidate.backtest_job_id)
        || !candidate.parameters || typeof candidate.parameters !== "object" || Array.isArray(candidate.parameters))) {
    return Promise.resolve(result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_request" } }, true));
  }
  const body = { ...request };
  return requestOptimization(backendUrl, "/v1/research/optimization-jobs", {
    method: "POST", body: JSON.stringify(body),
  }, fetcher, { taskId: request.task_id, lookup: request });
}

export function fetchByqOptimizationGet(
  backendUrl: string, lookup: OptimizationLookup, fetcher: Fetcher = fetch,
): Promise<ByqOptimizationResult> {
  const byId = typeof lookup.job_id === "string" && JOB_ID.test(lookup.job_id);
  const byKey = typeof lookup.task_id === "string" && TASK_ID.test(lookup.task_id)
    && typeof lookup.idempotency_key === "string" && IDEMPOTENCY_KEY.test(lookup.idempotency_key);
  if (byId === byKey || (!byId && lookup.job_id !== undefined)
      || (byId && (lookup.task_id !== undefined || lookup.idempotency_key !== undefined))) {
    return Promise.resolve(result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_request" } }, true));
  }
  const path = byId ? `/v1/research/optimization-jobs/${encodeURIComponent(lookup.job_id!)}`
    : `/v1/research/optimization-jobs?${new URLSearchParams({ task_id: lookup.task_id!,
      idempotency_key: lookup.idempotency_key! })}`;
  return requestOptimization(backendUrl, path, { method: "GET" }, fetcher,
    byId ? { jobId: lookup.job_id } : { taskId: lookup.task_id });
}

export function fetchByqOptimizationCancel(
  backendUrl: string, jobId: string, fetcher: Fetcher = fetch,
): Promise<ByqOptimizationResult> {
  if (!JOB_ID.test(jobId)) {
    return Promise.resolve(result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_request" } }, true));
  }
  return requestOptimization(backendUrl, `/v1/research/optimization-jobs/${encodeURIComponent(jobId)}/cancel`,
    { method: "POST", body: "{}" }, fetcher, { jobId });
}
