import { isWriteRequest, unknownWriteResult } from "./write-outcome.js";

const TIMEOUT_MS = 8_000;
type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;
export type FeedbackResult = { content: Array<{ type: "text"; text: string }>; isError: boolean };
export type FeedbackRequest = Record<string, unknown>;

function result(payload: unknown, isError: boolean): FeedbackResult {
  return { content: [{ type: "text", text: JSON.stringify(payload) }], isError };
}

function errorCode(status: number): string {
  if (status === 403) return "feedback_forbidden";
  if (status === 404) return "feedback_not_found";
  if (status === 409) return "feedback_conflict";
  if (status === 422) return "feedback_invalid";
  if (status === 429) return "feedback_rate_limited";
  return "feedback_unavailable";
}

async function request(backendUrl: string, path: string, init: RequestInit, fetcher: Fetcher): Promise<FeedbackResult> {
  const unknown = () => {
    const base = unknownWriteResult(init);
    const value = JSON.parse(base.content[0].text);
    let payload:Record<string,unknown> = {};
    try { payload = JSON.parse(String(init.body)); } catch {}
    const item = path.match(/^\/v1\/feedback\/items\/(feedback_[0-9a-f]{32})(?:\/(submit|withdraw))?$/);
    const operation = path === '/v1/feedback/items' && init.method === 'POST' ? 'create'
      : item && init.method === 'PUT' ? 'update' : item?.[2];
    if(operation && typeof payload.idempotency_key === 'string' && /^[A-Za-z0-9_.:-]{1,128}$/.test(payload.idempotency_key)) {
      value.reconciliation = {tool:'byq_feedback_get',arguments:{operation,idempotency_key:payload.idempotency_key,...(item ? {feedback_id:item[1]} : {})}};
    }
    return result(value,false);
  };
  try {
    const response = await fetcher(`${backendUrl}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init.headers ?? {}) },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (isWriteRequest(init) && response.status >= 500) return unknown();
    const payload = await response.json().catch(() => null) as unknown;
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      if (isWriteRequest(init) && response.ok) return unknown();
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (!response.ok) return result({ service: "beyondquant-mcp", status: "error", backend: { status: errorCode(response.status), http_status: response.status } }, true);
    const value = payload as Record<string,any>;
    const item = path.match(/^\/v1\/feedback\/items(?:\/(feedback_[0-9a-f]{32}))?(?:\/(submit|withdraw))?$/);
    const receipt = path.startsWith('/v1/feedback/receipts?');
    if ((item && (item[1] || isWriteRequest(init))) || receipt) {
      const absent = receipt && value.state === 'not_found' && Object.keys(value).length === 1;
      const requested = receipt ? new URLSearchParams(path.split('?')[1]).get('feedback_id') : item?.[1];
      const valid = /^feedback_[0-9a-f]{32}$/.test(value.feedback?.feedback_id ?? '')
        && (!requested || value.feedback.feedback_id === requested) && (!receipt || value.state === 'confirmed');
      if (!absent && !valid) return isWriteRequest(init) ? unknown() : result({status:'error',backend:{status:'invalid_response'}},true);
    }
    return result({ service: "beyondquant-mcp", status: "ok", ...payload }, false);
  } catch {
    if (isWriteRequest(init)) return unknown();
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "unreachable" } }, true);
  }
}

const body = (value: FeedbackRequest): RequestInit => ({ method: "POST", body: JSON.stringify(value) });
export const fetchByqFeedbackOptions = (url: string, fetcher: Fetcher = fetch) => request(url, "/v1/feedback/options", { method: "GET" }, fetcher);
export const fetchByqFeedbackList = (url: string, args: { status?: string; category?: string; query?: string; limit?: number; offset?: number }, fetcher: Fetcher = fetch) => {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(args)) if (value !== undefined) params.set(key, String(value));
  return request(url, `/v1/feedback/items?${params}`, { method: "GET" }, fetcher);
};
export const fetchByqFeedbackGet = (url: string, id: string, fetcher: Fetcher = fetch) => request(url, `/v1/feedback/items/${encodeURIComponent(id)}`, { method: "GET" }, fetcher);
export const fetchByqFeedbackCreate = (url: string, args: FeedbackRequest, fetcher: Fetcher = fetch) => request(url, "/v1/feedback/items", body(args), fetcher);
export const fetchByqFeedbackUpdate = (url: string, id: string, args: FeedbackRequest, fetcher: Fetcher = fetch) => request(url, `/v1/feedback/items/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(args) }, fetcher);
export const fetchByqFeedbackPreview = (url: string, id: string, expectedVersion: number, fetcher: Fetcher = fetch) => request(url, `/v1/feedback/items/${encodeURIComponent(id)}/preview`, body({ expected_version: expectedVersion }), fetcher);
export const fetchByqFeedbackSubmit = (url: string, id: string, args: FeedbackRequest, fetcher: Fetcher = fetch) => request(url, `/v1/feedback/items/${encodeURIComponent(id)}/submit`, body(args), fetcher);

export const fetchByqFeedbackReceipt = (url:string,args:{operation:string;idempotency_key:string;feedback_id?:string},fetcher:Fetcher=fetch) => {
  const params = new URLSearchParams({operation:args.operation,idempotency_key:args.idempotency_key});
  if(args.feedback_id) params.set('feedback_id',args.feedback_id);
  return request(url,'/v1/feedback/receipts?'+params,{method:'GET'},fetcher);
};
