const BACKEND_TIMEOUT_MS = 8000;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;
export type PoolContext = {
  workspace_id: string;
  owner_principal: string;
  actor_principal: string;
  trace_id: string;
  session_id: string;
  dsh_run_id: string;
};
export type PoolResult = { content: Array<{ type: "text"; text: string }>; isError: boolean };

function result(payload: unknown, isError: boolean): PoolResult {
  return { content: [{ type: "text", text: JSON.stringify(payload) }], isError };
}

function contextHeaders(context: PoolContext): Record<string, string> {
  return {
    "x-byq-workspace-id": context.workspace_id,
    "x-byq-owner-principal": context.owner_principal,
    "x-byq-actor-principal": context.actor_principal,
    "x-byq-trace-id": context.trace_id,
    "x-byq-session-id": context.session_id,
    "x-byq-dsh-run-id": context.dsh_run_id,
  };
}

async function requestPool(
  backendUrl: string,
  path: string,
  method: string,
  context: PoolContext,
  body?: Record<string, unknown>,
  fetcher: Fetcher = fetch,
): Promise<PoolResult> {
  try {
    const response = await fetcher(`${backendUrl}${path}`, {
      method,
      headers: { "content-type": "application/json", ...contextHeaders(context) },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    const payload = await response.json().catch(() => null) as unknown;
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (!response.ok) {
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "pool_rejected", http_status: response.status } }, true);
    }
    return result({ service: "beyondquant-mcp", status: "ok", ...payload }, false);
  } catch {
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "unreachable" } }, true);
  }
}

export const fetchByqPoolList = (backendUrl: string, context: PoolContext, fetcher: Fetcher = fetch) =>
  requestPool(backendUrl, "/v1/paper/pools", "GET", context, undefined, fetcher);
export const fetchByqPoolGet = (backendUrl: string, poolId: string, context: PoolContext, fetcher: Fetcher = fetch) =>
  requestPool(backendUrl, `/v1/paper/pools/${encodeURIComponent(poolId)}`, "GET", context, undefined, fetcher);
export const fetchByqPoolCreate = (backendUrl: string, body: Record<string, unknown>, context: PoolContext, fetcher: Fetcher = fetch) =>
  requestPool(backendUrl, "/v1/paper/pools", "POST", context, body, fetcher);
export const fetchByqPoolSnapshotReplace = (backendUrl: string, poolId: string, body: Record<string, unknown>, context: PoolContext, fetcher: Fetcher = fetch) =>
  requestPool(backendUrl, `/v1/paper/pools/${encodeURIComponent(poolId)}/snapshot`, "PUT", context, body, fetcher);
export const fetchByqPoolHistory = (backendUrl: string, poolId: string, context: PoolContext, fetcher: Fetcher = fetch) =>
  requestPool(backendUrl, `/v1/paper/pools/${encodeURIComponent(poolId)}/snapshots`, "GET", context, undefined, fetcher);
export const fetchByqPoolLifecycle = (backendUrl: string, poolId: string, body: Record<string, unknown>, context: PoolContext, fetcher: Fetcher = fetch) =>
  requestPool(backendUrl, `/v1/paper/pools/${encodeURIComponent(poolId)}/lifecycle`, "PATCH", context, body, fetcher);
