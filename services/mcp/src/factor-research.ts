import { safeDomainAdmission } from "./domain-admission.js";
import { unknownArtifactWriteResult } from "./write-outcome.js";

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
  const unknown = () => unknownArtifactWriteResult(init);
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
          backend: { status: errorStatus(response.status), http_status: response.status,
            ...(safeDomainAdmission(payload) ? { admission: safeDomainAdmission(payload) } : {}),
            ...(safeFactorValidation(payload) ? { validation: safeFactorValidation(payload) } : {}) },
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


export function safeFactorValidation(payload: unknown) {
  const detail = (payload as any)?.detail;
  const value = detail?.validation ?? detail;
  if (!value || value.schema_version !== "factor-validation-problem.v1"
      || !["request", "as_of_date", "factor", "factor.name", "factor.version", "factor.lookback",
           "securities", "sessions", "statuses", "bars", "universe_snapshots", "sources"].includes(value.field)
      || !["invalid_input", "object_required", "unknown_fields", "text_required", "date_format",
           "unsupported_value", "out_of_range"].includes(value.code)) return undefined;
  return { schema_version: "factor-validation-problem.v1", field: value.field, code: value.code,
    repair_limit: 1, next_action: "correct_once",
    ...(value.field === "factor.name" && value.code === "unsupported_value"
      ? { allowed_values: ["daily_return", "momentum"] } : {}) };
}
