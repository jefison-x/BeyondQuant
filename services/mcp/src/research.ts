import { createHash } from "node:crypto";
import { safeRequestValidation } from "./request-validation.js";
import { bindActiveWebEvidenceProducer } from "./web-evidence-provenance.js";
import { fetchByqSignalSnapshotGet } from "./backtest.js";

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

const RESEARCH_EXECUTION_NOTE =
  "This query reports existing task state and grants no authority. Automatic continuation uses saved conversation settings and trusted events without a separate continuation permission; business actions still require their current authorization and approval.";

// Fixed bounded explanations selected only from a legal handoff state/reason
// pair. Maps are own-entry lookups, so hostile keys such as __proto__,
// constructor or toString are never treated as facts. Missing, malformed,
// foreign-ID or contradictory state/reason yields no note instead of copying
// arbitrary handoff or error prose into instructions.
const RESEARCH_HANDOFF_STATE_NOTES = new Map<string, string>([
  ["waiting_job", "Task is waiting on an existing Domain Job. This query does not advance or resume it."],
  ["waiting_approval", "An approval is pending. Request that human approval outside this query; this query does not grant it."],
  ["approval_continuation_queued", "Approval continuation is queued. This query does not dispatch or resume it."],
  ["continuation_queued", "A reserved continuation event is recorded for this task. This does not show that it was dispatched or that a new event was authorized."],
  ["waiting_event", "No continuation event is currently pending. Automatic continuation may follow trusted future events under saved conversation settings."],
  ["completed", "This reports a confirmed task status; validate same-task evidence before claiming completion."],
  ["failed", "This reports the task status; this query does not change or retry it."],
  ["cancelled", "This reports the task status; this query does not change or resume it."],
]);

const RESEARCH_HANDOFF_REASON_NOTES = new Map<string, string>([
  ["completion_evidence_missing", "Completion evidence is missing. Reconcile existing same-task evidence; this query does not replay or complete work."],
  ["evidence_limit_reached", "Referenced evidence exceeded the bounded snapshot. Reconcile with the existing receipts; this query does not replay writes."],
  ["continuation_result_unconfirmed", "A continuation result is unconfirmed. Inspect the existing receipts; this query does not replay it."],
  ["approval_binding_invalid", "An approval binding is invalid. Reconcile existing approval references; this query does not re-approve."],
  ["approval_continuation_unconfirmed", "An approval continuation is unconfirmed. Inspect the existing receipts; this query does not resubmit it."],
  ["task_execution_unconfirmed", "Task execution is unconfirmed. This query does not prove, resume, or attribute execution."],
  ["conversation_binding_missing", "The conversation binding is missing. This query does not repair or recreate it."],
  ["no_registered_executor", "No registered executor is available. This query does not register or start one."],
  ["conversation_inactive", "The original conversation is inactive. This query does not reopen it."],
  ["automatic_continuation_disabled", "Automatic continuation is disabled for future events in this conversation. Existing recorded events remain separately visible."],
  ["automatic_continuation_stopped", "An explicit stop was recorded for automatic continuation. This query does not restart it."],
  ["continuation_needs_attention", "A continuation needs attention. Keep any listed event status intact; this query does not cancel it or restart continuation."],
  ["execution_options_invalid", "Saved conversation settings did not pass validation. Existing event records remain intact; this query does not admit new events."],
  ["continuation_ledger_invalid", "Continuation records did not pass validation. Preserve their recorded states and reconcile; this query does not replay them."],
]);

// Legal state/reason pair sets derived from the actual Backend projection.
const RESEARCH_NULL_REASON_STATES = new Set([
  "waiting_job", "waiting_approval", "approval_continuation_queued",
  "continuation_queued", "waiting_event", "completed", "failed", "cancelled",
]);
const RESEARCH_RECONCILE_REASONS = new Set([
  "completion_evidence_missing", "evidence_limit_reached", "continuation_result_unconfirmed",
  "execution_options_invalid", "continuation_ledger_invalid",
  "approval_binding_invalid", "approval_continuation_unconfirmed",
  "continuation_needs_attention",
]);
const RESEARCH_BLOCKED_REASONS = new Set([
  "conversation_binding_missing", "conversation_inactive", "no_registered_executor",
  "automatic_continuation_disabled", "automatic_continuation_stopped", "continuation_needs_attention",
]);

function researchContinuationNote(value: Record<string, unknown>, taskId: string): string | undefined {
  const handoff = value.handoff;
  if (handoff === null || typeof handoff !== "object" || Array.isArray(handoff)) return undefined;
  const entry = handoff as Record<string, unknown>;
  if (entry.schema_version !== "research-task-handoff.v1") return undefined;
  if (entry.task_id !== taskId) return undefined;
  const state = typeof entry.state === "string" ? entry.state : undefined;
  if (state === undefined) return undefined;
  // A legal reason is a string or null; any other type is malformed.
  const rawReason = entry.reason;
  if (rawReason !== null && typeof rawReason !== "string") return undefined;
  const reason: string | null = typeof rawReason === "string" ? rawReason : null;
  if (RESEARCH_NULL_REASON_STATES.has(state)) {
    return reason === null ? RESEARCH_HANDOFF_STATE_NOTES.get(state) : undefined;
  }
  if (state === "conversation_active") {
    return reason === "task_execution_unconfirmed"
      ? RESEARCH_HANDOFF_REASON_NOTES.get(reason) : undefined;
  }
  if (state === "needs_reconciliation") {
    return reason !== null && RESEARCH_RECONCILE_REASONS.has(reason)
      ? RESEARCH_HANDOFF_REASON_NOTES.get(reason) : undefined;
  }
  if (state === "blocked") {
    return reason !== null && RESEARCH_BLOCKED_REASONS.has(reason)
      ? RESEARCH_HANDOFF_REASON_NOTES.get(reason) : undefined;
  }
  return undefined;
}

// Notes attach only to a successful exact research_task entity_id GET whose
// parsed task identity matches the requested id. The byq_research_get watch
// branch returns its validated watch envelope directly and never reaches this
// helper; only the existing watchedResearchCreate confirmed-registration reread
// reuses this entity GET and therefore receives the same notes.
function withResearchTaskNotes(response: ByqResearchResult, taskId: string): ByqResearchResult {
  if (response.isError) return response;
  const text = response.content[0]?.text;
  if (typeof text !== "string") return response;
  let payload: unknown;
  try { payload = JSON.parse(text); } catch { return response; }
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) return response;
  const record = payload as Record<string, unknown>;
  if (record.task_id !== taskId) return response;
  const note = researchContinuationNote(record, taskId);
  // Reserve continuation_note for this fixed whitelist. Never pass through a
  // Backend value when handoff is absent, malformed or bound to another task.
  const safeRecord = { ...record };
  delete safeRecord.continuation_note;
  return result({
    ...safeRecord,
    execution_note: RESEARCH_EXECUTION_NOTE,
    ...(note ? { continuation_note: note } : {}),
  }, false);
}

const ARTIFACT_STATUSES = ["draft", "validated", "superseded"];
const CONTENT_SHA256_PATTERN = /^[a-f0-9]{64}$/;
const SIGNAL_SUMMARY_SCHEMA_VERSION = "signal-snapshot-summary.v1";
const MAX_MCP_PAYLOAD_BYTES = 64 * 1024;
// The Backend summary carries exactly these four top-level fields.
const SIGNAL_SUMMARY_TOP_LEVEL_KEYS = new Set([
  "schema_version", "artifact", "snapshot", "diagnostic_samples",
]);
// Raw execution/panel field names (plus the raw `content` body) that must never
// reach a Product Agent. The Backend bounded projection already excludes them;
// enforcing the same closed set here keeps the MCP boundary fail-closed.
const FORBIDDEN_SIGNAL_SUMMARY_FIELDS = new Set([
  "content", "bars_frame", "bars", "signals", "corporate_actions", "benchmark",
  "symbols", "symbol_index", "date_index", "columns", "research_bars", "script",
]);
// Mirrors FORBIDDEN_STRATEGY_FIELDS in
// packages/contracts/signal_snapshot_summary.py: the summary's
// snapshot.strategy block may carry identity only, never the frozen executable
// payload.
const FORBIDDEN_STRATEGY_FIELDS = new Set(["script", "snapshot", "parameters", "source"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function invalidResearchResponse(): ByqResearchResult {
  return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
}

function parseResultPayload(response: ByqResearchResult): Record<string, unknown> | undefined {
  try {
    const value = JSON.parse(response.content[0]?.text ?? "{}");
    return isRecord(value) ? value : undefined;
  } catch {
    return undefined;
  }
}

function containsForbiddenSignalSummaryField(value: unknown): boolean {
  if (Array.isArray(value)) return value.some(containsForbiddenSignalSummaryField);
  if (!isRecord(value)) return false;
  for (const [key, item] of Object.entries(value)) {
    if (FORBIDDEN_SIGNAL_SUMMARY_FIELDS.has(key) || containsForbiddenSignalSummaryField(item)) return true;
  }
  return false;
}

function boundedResultPayload(payload: Record<string, unknown>): ByqResearchResult {
  // The whole Product-Agent payload (identity, wrapper and summary) must stay
  // within the 64 KiB bound, not just the nested summary.
  if (Buffer.byteLength(JSON.stringify(payload), "utf8") > MAX_MCP_PAYLOAD_BYTES) {
    return invalidResearchResponse();
  }
  return result(payload, false);
}

function hasExactSignalSummaryKeys(summary: Record<string, unknown>): boolean {
  const keys = Object.keys(summary);
  return keys.length === SIGNAL_SUMMARY_TOP_LEVEL_KEYS.size
    && keys.every((key) => SIGNAL_SUMMARY_TOP_LEVEL_KEYS.has(key));
}

type ArtifactReference = {
  artifactId: string;
  type: string;
  status: string;
  contentSha256: string;
  ownerPrincipal?: unknown;
  workspaceId?: unknown;
};

// The reference contract is strictly typed: project_artifact always carries a
// non-empty `type` plus validation.status/content_sha256. A projection without
// that typed contract is rejected; there is no legacy fallback to the raw row.
async function fetchArtifactReference(
  backendUrl: string,
  artifactId: string,
  fetcher: Fetcher,
): Promise<{ reference?: ArtifactReference; error?: ByqResearchResult }> {
  const response = await requestResearch(
    backendUrl,
    `/v1/research/artifacts/${encodeURIComponent(artifactId)}/reference`,
    { method: "GET" },
    fetcher,
  );
  if (response.isError) return { error: response };
  const projection = parseResultPayload(response);
  const validation = projection?.validation;
  if (!projection
      || projection.artifact_id !== artifactId
      || typeof projection.type !== "string" || !projection.type.trim()
      || !isRecord(validation)
      || typeof validation.status !== "string" || !ARTIFACT_STATUSES.includes(validation.status)
      || typeof validation.content_sha256 !== "string" || !CONTENT_SHA256_PATTERN.test(validation.content_sha256)) {
    return { error: invalidResearchResponse() };
  }
  return { reference: {
    artifactId,
    type: projection.type,
    status: validation.status,
    contentSha256: validation.content_sha256,
    ownerPrincipal: projection.owner_principal,
    workspaceId: projection.workspace_id,
  } };
}

type SignalSnapshotReadExpectation = {
  artifactId: string;
  contentSha256: string;
  status: string;
  taskId?: string;
  ownerPrincipal?: unknown;
  workspaceId?: unknown;
};

type BoundedSignalSnapshot = {
  artifactId: string;
  taskId: unknown;
  kind: string;
  status: string;
  contentSha256: string;
  summary: Record<string, unknown>;
};

async function readBoundedSignalSnapshot(
  backendUrl: string,
  expected: SignalSnapshotReadExpectation,
  fetcher: Fetcher,
): Promise<{ value?: BoundedSignalSnapshot; error?: ByqResearchResult }> {
  const response = await fetchByqSignalSnapshotGet(backendUrl, expected.artifactId, fetcher);
  if (response.isError) return { error: response };
  const payload = parseResultPayload(response);
  const summary = payload?.summary;
  if (!isRecord(summary)
      || !hasExactSignalSummaryKeys(summary)
      || containsForbiddenSignalSummaryField(summary)) {
    return { error: invalidResearchResponse() };
  }
  const snapshot = summary.snapshot;
  const diagnosticSamples = summary.diagnostic_samples;
  const integrity = isRecord(snapshot) ? snapshot.integrity : undefined;
  const strategy = isRecord(snapshot) ? snapshot.strategy : undefined;
  const artifact = summary.artifact;
  if (!isRecord(snapshot)
      || !isRecord(diagnosticSamples)
      || !isRecord(integrity)
      || integrity.content_sha256 !== expected.contentSha256
      || !isRecord(strategy)
      || Object.keys(strategy).some((key) => FORBIDDEN_STRATEGY_FIELDS.has(key))
      || !isRecord(artifact)
      || summary.schema_version !== SIGNAL_SUMMARY_SCHEMA_VERSION
      || artifact.artifact_id !== expected.artifactId
      || artifact.kind !== "signal_snapshot"
      || artifact.content_sha256 !== expected.contentSha256
      || artifact.status !== expected.status
      || (expected.taskId !== undefined && artifact.task_id !== expected.taskId)
      || (expected.ownerPrincipal !== undefined && artifact.owner_principal !== undefined
          && artifact.owner_principal !== expected.ownerPrincipal)
      || (expected.workspaceId !== undefined && artifact.workspace_id !== undefined
          && artifact.workspace_id !== expected.workspaceId)) {
    return { error: invalidResearchResponse() };
  }
  return { value: {
    artifactId: expected.artifactId,
    taskId: artifact.task_id ?? null,
    kind: "signal_snapshot",
    status: expected.status,
    contentSha256: expected.contentSha256,
    summary,
  } };
}

async function requestResearchEntity(
  backendUrl: string,
  entityType: ResearchEntityType,
  entityId: string,
  fetcher: Fetcher,
): Promise<ByqResearchResult> {
  const response = await requestResearch(
    backendUrl,
    `/v1/research/${entityType === "research_task" ? "tasks" : `${entityType}s`}/${encodeURIComponent(entityId)}`,
    { method: "GET" },
    fetcher,
  );
  if (response.isError) return response;
  const value = parseResultPayload(response);
  const key = {research_task:'task_id',experiment:'experiment_id',artifact:'artifact_id'}[entityType];
  if (!value || value[key] !== entityId) return invalidResearchResponse();
  return response;
}

// A non-signal Artifact keeps the original full-row read, but the raw row must
// still agree with the typed reference so a non-signal reference cannot hand
// back a raw signal_snapshot body.
async function readTypedArtifactRow(
  backendUrl: string,
  reference: ArtifactReference,
  fetcher: Fetcher,
): Promise<ByqResearchResult> {
  const raw = await requestResearchEntity(backendUrl, "artifact", reference.artifactId, fetcher);
  if (raw.isError) return raw;
  const value = parseResultPayload(raw);
  if (!value || value.kind !== reference.type) return invalidResearchResponse();
  return raw;
}

function signalSnapshotPayload(value: BoundedSignalSnapshot): Record<string, unknown> {
  // Fixed, closed signal shape: no reference metadata/ref/owner/workspace is
  // ever forwarded, so a poisoned reference projection cannot reach the Agent.
  return {
    service: "beyondquant-mcp",
    status: value.status,
    artifact_id: value.artifactId,
    task_id: value.taskId,
    kind: value.kind,
    content_sha256: value.contentSha256,
    summary: value.summary,
  };
}

export async function fetchByqResearchGet(
  backendUrl: string,
  entityType: ResearchEntityType,
  entityId: string,
  fetcher: Fetcher = fetch,
): Promise<ByqResearchResult> {
  if (entityType === "research_task") {
    const response = await requestResearchEntity(backendUrl, entityType, entityId, fetcher);
    return withResearchTaskNotes(response, entityId);
  }
  if (entityType !== "artifact") return requestResearchEntity(backendUrl, entityType, entityId, fetcher);
  // The typed reference decides the true artifact type before any raw read. A
  // signal_snapshot is only ever returned as a bounded safe summary; a
  // reference failure never falls back to the raw artifact row.
  const reference = await fetchArtifactReference(backendUrl, entityId, fetcher);
  if (reference.error) return reference.error;
  const ref = reference.reference!;
  if (ref.type !== "signal_snapshot") return readTypedArtifactRow(backendUrl, ref, fetcher);
  const snapshot = await readBoundedSignalSnapshot(backendUrl, {
    artifactId: ref.artifactId,
    contentSha256: ref.contentSha256,
    status: ref.status,
    ownerPrincipal: ref.ownerPrincipal,
    workspaceId: ref.workspaceId,
  }, fetcher);
  if (snapshot.error) return snapshot.error;
  return boundedResultPayload(signalSnapshotPayload(snapshot.value!));
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
        message: 'Use a listed target_status. blocked is a task progress.stage, not a status; active and in_progress are invalid. Read the entity before choosing a legal transition.' },
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

export async function fetchByqWebEvidenceCreate(
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
  const response = await requestResearch(
    backendUrl,
    "/v1/research/web-evidence-records",
    { method: "POST", body: JSON.stringify(trustedRequest) },
    fetcher,
    true,
    (payload) => {
      const task = payload.task as Record<string, unknown> | null;
      const artifact = payload.artifact as Record<string, unknown> | null;
      const content = artifact?.content as Record<string, unknown> | null;
      if (payload.record_status !== 'saved'
          || !task || Array.isArray(task) || !artifact || Array.isArray(artifact)
          || typeof task.task_id !== 'string' || !/^task_[0-9a-f]{32}$/.test(task.task_id)
          || payload.idempotency_key !== request.idempotency_key.trim()
          || task.title !== request.task.title.trim() || task.objective !== request.task.objective.trim()
          || typeof artifact.artifact_id !== 'string' || !/^artifact_[0-9a-f]{32}$/.test(artifact.artifact_id)
          || artifact.task_id !== task.task_id || artifact.kind !== 'web_research_evidence'
          || !Number.isSafeInteger(payload.source_count) || Number(payload.source_count) < 0
          || !Array.isArray(content?.sources) || content.sources.length !== payload.source_count) {
        // requestResearch classifies a rejected write receipt as unknown, preserving its key.
        throw new Error('invalid web evidence receipt');
      }
      const artifactId = artifact.artifact_id;
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
  const resultBody = JSON.parse(response.content[0].text);
  if (resultBody.status === 'outcome_unknown') {
    const digest = createHash('sha256').update(request.idempotency_key.trim()).digest('hex').slice(0, 32);
    resultBody.reconciliation = { tool: 'byq_research_get', arguments: {
      entity_type: 'research_task', idempotency_key: `web-record-task:${digest}`,
    }, then: { tool: 'byq_research_get', entity_type: 'artifact',
      idempotency_key: `web-record-artifact:${digest}`,
      task_id_source: 'confirmed_original_task_id',
    } };
    return result(resultBody, false);
  }
  return response;
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
      backend: { status: "research_request_invalid", validation: {
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
  if (request.entity_type === "artifact") {
    // The confirmed entity is a raw Artifact row. The typed reference decides
    // the true type, and the raw row must agree on identity, parent task, kind,
    // hash and status. A missing/wrong kind or any mismatch fails closed; the
    // raw row is never returned for a signal_snapshot.
    const entity = payload.entity as Record<string, unknown>;
    const reference = await fetchArtifactReference(backendUrl, entity[entityKey] as string, fetcher);
    if (reference.error) return reference.error;
    const ref = reference.reference!;
    if (entity.artifact_id !== ref.artifactId
        || entity.task_id !== request.task_id
        || entity.kind !== ref.type
        || entity.status !== ref.status
        || entity.content_sha256 !== ref.contentSha256) {
      return invalidResearchResponse();
    }
    if (ref.type !== "signal_snapshot") return response;
    const snapshot = await readBoundedSignalSnapshot(backendUrl, {
      artifactId: ref.artifactId,
      contentSha256: ref.contentSha256,
      status: ref.status,
      taskId: request.task_id,
      ownerPrincipal: ref.ownerPrincipal,
      workspaceId: ref.workspaceId,
    }, fetcher);
    if (snapshot.error) return snapshot.error;
    const value = snapshot.value!;
    return boundedResultPayload({
      service: "beyondquant-mcp",
      schema_version: payload.schema_version,
      entity_type: payload.entity_type,
      idempotency_key: payload.idempotency_key,
      status: payload.status,
      entity: {
        artifact_id: value.artifactId,
        task_id: value.taskId,
        kind: value.kind,
        status: value.status,
        content_sha256: value.contentSha256,
        summary: value.summary,
      },
    });
  }
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
