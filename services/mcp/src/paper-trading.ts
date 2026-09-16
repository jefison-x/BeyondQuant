const BACKEND_TIMEOUT_MS = 8000;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;
export type PaperContext = {
  workspace_id: string;
  owner_principal: string;
  actor_principal: string;
  trace_id: string;
  session_id: string;
  dsh_run_id: string;
};
export type PaperResult = { content: Array<{ type: "text"; text: string }>; isError: boolean };

function result(payload: unknown, isError: boolean): PaperResult {
  return { content: [{ type: "text", text: JSON.stringify(payload) }], isError };
}

async function requestPaper(
  backendUrl: string, path: string, context: PaperContext, fetcher: Fetcher = fetch,
): Promise<PaperResult> {
  try {
    const response = await fetcher(`${backendUrl}${path}`, {
      method: "GET",
      headers: {
        "content-type": "application/json",
        "x-byq-workspace-id": context.workspace_id,
        "x-byq-owner-principal": context.owner_principal,
        "x-byq-actor-principal": context.actor_principal,
        "x-byq-trace-id": context.trace_id,
        "x-byq-session-id": context.session_id,
        "x-byq-dsh-run-id": context.dsh_run_id,
      },
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    const payload = await response.json().catch(() => null) as unknown;
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (!response.ok) {
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "paper_rejected", http_status: response.status } }, true);
    }
    const value = payload as Record<string,any>;
    const exact = path.match(/^\/v1\/paper\/accounts\/([^/?]+)(?:\/orders\/([^/?]+))?$/);
    if(exact) {
      const object = exact[2] ? value.order : value.account;
      if(!object || object.account_id !== decodeURIComponent(exact[1]) || (exact[2] && object.order_id !== decodeURIComponent(exact[2])))
        return result({status:'error',backend:{status:'invalid_response'}},true);
    }
    if(path.startsWith('/v1/paper/receipts?')) {
      const params = new URLSearchParams(path.split('?')[1]);
      const absent = value.state === 'not_found' && Object.keys(value).length === 1;
      const valid = value.state === 'confirmed' && value.operation === params.get('operation') && /^paper_account_[0-9a-f]{32}$/.test(value.account_id ?? '')
        && (!params.get('account_id') || value.account_id === params.get('account_id'))
        && (value.operation !== 'order' || (value.order?.account_id === value.account_id && /^paper_order_[0-9a-f]{32}$/.test(value.order?.order_id ?? '')));
      if(!absent && !valid) return result({status:'error',backend:{status:'invalid_response'}},true);
    }
    return result({ service: "beyondquant-mcp", status: "ok", ...payload }, false);
  } catch {
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "unreachable" } }, true);
  }
}

export const fetchByqPaperAccounts = (backendUrl: string, context: PaperContext, fetcher: Fetcher = fetch) =>
  requestPaper(backendUrl, "/v1/paper/accounts", context, fetcher);
export const fetchByqPaperAccount = (backendUrl: string, accountId: string, context: PaperContext, fetcher: Fetcher = fetch) =>
  requestPaper(backendUrl, `/v1/paper/accounts/${encodeURIComponent(accountId)}`, context, fetcher);
export const fetchByqPaperOrder = (backendUrl: string, accountId: string, orderId: string, context: PaperContext, fetcher: Fetcher = fetch) =>
  requestPaper(backendUrl, `/v1/paper/accounts/${encodeURIComponent(accountId)}/orders/${encodeURIComponent(orderId)}`, context, fetcher);
export const fetchByqPaperSnapshots = (backendUrl: string, accountId: string, context: PaperContext, fetcher: Fetcher = fetch) =>
  requestPaper(backendUrl, `/v1/paper/accounts/${encodeURIComponent(accountId)}/snapshots`, context, fetcher);

export function fetchByqPaperReceipt(backendUrl:string,args:{operation:string;idempotency_key:string;account_id?:string},context:PaperContext,fetcher:Fetcher=fetch) {
  const params = new URLSearchParams({operation:args.operation,idempotency_key:args.idempotency_key});
  if(args.account_id) params.set('account_id',args.account_id);
  return requestPaper(backendUrl,'/v1/paper/receipts?'+params,context,fetcher);
}
