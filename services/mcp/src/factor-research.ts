import { safeDomainAdmission } from "./domain-admission.js";
import { unknownWriteResult } from "./write-outcome.js";

const BACKEND_TIMEOUT_MS = 8000;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

export type FactorComputeRequest = Record<string, unknown>;
export type FactorJobLookup = { job_id?: string; task_id?: string; idempotency_key?: string };

export type ByqFactorResult = {
  content: Array<{ type: "text"; text: string }>;
  isError: boolean;
};

function result(payload: unknown, isError: boolean): ByqFactorResult {
  return { content: [{ type: "text", text: JSON.stringify(payload) }], isError };
}

function errorStatus(status: number): string {
  if (status === 401) return "research_unauthorized";
  if (status === 403) return "research_forbidden";
  if (status === 404) return "research_not_found";
  if (status === 409) return "research_conflict";
  if (status === 422) return "factor_request_invalid";
  return "research_unavailable";
}

function unknownFactorJobWrite(init: RequestInit): ByqFactorResult {
  const response = unknownWriteResult(init);
  const value = JSON.parse(response.content[0].text);
  let request: Record<string, unknown> = {};
  try { request = JSON.parse(String(init.body ?? "{}")); } catch { /* retain unknown */ }
  if (typeof request.task_id === "string" && /^task_[0-9a-f]{32}$/.test(request.task_id)
      && typeof value.idempotency_key === "string") {
    value.reconciliation = { tool: "byq_factor_job_get", arguments: {
      task_id: request.task_id, idempotency_key: value.idempotency_key,
    } };
  }
  return result(value, false);
}

function validJob(value: Record<string, any>, taskId?: unknown, jobId?: unknown): boolean {
  const job = value.job;
  return job && /^factorjob_[0-9a-f]{32}$/.test(job.job_id ?? "")
    && (taskId === undefined || job.task_id === taskId)
    && (jobId === undefined || job.job_id === jobId)
    && ["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"].includes(job.status)
    && (job.result_ref == null || /^artifact_[0-9a-f]{32}$/.test(job.result_ref));
}

export async function fetchByqFactorCompute(
  backendUrl: string,
  request: FactorComputeRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqFactorResult> {
  const init = { method: "POST", body: JSON.stringify(request) };
  const unknown = () => unknownFactorJobWrite(init);
  try {
    const response = await fetcher(`${backendUrl}/v1/research/factors/compute`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(request),
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    if (response.status >= 500) return unknown();
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      if (response.ok) return unknown();
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
      if (response.ok) return unknown();
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (!response.ok) {
      return result(
        {
          service: "beyondquant-mcp",
          status: "error",
          backend: { status: errorStatus(response.status), http_status: response.status,
            ...(safeDomainAdmission(payload) ? { admission: safeDomainAdmission(payload) } : {}),
            ...(safeFactorValidation(payload) ? { validation: safeFactorValidation(payload) } : {}) },
        },
        true,
      );
    }
    const value = payload as Record<string, any>;
    if (!validJob(value, request.task_id)) return unknown();
    return result({ service: "beyondquant-mcp", status: "ok", ...payload }, false);
  } catch {
    return unknown();
  }
}

export async function fetchByqFactorJobGet(
  backendUrl: string, lookup: FactorJobLookup, fetcher: Fetcher = fetch,
): Promise<ByqFactorResult> {
  const byId = typeof lookup.job_id === "string" && /^factorjob_[0-9a-f]{32}$/.test(lookup.job_id);
  const byKey = typeof lookup.task_id === "string" && /^task_[0-9a-f]{32}$/.test(lookup.task_id)
    && typeof lookup.idempotency_key === "string" && /^[A-Za-z0-9_.:-]{1,128}$/.test(lookup.idempotency_key);
  if (byId === byKey || (!byId && lookup.job_id !== undefined)
      || (byId && (lookup.task_id !== undefined || lookup.idempotency_key !== undefined))) {
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_request" } }, true);
  }
  const path = byId ? `/v1/research/factor-jobs/${lookup.job_id}`
    : `/v1/research/factor-jobs?task_id=${encodeURIComponent(lookup.task_id!)}&idempotency_key=${encodeURIComponent(lookup.idempotency_key!)}`;
  try {
    const response = await fetcher(`${backendUrl}${path}`, { method: "GET", signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS) });
    const payload: unknown = await response.json();
    if (!response.ok) return result({ service: "beyondquant-mcp", status: "error", backend: {
      status: errorStatus(response.status), http_status: response.status,
    } }, true);
    if (!payload || typeof payload !== "object" || Array.isArray(payload)
        || !validJob(payload as Record<string, any>, byKey ? lookup.task_id : undefined,
          byId ? lookup.job_id : undefined)) {
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    return result({ service: "beyondquant-mcp", status: "ok", ...payload }, false);
  } catch {
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "unreachable" } }, true);
  }
}


export function safeFactorValidation(payload: unknown) {
  const detail = (payload as any)?.detail;
  const value = detail?.validation ?? detail;
  if (!value || value.schema_version !== "factor-validation-problem.v1"
      || !["request", "as_of_date", "factor", "factor.name", "factor.version", "factor.lookback",
           "securities", "sessions", "statuses", "bars", "universe_snapshots", "sources"].includes(value.field)
      || !["invalid_input", "object_required", "unknown_fields", "text_required", "date_format",
           "unsupported_value", "out_of_range"].includes(value.code)) return undefined;
  return { schema_version: "factor-validation-problem.v1", field: value.field, code: value.code,
    repair_limit: 1, next_action: "correct_once",
    ...(value.field === "factor.name" && value.code === "unsupported_value"
      ? { allowed_values: ["daily_return", "momentum"] } : {}) };
}
