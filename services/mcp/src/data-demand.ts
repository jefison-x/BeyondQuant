const BACKEND_TIMEOUT_MS = 8000;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;
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

async function requestDataDemand(
  backendUrl: string, path: string, init: RequestInit, fetcher: Fetcher,
): Promise<DataDemandResult> {
  try {
    const response = await fetcher(`${backendUrl}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init.headers ?? {}) },
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    let payload: unknown;
    try { payload = await response.json(); } catch {
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
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

export function fetchByqDataDemandCreate(
  backendUrl: string, request: DataDemandRequest, fetcher: Fetcher = fetch,
): Promise<DataDemandResult> {
  return requestDataDemand(backendUrl, "/v1/agent/data-demands", {
    method: "POST", body: JSON.stringify(request),
  }, fetcher);
}

export function fetchByqDataDemandGet(
  backendUrl: string, demandId: string, fetcher: Fetcher = fetch,
): Promise<DataDemandResult> {
  return requestDataDemand(backendUrl, `/v1/agent/data-demands/${encodeURIComponent(demandId)}`, { method: "GET" }, fetcher);
}

export function fetchByqDataDemandNotifications(
  backendUrl: string, fetcher: Fetcher = fetch,
): Promise<DataDemandResult> {
  return requestDataDemand(backendUrl, "/v1/agent/data-demand-notifications", { method: "GET" }, fetcher);
}
