import { z } from "zod";

import { isWriteRequest, unknownArtifactWriteResult } from "./write-outcome.js";
import { safeDomainAdmission } from "./domain-admission.js";

const BACKEND_TIMEOUT_MS = 8000;
const MAX_VALIDATION_DETAIL_CHARACTERS = 1200;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

export type StrategyRequest = Record<string, unknown>;

export const strategyValidationInputSchema = z.object({
  task_id: z.string(),
  experiment_id: z.string().optional(),
  trace_id: z.string(),
  idempotency_key: z.string(),
  strategy: z.object({
    strategy_id: z.string().regex(/^[A-Za-z][A-Za-z0-9_-]{2,63}$/),
    name: z.string(),
    category: z.enum(["trend_following", "mean_reversion", "momentum", "volatility_based", "arbitrage", "custom"]),
    description: z.string().optional(),
    parameters: z.record(z.string(), z.unknown()).optional(),
    parameter_schema: z.record(z.string(), z.unknown()).optional(),
    data_requirements: z.object({
      benchmark: z.string().optional(),
      index_universe: z.string().optional(),
      daily_basic: z.array(z.enum([
        "turnover_rate", "turnover_rate_f", "volume_ratio", "pe", "pe_ttm", "pb",
        "ps", "ps_ttm", "dv_ratio", "dv_ttm", "total_share", "float_share",
        "free_share", "total_mv", "circ_mv",
      ])).max(12).optional(),
      fundamentals: z.array(z.enum([
        "eps", "roe", "roa", "grossprofit_margin", "debt_to_assets", "or_yoy", "netprofit_yoy",
      ])).max(12).optional(),
    }).strict().optional(),
    source_type: z.literal("python_script").optional(),
    script: z.string(),
  }).strict(),
}).strict();

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

function safeValidationMessage(payload: unknown): string | undefined {
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) return undefined;
  const detail = (payload as Record<string, unknown>).detail;
  if (typeof detail !== "string") return undefined;
  const message = detail.trim();
  if (!message || message.length > MAX_VALIDATION_DETAIL_CHARACTERS) return undefined;
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/u.test(message)) return undefined;
  if (/(?:bearer\s+[a-z0-9._~-]+|(?:password|token|secret|api[_-]?key|authorization)\s*[:=]\s*\S+)/iu.test(message)) {
    return undefined;
  }
  if (/(?:^|\s)\/(?:home|root|var|opt|etc|run|srv|tmp)\//u.test(message)) return undefined;
  return message;
}

function safeStructuredValidation(payload: Record<string, unknown>) {
  const detail = payload.detail;
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return undefined;
  const envelope = detail as Record<string, unknown>;
  if (envelope.schema_version !== "domain-call-admission.v1" || envelope.state !== "correctable_failure") return undefined;
  const candidate = envelope.validation;
  if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return undefined;
  const value = candidate as Record<string, unknown>;
  const fields = new Set(["strategy", ...["strategy_id", "name", "category", "description", "parameters",
    "parameter_schema", "data_requirements", "source_type", "script"].map(field => `strategy.${field}`),
    ...["benchmark", "index_universe", "daily_basic", "fundamentals"].map(field => `strategy.data_requirements.${field}`)]);
  const codes = new Set(["invalid_strategy", "text_required", "object_required", "unknown_fields", "too_large",
    "invalid_json", "unsupported_value", "invalid_format", "credential_fields_forbidden", "static_validation_failed"]);
  if (value.schema_version !== "strategy-validation-problem.v1" || typeof value.field !== "string"
    || !fields.has(value.field) || typeof value.code !== "string" || !codes.has(value.code)) return undefined;
  return { schema_version: value.schema_version, field: value.field, code: value.code, repair_limit: 1,
    next_action: envelope.reason === "correction_failed" ? "stop_correction_failed" : "read_strategy_contract_then_correct_once" };
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
    if (isWriteRequest(init) && response.status >= 500) return unknownArtifactWriteResult(init);
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      if (isWriteRequest(init) && response.ok) return unknownArtifactWriteResult(init);
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
      if (isWriteRequest(init) && response.ok) return unknownArtifactWriteResult(init);
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (!response.ok) {
      const admission = safeDomainAdmission(payload);
      const validationMessage = response.status === 422 ? safeValidationMessage(payload) : undefined;
      const validation = response.status === 422 ? safeStructuredValidation(payload as Record<string, unknown>) : undefined;
      return result(
        {
          service: "beyondquant-mcp",
          status: "error",
          backend: {
            status: errorStatus(response.status),
            http_status: response.status,
            ...(admission ? { admission } : {}),
            ...(validation ? { validation } : validationMessage
              ? { validation: { message: validationMessage, repair_limit: 1 } }
              : {}),
          },
        },
        true,
      );
    }
    return result({ service: "beyondquant-mcp", status: "ok", ...payload }, false);
  } catch {
    if (isWriteRequest(init)) return unknownArtifactWriteResult(init);
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "unreachable" } }, true);
  }
}

export function fetchByqStrategyDraftSave(
  backendUrl: string,
  request: StrategyRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqStrategyResult> {
  return requestStrategy(
    backendUrl,
    "/v1/research/strategies/drafts",
    { method: "POST", body: JSON.stringify(request) },
    fetcher,
  );
}

export async function fetchByqStrategyDraftDelete(
  backendUrl: string,
  artifactId: string,
  fetcher: Fetcher = fetch,
): Promise<ByqStrategyResult> {
  const response = await requestStrategy(
    backendUrl,
    `/v1/research/strategies/drafts/${encodeURIComponent(artifactId)}`,
    { method: "DELETE" },
    fetcher,
  );
  const payload = JSON.parse(response.content[0].text);
  if (payload.status === "outcome_unknown" && /^artifact_[0-9a-f]{32}$/.test(artifactId)) {
    payload.reconciliation = { tool: "byq_research_get", arguments: {
      entity_type: "artifact", entity_id: artifactId,
    } };
    payload.next_action = "Read this exact original draft and inspect its status. Do not infer deletion from a missing list entry or retry with another artifact identity.";
    return result(payload, false);
  }
  return response;
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
