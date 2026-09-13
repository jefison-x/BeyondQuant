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
  const mutating = method !== "GET";
  const unknown = () => result({ service: "beyondquant-mcp", status: "outcome_unknown", retryable: false,
    ...(typeof body?.idempotency_key === "string" && /^[A-Za-z0-9_.:-]{1,128}$/.test(body.idempotency_key) ? { idempotency_key: body.idempotency_key } : {}),
    ...(method === "POST" && ["/v1/paper/pools", "/v1/paper/index-pools"].includes(path)
      && typeof body?.idempotency_key === "string" && /^[A-Za-z0-9_.:-]{1,128}$/.test(body.idempotency_key)
      ? { reconciliation: { tool:"byq_pool_get", arguments:{ creation_kind:path.includes("index-pools") ? "index" : "custom", idempotency_key:body.idempotency_key } } } : {}),
    next_action: "Preserve the original request identity and verify its result; never create a replacement pool or infer absence from a partial list.",
  }, false);
  try {
    const response = await fetcher(`${backendUrl}${path}`, {
      method,
      headers: { "content-type": "application/json", ...contextHeaders(context) },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    const payload = await response.json().catch(() => null) as unknown;
    if (mutating && response.status >= 500) return unknown();
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
      if (mutating && response.ok) return unknown();
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (!response.ok) {
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "pool_rejected", http_status: response.status } }, true);
    }
    const value = payload as Record<string, any>;
    const exactRead = /^\/v1\/paper\/pools\/[^/?]+$/.test(path);
    const creation = method === "POST" && ["/v1/paper/pools", "/v1/paper/index-pools"].includes(path);
    const receipt = path.startsWith("/v1/paper/pools/reconcile?");
    if ((exactRead || creation || receipt) && !(receipt && value.state === "not_found" && Object.keys(value).length === 1)) {
      const valid = /^stock_pool_[0-9a-f]{32}$/.test(value.pool?.pool_id ?? "")
        && (!exactRead || value.pool.pool_id === path.split("/").at(-1))
        && (!receipt || value.state === "confirmed")
        && (!value.run || value.run.pool_id === value.pool.pool_id);
      if (!valid) return creation ? unknown() : result({ service:"beyondquant-mcp", status:"error", backend:{status:"invalid_response"} }, true);
    }
    return result({ service: "beyondquant-mcp", status: "ok", ...payload }, false);
  } catch {
    if (mutating) return unknown();
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "unreachable" } }, true);
  }
}

export const fetchByqPoolList = (backendUrl: string, context: PoolContext, fetcher: Fetcher = fetch) =>
  requestPool(backendUrl, "/v1/paper/pools", "GET", context, undefined, fetcher);
export const fetchByqIndexPoolCatalog = (backendUrl: string, asOf: string, context: PoolContext, fetcher: Fetcher = fetch) =>
  requestPool(backendUrl, `/v1/paper/index-pools/catalog?requested_as_of=${encodeURIComponent(asOf)}&limit=6&offset=0`, "GET", context, undefined, fetcher);
export const fetchByqIndexPoolCreate = (backendUrl: string, body: Record<string, unknown>, context: PoolContext, fetcher: Fetcher = fetch) =>
  requestPool(backendUrl, "/v1/paper/index-pools", "POST", context, body, fetcher);
export const fetchByqIndexPoolStatus = (backendUrl: string, poolId: string, context: PoolContext, fetcher: Fetcher = fetch) =>
  requestPool(backendUrl, `/v1/paper/pools/${encodeURIComponent(poolId)}/materializations?limit=10&offset=0`, "GET", context, undefined, fetcher);
export async function fetchByqIndexPoolReconcile(backendUrl: string, key: string, context: PoolContext, fetcher: Fetcher = fetch) {
  const response = await requestPool(backendUrl, `/v1/paper/index-pools/reconcile?idempotency_key=${encodeURIComponent(key)}`, "GET", context, undefined, fetcher);
  const payload = JSON.parse(response.content[0].text);
  if (response.isError && ![401, 403, 409, 422].includes(payload.backend?.http_status)) {
    return result({ service: "beyondquant-mcp", status: "outcome_unknown", idempotency_key: key, retryable: false,
      next_action: "Read byq_index_pool_status again with the same idempotency_key within a bounded reconciliation budget; do not repeat creation.",
    }, false);
  }
  return response;
}
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

export const fetchByqPoolCreationReconcile = (backendUrl: string, kind: string, key: string, context: PoolContext, fetcher: Fetcher = fetch) =>
  requestPool(backendUrl, `/v1/paper/pools/reconcile?kind=${encodeURIComponent(kind)}&idempotency_key=${encodeURIComponent(key)}`, "GET", context, undefined, fetcher);
