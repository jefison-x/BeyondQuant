const BACKEND_TIMEOUT_MS = 8000;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

export type ResearchTaskCreateRequest = {
  owner_principal: string;
  title: string;
  objective: string;
  trace_id: string;
  idempotency_key: string;
};

export type ResearchEntityType = "research_task" | "experiment" | "artifact";

export type ResearchTransitionRequest = {
  entity_type: ResearchEntityType;
  entity_id: string;
  target_status: string;
  idempotency_key: string;
};

export type ExperimentCreateRequest = {
  task_id: string;
  name: string;
  input_snapshot: Record<string, unknown>;
  trace_id: string;
  idempotency_key: string;
};

export type ArtifactCreateRequest = {
  task_id: string;
  experiment_id?: string;
  kind: string;
  content: Record<string, unknown>;
  lineage: Array<{ kind: string; id: string }>;
  trace_id: string;
  idempotency_key: string;
};

export type ByqResearchResult = {
  content: Array<{ type: "text"; text: string }>;
  isError: boolean;
};

function result(payload: unknown, isError: boolean): ByqResearchResult {
  return {
    content: [{ type: "text", text: JSON.stringify(payload) }],
    isError,
  };
}

function errorStatus(status: number): string {
  if (status === 404) return "research_not_found";
  if (status === 409) return "research_conflict";
  if (status === 422) return "research_request_invalid";
  return "research_unavailable";
}

async function postResearch(
  backendUrl: string,
  path: string,
  payload: Record<string, unknown>,
  fetcher: Fetcher,
): Promise<ByqResearchResult> {
  return requestResearch(backendUrl, path, { method: "POST", body: JSON.stringify(payload) }, fetcher);
}

async function requestResearch(
  backendUrl: string,
  path: string,
  init: RequestInit,
  fetcher: Fetcher,
): Promise<ByqResearchResult> {
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
      return result(
        { service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } },
        true,
      );
    }
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
      return result(
        { service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } },
        true,
      );
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
    return result({ service: "beyondquant-mcp", status: "ok", ...payload }, false);
  } catch {
    return result(
      { service: "beyondquant-mcp", status: "error", backend: { status: "unreachable" } },
      true,
    );
  }
}

export function fetchByqResearchTaskCreate(
  backendUrl: string,
  request: ResearchTaskCreateRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqResearchResult> {
  return postResearch(backendUrl, "/v1/research/tasks", request, fetcher);
}

export function fetchByqResearchGet(
  backendUrl: string,
  entityType: ResearchEntityType,
  entityId: string,
  fetcher: Fetcher = fetch,
): Promise<ByqResearchResult> {
  return requestResearch(
    backendUrl,
    `/v1/research/${entityType === "research_task" ? "tasks" : `${entityType}s`}/${encodeURIComponent(entityId)}`,
    { method: "GET" },
    fetcher,
  );
}

export function fetchByqResearchTransition(
  backendUrl: string,
  request: ResearchTransitionRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqResearchResult> {
  const collection = request.entity_type === "research_task" ? "tasks" : `${request.entity_type}s`;
  return postResearch(
    backendUrl,
    `/v1/research/${collection}/${encodeURIComponent(request.entity_id)}/transitions`,
    { target_status: request.target_status, idempotency_key: request.idempotency_key },
    fetcher,
  );
}

export function fetchByqExperimentCreate(
  backendUrl: string,
  request: ExperimentCreateRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqResearchResult> {
  return postResearch(backendUrl, "/v1/research/experiments", request, fetcher);
}

export function fetchByqArtifactCreate(
  backendUrl: string,
  request: ArtifactCreateRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqResearchResult> {
  return postResearch(backendUrl, "/v1/research/artifacts", request, fetcher);
}
