const BACKEND_TIMEOUT_MS = 5000;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

export type ByqHealthResult = {
  content: Array<{ type: "text"; text: string }>;
  isError: boolean;
};

function result(payload: unknown, isError: boolean): ByqHealthResult {
  return {
    content: [{ type: "text", text: JSON.stringify(payload) }],
    isError,
  };
}

export async function fetchByqHealth(
  backendUrl: string,
  fetcher: Fetcher = fetch,
): Promise<ByqHealthResult> {
  try {
    const response = await fetcher(`${backendUrl}/healthz`, {
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });

    let backend: unknown;
    try {
      backend = await response.json();
    } catch (error) {
      return result(
        {
          service: "beyondquant-mcp",
          status: "error",
          backend: { status: "invalid_response", error: String(error) },
        },
        true,
      );
    }

    if (backend === null || typeof backend !== "object" || Array.isArray(backend)) {
      return result(
        {
          service: "beyondquant-mcp",
          status: "error",
          backend: { status: "invalid_response" },
        },
        true,
      );
    }

    return result(
      {
        service: "beyondquant-mcp",
        status: response.ok ? "ok" : "error",
        backend,
      },
      !response.ok,
    );
  } catch (error) {
    return result(
      {
        service: "beyondquant-mcp",
        status: "error",
        backend: { status: "unreachable", error: String(error) },
      },
      true,
    );
  }
}
