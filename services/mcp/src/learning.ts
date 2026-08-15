const BACKEND_TIMEOUT_MS = 8000;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

export type LearningContext = {
  owner_principal?: string;
  actor_principal?: string;
  trace_id?: string;
  session_id?: string;
  dsh_run_id?: string;
};

export type LearningResult = {
  content: Array<{ type: "text"; text: string }>;
  isError: boolean;
};

function result(payload: unknown, isError: boolean): LearningResult {
  return { content: [{ type: "text", text: JSON.stringify(payload) }], isError };
}

function errorStatus(status: number): string {
  if (status === 401) return "learning_unauthorized";
  if (status === 403) return "learning_forbidden";
  if (status === 404) return "learning_not_found";
  if (status === 409) return "learning_conflict";
  if (status === 422) return "learning_request_invalid";
  return "learning_unavailable";
}

function contextHeaders(context: LearningContext | undefined): Record<string, string> {
  if (!context) return {};
  const headers: Record<string, string> = {};
  const mapping: Array<[keyof LearningContext, string]> = [
    ["owner_principal", "x-byq-owner-principal"],
    ["actor_principal", "x-byq-actor-principal"],
    ["trace_id", "x-byq-trace-id"],
    ["session_id", "x-byq-session-id"],
    ["dsh_run_id", "x-byq-dsh-run-id"],
  ];
  for (const [field, header] of mapping) {
    const value = context[field];
    if (value) headers[header] = value;
  }
  return headers;
}

async function requestLearning(
  backendUrl: string,
  path: string,
  init: RequestInit,
  context: LearningContext | undefined,
  fetcher: Fetcher,
): Promise<LearningResult> {
  try {
    const response = await fetcher(`${backendUrl}${path}`, {
      ...init,
      headers: {
        "content-type": "application/json",
        ...contextHeaders(context),
        ...(init.headers ?? {}),
      },
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
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: errorStatus(response.status), http_status: response.status } }, true);
    }
    return result({ service: "beyondquant-mcp", status: "ok", ...payload }, false);
  } catch {
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "unreachable" } }, true);
  }
}

export function fetchByqLearningRunStart(
  backendUrl: string,
  request: Record<string, unknown>,
  context: LearningContext,
  fetcher: Fetcher = fetch,
): Promise<LearningResult> {
  return requestLearning(backendUrl, "/v1/learning/runs", { method: "POST", body: JSON.stringify(request) }, context, fetcher);
}

export function fetchByqLearningRunGet(
  backendUrl: string,
  runId: string,
  context: LearningContext,
  fetcher: Fetcher = fetch,
): Promise<LearningResult> {
  return requestLearning(backendUrl, `/v1/learning/runs/${encodeURIComponent(runId)}`, { method: "GET" }, context, fetcher);
}

export function fetchByqLearningIterationRecord(
  backendUrl: string,
  runId: string,
  request: Record<string, unknown>,
  context: LearningContext,
  fetcher: Fetcher = fetch,
): Promise<LearningResult> {
  return requestLearning(backendUrl, `/v1/learning/runs/${encodeURIComponent(runId)}/iterations`, { method: "POST", body: JSON.stringify(request) }, context, fetcher);
}

export function fetchByqLearningIterationList(
  backendUrl: string,
  runId: string,
  context: LearningContext,
  fetcher: Fetcher = fetch,
): Promise<LearningResult> {
  return requestLearning(backendUrl, `/v1/learning/runs/${encodeURIComponent(runId)}/iterations`, { method: "GET" }, context, fetcher);
}

export function fetchByqLearningRunReview(
  backendUrl: string,
  runId: string,
  request: Record<string, unknown>,
  context: LearningContext,
  fetcher: Fetcher = fetch,
): Promise<LearningResult> {
  return requestLearning(backendUrl, `/v1/learning/runs/${encodeURIComponent(runId)}/review`, { method: "POST", body: JSON.stringify(request) }, context, fetcher);
}

export function fetchByqLearningSignalCreate(
  backendUrl: string,
  request: Record<string, unknown>,
  context: LearningContext,
  fetcher: Fetcher = fetch,
): Promise<LearningResult> {
  return requestLearning(backendUrl, "/v1/learning/signals", { method: "POST", body: JSON.stringify(request) }, context, fetcher);
}

export function fetchByqLearningSignalGet(
  backendUrl: string,
  signalId: string,
  context: LearningContext,
  fetcher: Fetcher = fetch,
): Promise<LearningResult> {
  return requestLearning(backendUrl, `/v1/learning/signals/${encodeURIComponent(signalId)}`, { method: "GET" }, context, fetcher);
}

export function fetchByqExperimentCompare(
  backendUrl: string,
  request: Record<string, unknown>,
  context: LearningContext,
  fetcher: Fetcher = fetch,
): Promise<LearningResult> {
  return requestLearning(backendUrl, "/v1/learning/experiments/compare", { method: "POST", body: JSON.stringify(request) }, context, fetcher);
}

export function fetchByqLessonPropose(
  backendUrl: string,
  request: Record<string, unknown>,
  context: LearningContext,
  fetcher: Fetcher = fetch,
): Promise<LearningResult> {
  return requestLearning(backendUrl, "/v1/learning/lessons", { method: "POST", body: JSON.stringify(request) }, context, fetcher);
}

export function fetchByqLessonGet(
  backendUrl: string,
  lessonId: string,
  context: LearningContext,
  fetcher: Fetcher = fetch,
): Promise<LearningResult> {
  return requestLearning(backendUrl, `/v1/learning/lessons/${encodeURIComponent(lessonId)}`, { method: "GET" }, context, fetcher);
}

export function fetchByqLessonReview(
  backendUrl: string,
  lessonId: string,
  request: Record<string, unknown>,
  context: LearningContext,
  fetcher: Fetcher = fetch,
): Promise<LearningResult> {
  return requestLearning(backendUrl, `/v1/learning/lessons/${encodeURIComponent(lessonId)}/review`, { method: "POST", body: JSON.stringify(request) }, context, fetcher);
}
