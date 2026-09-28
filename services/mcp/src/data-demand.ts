import { isWriteRequest, unknownWriteResult } from "./write-outcome.js";

const BACKEND_TIMEOUT_MS = 8000;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;
export type DataDemandLookup = { demand_id: string } | { job_id: string } | { idempotency_key: string };
export type DataDemandRequest = Record<string, unknown>;
export type DataDemandResult = { content: Array<{ type: "text"; text: string }>; isError: boolean };

function result(payload: unknown, isError: boolean): DataDemandResult {
  return { content: [{ type: "text", text: JSON.stringify(payload) }], isError };
}

function errorStatus(status: number): string {
  if (status === 403) return "data_demand_forbidden";
  if (status === 404) return "data_demand_not_found";
  if (status === 409) return "data_demand_conflict";
  if (status === 422) return "data_demand_invalid";
  return "data_demand_unavailable";
}

function unknownDemand(init: RequestInit, path: string) {
  const response = unknownWriteResult(init);
  const body = JSON.parse(response.content[0].text);
  const cancelledId = /^\/v1\/agent\/data-demands\/(datademand_[0-9a-f]{32})\/cancel$/.exec(path)?.[1];
  if (cancelledId) body.reconciliation = {
    tool: "byq_data_demand_get", arguments: { job_id: cancelledId },
  };
  else if (typeof body.idempotency_key === "string") body.reconciliation = {
    tool: "byq_data_demand_get", arguments: { idempotency_key: body.idempotency_key },
  };
  return result(body, false);
}

async function requestDataDemand(
  backendUrl: string, path: string, init: RequestInit, fetcher: Fetcher,
): Promise<DataDemandResult> {
  try {
    const response = await fetcher(`${backendUrl}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init.headers ?? {}) },
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    if (isWriteRequest(init) && response.status >= 500) return unknownDemand(init, path);
    let payload: unknown;
    try { payload = await response.json(); } catch {
      if (isWriteRequest(init) && response.ok) return unknownDemand(init, path);
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
      if (isWriteRequest(init) && response.ok) return unknownDemand(init, path);
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (!response.ok) {
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: errorStatus(response.status), http_status: response.status } }, true);
    }
    const value = payload as Record<string, any>;
    if (!path.endsWith("/data-demand-notifications")) {
      const byKey = path.includes("/by-key/");
      const demand = value.demand;
      const valid = demand?.schema_version === "data-demand.v1"
        && typeof demand.demand_id === "string" && /^datademand_[0-9a-f]{32}$/.test(demand.demand_id);
      const taskBound = demand?.task_id !== undefined && demand?.task_id !== null;
      const job = demand?.job;
      const businessJob = value.business_job;
      const jobFields = ["job_id", "workspace_id", "type", "status", "progress", "input_ref", "result_ref", "error", "created_at", "started_at", "finished_at"];
      const validJob = (candidate: any) => candidate !== null && typeof candidate === "object" && !Array.isArray(candidate)
        && Object.keys(candidate).sort().join(",") === [...jobFields].sort().join(",")
        && candidate.job_id === demand.demand_id && typeof candidate.workspace_id === "string" && candidate.workspace_id.length > 0
        && candidate.type === "DATA_IMPORT" && ["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"].includes(candidate.status)
        && (candidate.progress === null || typeof candidate.progress === "number" && Number.isFinite(candidate.progress) && candidate.progress >= 0 && candidate.progress <= 100)
        && (candidate.input_ref === null || typeof candidate.input_ref === "string")
        && (candidate.result_ref === null || typeof candidate.result_ref === "string")
        && (candidate.error === null || typeof candidate.error === "object" && !Array.isArray(candidate.error))
        && typeof candidate.created_at === "string"
        && (candidate.started_at === null || typeof candidate.started_at === "string")
        && (candidate.finished_at === null || typeof candidate.finished_at === "string");
      const jobValid = taskBound && validJob(job) && validJob(businessJob)
        && job.workspace_id === businessJob.workspace_id && job.status === businessJob.status
        && job.progress === businessJob.progress && job.input_ref === businessJob.input_ref
        && job.result_ref === businessJob.result_ref && JSON.stringify(job.error) === JSON.stringify(businessJob.error)
        && job.created_at === businessJob.created_at && job.started_at === businessJob.started_at
        && job.finished_at === businessJob.finished_at;
      if (!(byKey && value.state === "not_found" && Object.keys(value).length === 1)
          && (!valid || byKey && value.state !== "confirmed"
              || taskBound && (typeof demand.task_id !== "string" || !/^task_[0-9a-f]{32}$/.test(demand.task_id) || !jobValid)
              || !isWriteRequest(init) && !byKey && demand.demand_id !== path.split("/").at(-1))) {
        if (isWriteRequest(init)) return unknownDemand(init, path);
        return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
      }
    }
    return result({ service: "beyondquant-mcp", status: "ok", ...payload }, false);
  } catch {
    if (isWriteRequest(init)) return unknownDemand(init, path);
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "unreachable" } }, true);
  }
}

export function fetchByqDataDemandCreate(
  backendUrl: string, request: DataDemandRequest, fetcher: Fetcher = fetch,
): Promise<DataDemandResult> {
  return requestDataDemand(backendUrl, "/v1/agent/data-demands", {
    method: "POST", body: JSON.stringify(request),
  }, fetcher);
}

export function fetchByqDataDemandGet(
  backendUrl: string, lookup: string | DataDemandLookup, fetcher: Fetcher = fetch,
): Promise<DataDemandResult> {
  const path = typeof lookup === "string" ? encodeURIComponent(lookup)
    : "demand_id" in lookup ? encodeURIComponent(lookup.demand_id)
    : "job_id" in lookup ? encodeURIComponent(lookup.job_id)
    : "by-key/" + encodeURIComponent(lookup.idempotency_key);
  return requestDataDemand(backendUrl, `/v1/agent/data-demands/${path}`, { method: "GET" }, fetcher);
}

export function fetchByqDataDemandCancel(
  backendUrl: string, jobId: string, fetcher: Fetcher = fetch,
): Promise<DataDemandResult> {
  return requestDataDemand(backendUrl, `/v1/agent/data-demands/${encodeURIComponent(jobId)}/cancel`,
    { method: "POST", body: "{}" }, fetcher);
}

export function fetchByqDataDemandNotifications(
  backendUrl: string, fetcher: Fetcher = fetch,
): Promise<DataDemandResult> {
  return requestDataDemand(backendUrl, "/v1/agent/data-demand-notifications", { method: "GET" }, fetcher);
}
