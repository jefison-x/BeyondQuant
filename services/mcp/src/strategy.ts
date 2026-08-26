import { z } from "zod";

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
      const validationMessage = response.status === 422 ? safeValidationMessage(payload) : undefined;
      return result(
        {
          service: "beyondquant-mcp",
          status: "error",
          backend: {
            status: errorStatus(response.status),
            http_status: response.status,
            ...(validationMessage
              ? { validation: { message: validationMessage, repair_limit: 1 } }
              : {}),
          },
        },
        true,
      );
    }
    return result({ service: "beyondquant-mcp", status: "ok", ...payload }, false);
  } catch {
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

export function fetchByqStrategyDraftDelete(
  backendUrl: string,
  artifactId: string,
  fetcher: Fetcher = fetch,
): Promise<ByqStrategyResult> {
  return requestStrategy(
    backendUrl,
    `/v1/research/strategies/drafts/${encodeURIComponent(artifactId)}`,
    { method: "DELETE" },
    fetcher,
  );
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
