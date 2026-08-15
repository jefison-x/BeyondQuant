const BACKEND_TIMEOUT_MS = 8000;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

export type StrategyRequest = Record<string, unknown>;

export type ByqStrategyResult = {
  content: Array<{ type: "text"; text: string }>;
  isError: boolean;
};

function result(payload: unknown, isError: boolean): ByqStrategyResult {
  return { content: [{ type: "text", text: JSON.stringify(payload) }], isError };
}

function errorStatus(status: number): string {
  if (status === 404) return "research_not_found";
  if (status === 409) return "research_conflict";
  if (status === 422) return "strategy_request_invalid";
  return "research_unavailable";
}

async function requestStrategy(
  backendUrl: string,
  path: string,
  init: RequestInit,
  fetcher: Fetcher,
): Promise<ByqStrategyResult> {
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

export function fetchByqStrategyValidate(
  backendUrl: string,
  request: StrategyRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqStrategyResult> {
  return requestStrategy(
    backendUrl,
    "/v1/research/strategies/validate",
    { method: "POST", body: JSON.stringify(request) },
    fetcher,
  );
}

export function fetchByqStrategyVersionCreate(
  backendUrl: string,
  request: StrategyRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqStrategyResult> {
  return requestStrategy(
    backendUrl,
    "/v1/research/strategies/versions",
    { method: "POST", body: JSON.stringify(request) },
    fetcher,
  );
}

export function fetchByqStrategyApprove(
  backendUrl: string,
  request: StrategyRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqStrategyResult> {
  return requestStrategy(
    backendUrl,
    "/v1/research/strategies/approvals",
    { method: "POST", body: JSON.stringify(request) },
    fetcher,
  );
}

export function fetchByqStrategyExport(
  backendUrl: string,
  artifactId: string,
  fetcher: Fetcher = fetch,
): Promise<ByqStrategyResult> {
  return requestStrategy(
    backendUrl,
    `/v1/research/strategies/versions/${encodeURIComponent(artifactId)}/export`,
    { method: "GET" },
    fetcher,
  );
}
