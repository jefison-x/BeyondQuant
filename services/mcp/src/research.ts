import { safeRequestValidation } from "./request-validation.js";
import { bindActiveWebEvidenceProducer } from "./web-evidence-provenance.js";

import { isWriteRequest, unknownWriteResult } from "./write-outcome.js";

const BACKEND_TIMEOUT_MS = 8000;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;
type SuccessProjector = (payload: Record<string, unknown>) => Record<string, unknown>;

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
  progress?: {
    schema_version: "research-progress.v1";
    stage: string;
    next_action: string | null;
    blocked_reason: string | null;
    linked_objects: Array<{ kind: "artifact" | "experiment"; id: string }>;
    completion_evidence: string[];
  };
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

export type WebEvidenceCreateRequest = {
  task: { title: string; objective: string };
  content: Record<string, unknown>;
  lineage: Array<{ kind: string; id: string }>;
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
  if (status === 401) return "research_unauthorized";
  if (status === 403) return "research_forbidden";
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
  safeWebValidation = false,
  successProjector?: SuccessProjector,
): Promise<ByqResearchResult> {
  try {
    const response = await fetcher(`${backendUrl}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init.headers ?? {}) },
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    if (isWriteRequest(init) && response.status >= 500) return unknownWriteResult(init);
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      if (isWriteRequest(init) && response.ok) return unknownWriteResult(init);
      return result(
        { service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } },
        true,
      );
    }
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
      if (isWriteRequest(init) && response.ok) return unknownWriteResult(init);
      return result(
        { service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } },
        true,
      );
    }
    if (!response.ok) {
      const validationIssue = safeWebValidation && response.status === 422
        ? safeWebEvidenceValidationIssue(payload)
        : undefined;
      return result(
        {
          service: "beyondquant-mcp",
          status: "error",
          backend: {
            status: errorStatus(response.status),
            http_status: response.status,
            ...(response.status === 422 && safeRequestValidation(payload)
              ? { validation: safeRequestValidation(payload) } : {}),
            ...(validationIssue ? { validation_issue: validationIssue } : {}),
          },
          ...(safeWebValidation ? {
            public_status: {
              state: "not_saved",
              message: "搜索结果已展示，但研究记录暂未保存；这不影响本次阅读，且这些网页内容未用于量化计算。",
            },
          } : {}),
        },
        true,
      );
    }
    const safePayload = successProjector
      ? successProjector(payload as Record<string, unknown>)
      : payload;
    return result({ service: "beyondquant-mcp", status: "ok", ...safePayload }, false);
  } catch {
    if (isWriteRequest(init)) return unknownWriteResult(init);
    return result(
      { service: "beyondquant-mcp", status: "error", backend: { status: "unreachable" } },
      true,
    );
  }
}

function safeWebEvidenceValidationIssue(payload: unknown): string {
  const detail = payload !== null && typeof payload === "object" && !Array.isArray(payload)
    ? (payload as Record<string, unknown>).detail
    : undefined;
  if (typeof detail !== "string") return "INVALID_WEB_EVIDENCE";
  const rules: Array<[string, string]> = [
    ["missing or unknown fields", "SCHEMA_FIELDS"],
    ["schema_version", "SCHEMA_VERSION"],
    ["producer is not recognized", "PRODUCER_PROVENANCE"],
    ["qualified search plugin version", "PLUGIN_VERSION"],
    ["search.queries", "QUERY_COUNT"],
    ["duplicate web search query", "DUPLICATE_QUERY"],
    ["query language", "QUERY_LANGUAGE"],
    ["stopped_reason", "STOPPED_REASON"],
    ["duplicate source_id", "DUPLICATE_SOURCE_ID"],
    ["duplicate source URL", "DUPLICATE_SOURCE_URL"],
    ["source URL", "SOURCE_URL"],
    ["source_id", "SOURCE_ID"],
    ["source_tier", "SOURCE_TIER"],
    ["temporal_status", "TEMPORAL_STATUS"],
    ["retrieved_at cannot precede", "SOURCE_TIME_ORDER"],
    ["query_indexes", "SOURCE_QUERY_INDEX"],
    ["supported causal claim", "CAUSAL_SOURCE"],
    ["supported claim", "SUPPORTED_SOURCE"],
    ["conflicted claim", "CONFLICT_SOURCE_COUNT"],
    ["claim source_ids", "CLAIM_SOURCE_ID"],
    ["claim source_indexes", "CLAIM_SOURCE_INDEX"],
    ["claim type or state", "CLAIM_CLASSIFICATION"],
    ["unverified market context", "MARKET_CONTEXT"],
    ["usage policy", "USAGE_POLICY"],
    ["ISO-8601 timestamp", "TIMESTAMP"],
    ["must include a timezone", "TIMESTAMP_TIMEZONE"],
    ["must use YYYYMMDD", "MARKET_DATE"],
    ["not a valid date", "MARKET_DATE"],
  ];
  return rules.find(([fragment]) => detail.includes(fragment))?.[1] ?? "INVALID_WEB_EVIDENCE";
}

export function fetchByqResearchTaskCreate(
  backendUrl: string,
  request: ResearchTaskCreateRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqResearchResult> {
  return watchedResearchCreate(backendUrl, 'research_task', "/v1/research/tasks", request, fetcher);
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
  const statuses = request.entity_type === 'artifact'
    ? ['draft', 'validated', 'superseded'] : ['planned', 'running', 'completed', 'failed', 'cancelled'];
  if (!statuses.includes(request.target_status)) {
    return Promise.resolve(result({ service: 'beyondquant-mcp', status: 'error', backend: {
      status: 'research_request_invalid', validation: { field: 'target_status', allowed_values: statuses,
        repair_limit: 1, message: 'Use a listed target_status. blocked is a task progress.stage, not a status; active and in_progress are invalid. Read the entity before choosing a legal transition.' },
    } }, true));
  }
  const collection = request.entity_type === "research_task" ? "tasks" : `${request.entity_type}s`;
  return postResearch(
    backendUrl,
    `/v1/research/${collection}/${encodeURIComponent(request.entity_id)}/transitions`,
    { target_status: request.target_status, idempotency_key: request.idempotency_key,
      ...(request.progress ? { progress: request.progress } : {}) },
    fetcher,
  );
}

export function fetchByqExperimentCreate(
  backendUrl: string,
  request: ExperimentCreateRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqResearchResult> {
  return watchedResearchCreate(backendUrl, 'experiment', "/v1/research/experiments", request, fetcher);
}

export function fetchByqArtifactCreate(
  backendUrl: string,
  request: ArtifactCreateRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqResearchResult> {
  return watchedResearchCreate(backendUrl, 'artifact', "/v1/research/artifacts", request, fetcher);
}

export function fetchByqWebEvidenceCreate(
  backendUrl: string,
  request: WebEvidenceCreateRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqResearchResult> {
  let trustedRequest: WebEvidenceCreateRequest;
  try {
    trustedRequest = { ...request, content: bindActiveWebEvidenceProducer(request.content) };
  } catch {
    return Promise.resolve(result({
      service: "beyondquant-mcp",
      status: "error",
      backend: { status: "research_request_invalid", validation_issue: "PRODUCER_PROVENANCE" },
    }, true));
  }
  return requestResearch(
    backendUrl,
    "/v1/research/web-evidence-records",
    { method: "POST", body: JSON.stringify(trustedRequest) },
    fetcher,
    true,
    (payload) => {
      const artifact = payload.artifact;
      const artifactId = artifact !== null && typeof artifact === "object" && !Array.isArray(artifact)
        ? (artifact as Record<string, unknown>).artifact_id
        : undefined;
      return {
        record_status: payload.record_status,
        source_count: payload.source_count,
        public_status: {
          state: "saved",
          message: "研究记录已保存。",
          source_count: payload.source_count,
        },
        ...(typeof artifactId === "string" ? {
          audit_resource: { resource_type: "artifact", resource_id: artifactId },
        } : {}),
      };
    },
  );
}


export type ResearchLookup = {
  entity_type: ResearchEntityType;
  watch_id?: string;
  entity_id?: string;
  idempotency_key?: string;
  task_id?: string;
};

export async function fetchByqResearchLookup(
  backendUrl: string, request: ResearchLookup, fetcher: Fetcher = fetch,
): Promise<ByqResearchResult> {
  if (request.watch_id !== undefined) {
    if (!/^researchwatch_[0-9a-f]{32}$/.test(request.watch_id) || request.entity_id !== undefined
        || request.idempotency_key !== undefined || request.task_id !== undefined) {
      return result({service:'beyondquant-mcp',status:'error',backend:{status:'research_request_invalid'}},true);
    }
    const response = await requestResearch(backendUrl, `/v1/research/submission-watches/${request.watch_id}`, {method:'GET'}, fetcher);
    if (response.isError) return response;
    const value = JSON.parse(response.content[0]?.text ?? '{}');
    if (!validWatch(value, request.entity_type) || value.watch_id !== request.watch_id) {
      return result({service:'beyondquant-mcp',status:'error',backend:{status:'invalid_response'}},true);
    }
    return response;
  }
  const hasId = request.entity_id !== undefined;
  const hasKey = request.idempotency_key !== undefined;
  if (hasId === hasKey || (hasId && (request.task_id !== undefined || !request.entity_id?.trim()))
      || (hasKey && (!request.idempotency_key?.trim() || request.idempotency_key.length > 128
        || (request.entity_type === "research_task" ? request.task_id !== undefined : !request.task_id?.trim())))) {
    return result({ service: "beyondquant-mcp", status: "error",
      backend: { status: "research_request_invalid", validation: { repair_limit: 1,
        message: 'For entity_id lookup omit task_id and idempotency_key. For idempotency_key lookup omit entity_id; task_id is required only for artifact or experiment. Preserve the original request identity.' } } }, true);
  }
  if (hasId) return fetchByqResearchGet(backendUrl, request.entity_type, request.entity_id!, fetcher);
  const query = new URLSearchParams({ entity_type: request.entity_type, idempotency_key: request.idempotency_key! });
  if (request.task_id) query.set("task_id", request.task_id);
  const response = await requestResearch(backendUrl, `/v1/research/submissions/reconcile?${query}`, { method: "GET" }, fetcher);
  if (response.isError) return response;
  const payload = JSON.parse(response.content[0]?.text ?? "{}");
  const entityKey = { research_task: "task_id", experiment: "experiment_id", artifact: "artifact_id" }[request.entity_type];
  if (payload.schema_version !== "research-submission-reconciliation.v1"
      || payload.entity_type !== request.entity_type || payload.idempotency_key !== request.idempotency_key!.trim()
      || !["confirmed", "outcome_unknown"].includes(payload.status)
      || (payload.status === "confirmed" && request.entity_type !== "research_task"
        && payload.entity?.task_id !== request.task_id)
      || (payload.status === "confirmed" && (!payload.entity || Array.isArray(payload.entity) || typeof payload.entity[entityKey] !== "string" || !payload.entity[entityKey].trim()))) {
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
  }
  if (payload.status === "outcome_unknown") return result({ service: "beyondquant-mcp",
    schema_version: payload.schema_version, entity_type: request.entity_type,
    idempotency_key: payload.idempotency_key, status: "outcome_unknown", retryable: false,
    next_action: "Preserve the original request identity. Query this same key later within the task budget; do not repeat the write or infer absence from a list.",
  }, false);
  return response;
}

function validWatch(value: Record<string, unknown>, kind: ResearchEntityType): boolean {
  return value.schema_version === 'research-receipt-watch.v1' && value.entity_type === kind
    && typeof value.watch_id === 'string' && /^researchwatch_[0-9a-f]{32}$/.test(value.watch_id)
    && ['awaiting_receipt','confirmed','conflict','needs_attention'].includes(String(value.status))
    && Number.isInteger(value.attempts) && Number(value.attempts) >= 0 && Number(value.attempts) <= 8
    && value.max_attempts === 8 && typeof value.idempotency_key === 'string'
    && (value.status !== 'confirmed' || (typeof value.entity_id === 'string' && new RegExp(`^${kind === 'research_task' ? 'task' : kind}_[0-9a-f]{32}$`).test(value.entity_id)));
}

async function watchedResearchCreate(backendUrl: string, kind: ResearchEntityType, path: string,
  payload: Record<string, unknown>, fetcher: Fetcher): Promise<ByqResearchResult> {
  const registration = await postResearch(backendUrl, '/v1/research/submission-watches', {entity_type:kind,request:payload}, fetcher);
  if (registration.isError) return registration;
  const watch = JSON.parse(registration.content[0]?.text ?? '{}');
  if (!validWatch(watch,kind) || watch.idempotency_key !== String(payload.idempotency_key).trim()
      || watch.task_id !== (payload.task_id ?? null) || typeof watch.registration_created !== 'boolean') {
    // Registration may have committed. Without its exact acknowledgement no
    // business POST is sent, including on a caller's repeated registration.
    return result({service:'beyondquant-mcp',status:'outcome_unknown',retryable:false,
      ...(typeof payload.idempotency_key === 'string' && /^[A-Za-z0-9_.:-]{1,128}$/.test(payload.idempotency_key)
        ? {idempotency_key:payload.idempotency_key} : {}),
      next_action:'Receipt monitoring was not acknowledged; no research write was sent. Preserve the original identity and inspect this conversation receipt status.'},false);
  }
  if (watch.status === 'confirmed') return fetchByqResearchGet(backendUrl,kind,watch.entity_id,fetcher);
  const unknown = () => result({service:'beyondquant-mcp',status:'outcome_unknown',retryable:false,
    idempotency_key:watch.idempotency_key,submission_watch:watch,
    next_action:'BYQ will only check this original request within its persistent budget. Inspect the watch with byq_research_get; do not repeat the write or create a new identity.'},false);
  if (watch.registration_created !== true || watch.status !== 'awaiting_receipt') return unknown();
  const response = await postResearch(backendUrl,path,payload,fetcher);
  if (response.isError) return response;
  const value = JSON.parse(response.content[0]?.text ?? '{}');
  const id = value[{research_task:'task_id',experiment:'experiment_id',artifact:'artifact_id'}[kind]];
  if (value.status === 'outcome_unknown' || typeof id !== 'string' || !new RegExp(`^${kind === 'research_task' ? 'task' : kind}_[0-9a-f]{32}$`).test(id)) return unknown();
  return response;
}
