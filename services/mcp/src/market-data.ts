const BACKEND_TIMEOUT_MS = 8000;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

export type MarketDailyRequest = {
  ts_code?: string;
  trade_date?: string;
  start_date?: string;
  end_date?: string;
};

export type MarketValuationRequest = {
  symbols: string[];
  trade_date: string;
  fields: string[];
};

export type MarketFundamentalsRequest = {
  symbols: string[];
  as_of_date: string;
  fields: string[];
};

export type ByqMarketDailyResult = {
  content: Array<{ type: "text"; text: string }>;
  isError: boolean;
};

function result(payload: unknown, isError: boolean): ByqMarketDailyResult {
  return {
    content: [{ type: "text", text: JSON.stringify(payload) }],
    isError,
  };
}

function query(request: MarketDailyRequest): string {
  const params = new URLSearchParams();
  for (const key of ["ts_code", "trade_date", "start_date", "end_date"] as const) {
    const value = request[key];
    if (value !== undefined) {
      params.set(key, value);
    }
  }
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

export async function fetchByqMarketDaily(
  backendUrl: string,
  request: MarketDailyRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqMarketDailyResult> {
  try {
    const response = await fetcher(`${backendUrl}/v1/data/daily${query(request)}`, {
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    let payload: unknown;
    try {
      payload = await response.json();
    } catch (error) {
      return result(
        {
          service: "beyondquant-mcp",
          status: "error",
          backend: { status: "invalid_response" },
        },
        true,
      );
    }
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
      return result(
        {
          service: "beyondquant-mcp",
          status: "error",
          backend: { status: "invalid_response" },
        },
        true,
      );
    }
    if (!response.ok) {
      return result(
        {
          service: "beyondquant-mcp",
          status: "error",
          backend: { status: "data_provider_unavailable", http_status: response.status },
        },
        true,
      );
    }
    return result(
      {
        service: "beyondquant-mcp",
        status: "ok",
        ...payload,
      },
      false,
    );
  } catch (error) {
    return result(
      {
        service: "beyondquant-mcp",
        status: "error",
        backend: { status: "unreachable" },
      },
      true,
    );
  }
}

async function fetchPersistedResearch(
  backendUrl: string,
  path: string,
  request: MarketValuationRequest | MarketFundamentalsRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqMarketDailyResult> {
  try {
    const response = await fetcher(`${backendUrl}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(request),
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    let payload: unknown;
    try {
      payload = await response.json();
    } catch (error) {
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (!response.ok) {
      const status = response.status === 422 ? "research_request_invalid" : "research_data_unavailable";
      return result({ service: "beyondquant-mcp", status: "error", backend: { status, http_status: response.status } }, true);
    }
    return result({ service: "beyondquant-mcp", status: "ok", ...payload }, false);
  } catch (error) {
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "unreachable" } }, true);
  }
}

export async function fetchByqMarketValuation(
  backendUrl: string,
  request: MarketValuationRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqMarketDailyResult> {
  return fetchPersistedResearch(backendUrl, "/v1/data/research/valuation", request, fetcher);
}

export async function fetchByqMarketFundamentals(
  backendUrl: string,
  request: MarketFundamentalsRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqMarketDailyResult> {
  return fetchPersistedResearch(backendUrl, "/v1/data/research/fundamentals", request, fetcher);
}
