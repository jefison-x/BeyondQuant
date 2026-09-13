import { unknownWriteResult } from "./write-outcome.js";

const BACKEND_TIMEOUT_MS = 8000;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

export type FactorComputeRequest = Record<string, unknown>;

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

export async function fetchByqFactorCompute(
  backendUrl: string,
  request: FactorComputeRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqFactorResult> {
  const init = { method: "POST", body: JSON.stringify(request) };
  const unknown = () => {
    const response = unknownWriteResult(init);
    const body = JSON.parse(response.content[0].text);
    if (typeof request.task_id === 'string' && /^task_[0-9a-f]{32}$/.test(request.task_id)
        && typeof body.idempotency_key === 'string') {
      body.reconciliation = { tool: 'byq_research_get', arguments: {
        entity_type: 'artifact', task_id: request.task_id, idempotency_key: body.idempotency_key,
      } };
    }
    return result(body, false);
  };
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
          backend: { status: errorStatus(response.status), http_status: response.status },
        },
        true,
      );
    }
    const value = payload as Record<string, any>;
    if (!value.artifact || value.artifact.kind !== 'factor_result'
        || value.artifact.task_id !== request.task_id
        || typeof value.artifact.artifact_id !== 'string'
        || !/^artifact_[0-9a-f]{32}$/.test(value.artifact.artifact_id)
        || typeof value.input_manifest?.id !== 'string'
        || value.factor?.input_manifest_id !== value.input_manifest.id
        || value.artifact.content?.input_manifest_id !== value.input_manifest.id) return unknown();
    return result({ service: "beyondquant-mcp", status: "ok", ...payload }, false);
  } catch {
    return unknown();
  }
}
