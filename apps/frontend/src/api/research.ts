const ROOT = "/api/product";

export interface ResearchReceipt {
  watch_id: string;
  entity_type: 'research_task' | 'experiment' | 'artifact';
  status: 'awaiting_receipt' | 'confirmed' | 'conflict' | 'needs_attention';
  entity_id: string | null;
  attempts: number;
  max_attempts: number;
  deadline_at: string;
  reason: string;
}

export function getResearchReceipts(conversationId: string): Promise<{
  schema_version: 'research-receipt-list.v1'; conversation_id: string; receipts: ResearchReceipt[];
}> {
  return getJson(`/research/submission-watches?conversation_id=${encodeURIComponent(conversationId)}`,
    { signal: AbortSignal.timeout(8000) });
}

export class ResearchRequestError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string) { super(message); }
}

async function getJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${ROOT}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init.body ? { "content-type": "application/json" } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      error?: { code?: unknown; message?: unknown };
    };
    const code = typeof body.error?.code === "string" ? body.error.code : undefined;
    const message = typeof body.error?.message === "string" ? body.error.message : "research request failed";
    throw new ResearchRequestError(message, response.status, code);
  }
  return (await response.json()) as T;
}

export function getResearchEntity(
  entityType: "tasks" | "experiments" | "artifacts",
  entityId: string,
): Promise<Record<string, unknown>> {
  return getJson(`/research/${entityType}/${encodeURIComponent(entityId)}`);
}

export function getApproval(approvalId: string): Promise<Record<string, unknown>> {
  return getJson(`/approvals/${encodeURIComponent(approvalId)}`);
}

export function listArtifacts(): Promise<{ artifacts: Array<Record<string, unknown>> }> {
  return getJson("/research/artifacts");
}

export function listTasks(): Promise<{ tasks: Array<Record<string, unknown>> }> {
  return getJson("/research/tasks");
}

export interface ContinuationExecutionProfileBinding {
  profile_id: 'task-ready-read.v1';
  profile_version: number;
  profile_sha256: string;
}

export interface ContinuationRequestLimits {
  max_provider_calls: number;
  max_attempts: number;
  max_concurrent: number;
  max_input_bytes: number;
  max_total_input_bytes: number;
  max_output_tokens: number;
  max_total_output_tokens: number;
  max_tool_payload_bytes: number;
  max_total_tool_payload_bytes: number;
  max_tool_calls: number;
  deadline_ms: number;
}

export interface ContinuationAvailableProfile {
  execution_profile: ContinuationExecutionProfileBinding;
  request_limits: ContinuationRequestLimits;
}

export interface ContinuationRequestUsage {
  schema_version: 'continuation-request-usage.v1';
  execution_profile: ContinuationExecutionProfileBinding;
  request_limits: ContinuationRequestLimits;
  admission_usage: {
    provider_calls: number; provider_attempts: number; input_bytes: number; declared_output_tokens: number;
    tool_payload_bytes: number; max_input_bytes: number; max_declared_output_tokens: number;
    max_tool_payload_bytes: number; tool_calls: number; max_concurrent: number; elapsed_ms: number;
  };
  actual_usage: {
    input_tokens: number | 'unknown'; cache_read_tokens: number | 'unknown';
    output_tokens: number | 'unknown'; provider_attempts: number | 'unknown';
    usage_source: 'provider_response' | 'unknown' | 'no_provider_calls';
    completeness: 'known' | 'partial' | 'unknown';
  };
  limit_violations: Array<keyof ContinuationRequestLimits | 'provider_declared_output_exceeded'>;
}

export interface ContinuationV2Permission {
  schema_version: 'task-continuation-permission.v2';
  grant_version: number;
  confirmation_id: string;
  confirmed_artifact_ids: string[];
  execution_profile: ContinuationExecutionProfileBinding;
  request_limits: ContinuationRequestLimits;
  max_turns: 1;
  turn_timeout_seconds: number;
  expires_at: string;
  revoked_at: string | null;
}

interface ContinuationPermissionViewBase {
  task_id: string;
  can_start: boolean;
  blocked_reason: string;
  blocked_event_key?: string | null;
  blocked_reason_detail?: string | null;
}

export interface ContinuationPermissionViewV2 extends ContinuationPermissionViewBase {
  schema_version: 'task-continuation-permission.v2';
  available_profile: ContinuationAvailableProfile | null;
  permission: ContinuationV2Permission | null;
  request_state: {
    requests_reserved: number;
    requests_remaining: number;
    unconfirmed_requests: number;
    request_usage: ContinuationRequestUsage | null;
    request_identity?: null | {
      reservation_id: string;
      status: string;
      run_id: string | null;
      event_key: string | null;
      input_sha256: string | null;
      grant_version: number;
      outcome: string | null;
      settlement_sha256: string | null;
      dispatch_attempts: number;
    };
  };
}

export interface ContinuationPermissionViewLegacy extends ContinuationPermissionViewBase {
  schema_version: 'task-continuation-permission.v1';
  permission: null | {
    grant_version: number; token_limit: number; max_turns?: number;
    turn_timeout_seconds?: number; expires_at: string; revoked_at: string | null;
  };
  budget?: { token_limit?: number; reserved_tokens: number; charged_tokens: number;
    available_tokens: number; turns_remaining: number; unconfirmed_reservations: number;
    reserved_token_ceiling?: number; actual_usage?: Record<string, unknown> };
}

export type ContinuationPermissionView = ContinuationPermissionViewV2 | ContinuationPermissionViewLegacy;

export function getContinuationPermission(taskId: string): Promise<ContinuationPermissionView> {
  return getJson(`/research/tasks/${encodeURIComponent(taskId)}/continuation-permission`);
}

export function revokeContinuationPermission(taskId: string, grantVersion: number): Promise<ContinuationPermissionView> {
  return getJson(`/research/tasks/${encodeURIComponent(taskId)}/continuation-permission/revoke`, {
    method: 'POST', headers: { 'x-byq-continuation-confirmation': 'v1' },
    body: JSON.stringify({ grant_version: grantVersion }),
  });
}

export function listTaskOptions(limit = 50): Promise<{ tasks: Array<Record<string, unknown>> }> {
  return getJson(`/research/task-options?limit=${limit}`);
}

export async function createTask(
  title: string,
  objective: string,
  idempotencyKey?: string,
): Promise<Record<string, unknown>> {
  try {
    return await getJson("/research/tasks", {
      method: "POST",
      ...(idempotencyKey ? { headers: { "x-idempotency-key": idempotencyKey } } : {}),
      body: JSON.stringify({ title, objective }),
    });
  } catch (error) {
    if (error instanceof ResearchRequestError) throw error;
    throw new ResearchRequestError("提交结果尚未确认，请核对本次提交；不要新建任务。", 503);
  }
}

export function listExperiments(): Promise<{ experiments: Array<Record<string, unknown>> }> {
  return getJson("/research/experiments");
}

export function listApprovals(options: { status?: string; limit?: number; offset?: number } = {}): Promise<{
  approvals: Array<Record<string, unknown>>;
  total: number;
  pending_count: number;
  limit: number;
  offset: number;
}> {
  const params = new URLSearchParams();
  if (options.status) params.set("status", options.status);
  params.set("limit", String(options.limit ?? 50));
  params.set("offset", String(options.offset ?? 0));
  return getJson(`/approvals?${params.toString()}`);
}

export type ProductApprovalRequestType = "continuation_consent" | "strategy_version" | "ml_strategy_version";
export type ProductApprovalRequestStatus = "pending" | "decision_recorded" | "approved" | "rejected" | "outcome_unknown" | "needs_attention";

export interface ProductApprovalRequestBase {
  request_id: string;
  request_type: ProductApprovalRequestType;
  status: ProductApprovalRequestStatus;
  owner_principal: string;
  workspace_id: string;
  task_id: string;
  resource_artifact_id: string | null;
  content_sha256: string;
  request_key: string;
  created_at: string;
  updated_at: string;
  decision?: "approved" | "rejected";
  decision_key?: string;
  decision_by?: string;
  decision_at?: string;
  rationale?: string;
  domain_artifact_id?: string | null;
  permission?: Record<string, unknown> | null;
  materialization_error_code?: string | null;
  observed_state?: "confirmed" | "missing" | "draft" | "mismatch" | "unavailable";
}

export interface ContinuationConsentProductApprovalRequest extends ProductApprovalRequestBase {
  request_type: "continuation_consent";
  conversation_id: string;
  confirmed_artifacts: Array<{ artifact_id: string; content_sha256: string; kind: "strategy_version" | "ml_strategy_version" }>;
  execution_profile_id: "task-ready-read.v1";
  request_limits: ContinuationRequestLimits;
}

export interface StrategyVersionProductApprovalRequest extends ProductApprovalRequestBase {
  request_type: "strategy_version";
  strategy_version_artifact_id: string;
}

export interface MLStrategyVersionProductApprovalRequest extends ProductApprovalRequestBase {
  request_type: "ml_strategy_version";
  ml_strategy_artifact_id: string;
}

export type ProductApprovalRequest = ContinuationConsentProductApprovalRequest
  | StrategyVersionProductApprovalRequest
  | MLStrategyVersionProductApprovalRequest;

export type ProductApprovalRequestPayload =
  | { schema_version: "byq-product-approval-request.v1"; request_type: "continuation_consent";
      request_key: string; task_id: string; confirmed_artifact_ids: string[];
      execution_profile_id: "task-ready-read.v1" }
  | { schema_version: "byq-product-approval-request.v1"; request_type: "strategy_version";
      request_key: string; task_id: string; strategy_version_artifact_id: string }
  | { schema_version: "byq-product-approval-request.v1"; request_type: "ml_strategy_version";
      request_key: string; task_id: string; ml_strategy_artifact_id: string };

export type NewProductApprovalRequest =
  | { schema_version: "byq-product-approval-request.v1"; request_type: "continuation_consent";
      task_id: string; confirmed_artifact_ids: string[]; execution_profile_id: "task-ready-read.v1" }
  | { schema_version: "byq-product-approval-request.v1"; request_type: "strategy_version";
      task_id: string; strategy_version_artifact_id: string }
  | { schema_version: "byq-product-approval-request.v1"; request_type: "ml_strategy_version";
      task_id: string; ml_strategy_artifact_id: string };

export interface ProductApprovalRequestEnvelope {
  schema_version: "byq-product-approval-request.v1";
  request: ProductApprovalRequest;
}

export interface ProductApprovalRequestList {
  schema_version: "byq-product-approval-request-list.v1";
  requests: ProductApprovalRequest[];
  total: number;
  pending_count: number;
  attention_count: number;
  limit: number;
  offset: number;
}

export function listProductApprovalRequests(options: {
  status?: "pending" | "unresolved" | "approved" | "rejected" | "all";
  limit?: number;
  offset?: number;
} = {}): Promise<ProductApprovalRequestList> {
  const params = new URLSearchParams();
  if (options.status) params.set("status", options.status);
  params.set("limit", String(options.limit ?? 50));
  params.set("offset", String(options.offset ?? 0));
  return getJson(`/research/approval-requests?${params.toString()}`);
}

export function createProductApprovalRequest(payload: ProductApprovalRequestPayload): Promise<ProductApprovalRequestEnvelope> {
  return getJson("/research/approval-requests", {
    method: "POST",
    headers: { "x-byq-product-approval-confirmation": "v1" },
    body: JSON.stringify(payload),
  });
}

export function getProductApprovalRequest(requestId: string): Promise<ProductApprovalRequestEnvelope> {
  return getJson(`/research/approval-requests/${encodeURIComponent(requestId)}`);
}

export function getProductApprovalRequestByKey(requestKey: string): Promise<ProductApprovalRequestEnvelope> {
  return getJson(`/research/approval-requests/by-key/${encodeURIComponent(requestKey)}`);
}

export function reconcileProductApprovalRequest(requestId: string): Promise<ProductApprovalRequestEnvelope> {
  return getJson(`/research/approval-requests/${encodeURIComponent(requestId)}/reconcile`, {
    method: "POST",
    headers: { "x-byq-product-approval-confirmation": "v1" },
  });
}

export function decideProductApprovalRequest(requestId: string, payload: {
  schema_version: "byq-product-approval-decision.v1";
  decision_key: string;
  decision: "approved" | "rejected";
  rationale: string;
}): Promise<ProductApprovalRequestEnvelope> {
  return getJson(`/research/approval-requests/${encodeURIComponent(requestId)}/decision`, {
    method: "POST",
    headers: { "x-byq-product-approval-confirmation": "v1" },
    body: JSON.stringify(payload),
  });
}

export function decideApproval(
  approvalId: string,
  decision: "approved" | "rejected",
  rationale: string,
): Promise<{ approval: Record<string, unknown> }> {
  return getJson(`/approvals/${encodeURIComponent(approvalId)}/decision`, {
    method: "POST",
    body: JSON.stringify({ decision, rationale }),
  });
}

export function continueApproval(
  approvalId: string,
): Promise<{ approval: Record<string, unknown> }> {
  return getJson(`/approvals/${encodeURIComponent(approvalId)}/continue`, { method: "POST" });
}

export interface TaskHandoffView {
  schema_version: 'research-task-handoff.v1'; task_id: string; task_version: number;
  task_status: string; objective: string; progress: unknown; state: string;
  reason: string | null; references: Array<{ kind: string; id: string; status: string }>;
  has_more: boolean; observed_at: string;
}
export function getTaskHandoff(taskId: string): Promise<TaskHandoffView> {
  return getJson(`/research/tasks/${encodeURIComponent(taskId)}/handoff`);
}
