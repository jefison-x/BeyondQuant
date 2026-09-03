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
  try {
    const response = await fetcher(`${backendUrl}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init.headers ?? {}) },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    const payload = await response.json().catch(() => null) as unknown;
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    if (!response.ok) return result({ service: "beyondquant-mcp", status: "error", backend: { status: errorCode(response.status), http_status: response.status } }, true);
    return result({ service: "beyondquant-mcp", status: "ok", ...payload }, false);
  } catch {
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
