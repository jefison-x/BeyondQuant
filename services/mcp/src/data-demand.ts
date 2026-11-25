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

type ConversationResearchScope = {
  purpose: "research";
  scope_kind: "conversation_research" | "conversation_index_history";
  symbols: string[];
  start_date: string;
  end_date: string;
  data_requirements?: Record<string, unknown>;
};

function conversationResearchRequest(init: RequestInit): ConversationResearchScope | undefined {
  if (init.method?.toUpperCase() !== "POST" || typeof init.body !== "string") return undefined;
  try {
    const body = JSON.parse(init.body) as Record<string, unknown>;
    if (body.purpose !== "research" || !["conversation_research", "conversation_index_history"].includes(String(body.scope_kind))
        || !Array.isArray(body.symbols) || !body.symbols.every((symbol) => typeof symbol === "string")
        || typeof body.start_date !== "string" || typeof body.end_date !== "string") return undefined;
    return body as ConversationResearchScope;
  } catch { return undefined; }
}

function validResearchRequirements(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const requirements = value as Record<string, unknown>;
  if (Object.keys(requirements).some((key) => !["daily_basic", "fundamentals"].includes(key))) return false;
  return ["daily_basic", "fundamentals"].every((key) => requirements[key] === undefined
    || Array.isArray(requirements[key]) && (requirements[key] as unknown[]).length <= 12
      && (requirements[key] as unknown[]).every((item) => typeof item === "string"));
}

function canonicalResearchRequirements(value: Record<string, unknown>): string {
  return JSON.stringify(Object.keys(value).sort().map((key) => {
    const item = value[key];
    return [key, Array.isArray(item) ? (item as string[]).slice().sort() : item];
  }));
}

function canonicalDate(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value.replaceAll("-", "");
  if (/^\d{8}$/.test(value)) return value;
  return undefined;
}

function validNoJobPreparation(payload: Record<string, unknown>, request: ConversationResearchScope): boolean {
  if (Object.keys(payload).join(",") !== "preparation") return false;
  const preparation = payload.preparation;
  if (!preparation || typeof preparation !== "object" || Array.isArray(preparation)) return false;
  const result = preparation as Record<string, unknown>;
  const keys = Object.keys(result).sort();
  if (!(keys.join(",") === "request_id,scope,status"
      || keys.join(",") === "error,request_id,scope,status")) return false;
  const indexHistory = request.scope_kind === "conversation_index_history";
  const states = indexHistory ? ["ready", "not_published", "no_sessions"] : ["ready", "not_published"];
  if (result.request_id !== null || !states.includes(result.status as string)) return false;
  if (result.error !== undefined && (typeof result.error !== "string" || result.error.length > 240
      || /[\u0000-\u001f\u007f]/.test(result.error))) return false;
  const scope = result.scope;
  if (!scope || typeof scope !== "object" || Array.isArray(scope)) return false;
  const scopeValue = scope as Record<string, unknown>;
  const fields = `${indexHistory ? "asset_type," : ""}data_requirements,end_date,start_date,symbols,use_case`;
  if (Object.keys(scopeValue).sort().join(",") !== fields
      || (indexHistory && scopeValue.asset_type !== "index")
      || scopeValue.use_case !== "research"
      || canonicalDate(scopeValue.start_date) !== canonicalDate(request.start_date)
      || canonicalDate(scopeValue.end_date) !== canonicalDate(request.end_date)
      || !Array.isArray(scopeValue.symbols)
      || !scopeValue.symbols.every((symbol) => typeof symbol === "string" && /^\d{6}\.(?:SH|SZ|BJ)$/.test(symbol))
      || !validResearchRequirements(scopeValue.data_requirements)) return false;
  if (indexHistory && Object.keys(scopeValue.data_requirements).length !== 0) return false;
  if (request.data_requirements !== undefined && (!validResearchRequirements(request.data_requirements)
      || canonicalResearchRequirements(scopeValue.data_requirements as Record<string, unknown>)
        !== canonicalResearchRequirements(request.data_requirements))) return false;
  const requestedSymbols = [...request.symbols].sort();
  const returnedSymbols = (scopeValue.symbols as string[]).slice().sort();
  return returnedSymbols.length === requestedSymbols.length
    && returnedSymbols.every((symbol, index) => symbol === requestedSymbols[index]);
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
      const researchRequest = path === "/v1/agent/data-demands" ? conversationResearchRequest(init) : undefined;
      if (researchRequest && validNoJobPreparation(value, researchRequest)) {
        return result({ service: "beyondquant-mcp", status: "ok", ...payload }, false);
      }
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
