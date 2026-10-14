import {
  createProductApprovalRequest,
  decideProductApprovalRequest,
  getProductApprovalRequest,
  getProductApprovalRequestByKey,
  ResearchRequestError,
  type NewProductApprovalRequest,
  type ProductApprovalRequest,
  type ProductApprovalRequestEnvelope,
} from "@/api/research";
import { createRequestId } from "@/utils/requestId";

export interface ProductApprovalScope {
  ownerPrincipal: string;
  workspaceId: string;
}

export interface ApprovalRequestOutcome {
  request: ProductApprovalRequest;
  reconciled: boolean;
}

interface StoredRequestSubmission {
  request_key: string;
  payload: NewProductApprovalRequest;
  rejected: boolean;
}

interface StoredDecision {
  decision_key: string;
  decision: "approved" | "rejected";
}

function scopedKey(kind: string, scope: ProductApprovalScope, target: string): string {
  return `byq:product-approval:${encodeURIComponent(JSON.stringify([scope.ownerPrincipal, scope.workspaceId, kind, target]))}`;
}

function requireScope(scope: ProductApprovalScope) {
  if (!scope.ownerPrincipal || !scope.workspaceId) throw new Error("请先登录并选择工作区。");
}

function readRequestSubmission(key: string): StoredRequestSubmission | null {
  const raw = window.localStorage.getItem(key);
  if (!raw) return null;
  let value: unknown;
  try { value = JSON.parse(raw); } catch { throw new Error("本地保留的审批申请记录无法读取；请先人工核对，不会重新提交。"); }
  if (!value || typeof value !== "object") throw new Error("本地审批申请记录无效；请先人工核对。");
  const record = value as Partial<StoredRequestSubmission>;
  if (typeof record.request_key !== "string" || !record.request_key || !record.payload || typeof record.rejected !== "boolean") {
    throw new Error("本地审批申请记录不完整；请先人工核对。");
  }
  return record as StoredRequestSubmission;
}

function readDecision(key: string): StoredDecision | null {
  const raw = window.localStorage.getItem(key);
  if (!raw) return null;
  let value: unknown;
  try { value = JSON.parse(raw); } catch { throw new Error("本地审批决定记录无法读取；不会重发决定。"); }
  if (!value || typeof value !== "object") throw new Error("本地审批决定记录无效；不会重发决定。");
  const record = value as Partial<StoredDecision>;
  if (typeof record.decision_key !== "string" || !record.decision_key
      || (record.decision !== "approved" && record.decision !== "rejected")) {
    throw new Error("本地审批决定记录不完整；不会重发决定。");
  }
  return record as StoredDecision;
}

function assertRequestIdentity(
  envelope: ProductApprovalRequestEnvelope,
  scope: ProductApprovalScope,
  requestKey?: string,
  requestId?: string,
) {
  const request = envelope?.request;
  const knownStatuses = ["pending", "decision_recorded", "approved", "rejected", "outcome_unknown", "needs_attention"];
  if (envelope?.schema_version !== "byq-product-approval-request.v1"
      || !request
      || typeof request.request_id !== "string"
      || !request.request_id
      || !knownStatuses.includes(request.status)
      || request.owner_principal !== scope.ownerPrincipal
      || request.workspace_id !== scope.workspaceId
      || (requestKey && request.request_key !== requestKey)
      || (requestId && request.request_id !== requestId)) {
    throw new Error("审批申请身份或工作区不一致；请刷新并人工核对。");
  }
  return request;
}

function sameArtifactIds(left: string[], right: string[]): boolean {
  if (left.length !== right.length) return false;
  const sortedLeft = [...left].sort();
  const sortedRight = [...right].sort();
  return sortedLeft.every((artifactId, index) => artifactId === sortedRight[index]);
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[a-f0-9]{64}$/i.test(value);
}

function assertRequestMatchesPayload(request: ProductApprovalRequest, payload: NewProductApprovalRequest) {
  if (request.request_type !== payload.request_type || request.task_id !== payload.task_id
      || !isSha256(request.content_sha256)) {
    throw new Error("审批申请与原始任务或申请类型不一致；请人工核对。");
  }
  if (payload.request_type === "continuation_consent") {
    if (request.request_type !== "continuation_consent"
        || request.resource_artifact_id !== null
        || request.execution_profile_id !== payload.execution_profile_id
        || !Array.isArray(request.confirmed_artifacts)
        || !sameArtifactIds(request.confirmed_artifacts.map(item => item?.artifact_id ?? ""), payload.confirmed_artifact_ids)
        || request.confirmed_artifacts.some(item => !item || typeof item.artifact_id !== "string"
          || !isSha256(item.content_sha256)
          || !["strategy_version", "ml_strategy_version"].includes(item.kind))) {
      throw new Error("续接申请与原始确认资产不一致；请人工核对。");
    }
    return request;
  }
  if (payload.request_type === "strategy_version") {
    if (request.request_type !== "strategy_version"
        || request.strategy_version_artifact_id !== payload.strategy_version_artifact_id
        || request.resource_artifact_id !== payload.strategy_version_artifact_id) {
      throw new Error("策略审批申请与原始版本 Artifact 不一致；请人工核对。");
    }
    return request;
  }
  if (request.request_type !== "ml_strategy_version"
      || request.ml_strategy_artifact_id !== payload.ml_strategy_artifact_id
      || request.resource_artifact_id !== payload.ml_strategy_artifact_id) {
    throw new Error("模型策略审批申请与原始版本 Artifact 不一致；请人工核对。");
  }
  return request;
}

function samePayload(a: NewProductApprovalRequest, b: NewProductApprovalRequest): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function requestTarget(payload: NewProductApprovalRequest): string {
  if (payload.request_type === "continuation_consent") return payload.task_id;
  return `${payload.task_id}:${payload.request_type === "strategy_version"
    ? payload.strategy_version_artifact_id : payload.ml_strategy_artifact_id}`;
}

const terminal = (status: ProductApprovalRequest["status"]) => status === "approved" || status === "rejected";

export async function submitProductApprovalRequestOnce(
  scope: ProductApprovalScope,
  payload: NewProductApprovalRequest,
): Promise<ApprovalRequestOutcome> {
  requireScope(scope);
  const storageKey = scopedKey(`request:${payload.request_type}`, scope, requestTarget(payload));
  const saved = readRequestSubmission(storageKey);
  if (saved) {
    let existing: ProductApprovalRequestEnvelope;
    try {
      existing = await getProductApprovalRequestByKey(saved.request_key);
    } catch (error) {
      if (saved.rejected && error instanceof ResearchRequestError && error.status === 404) {
        window.localStorage.removeItem(storageKey);
        throw new Error("上次申请已确认未创建；请检查申请内容后再次点击提交。");
      }
      throw new Error("原审批申请结果尚未确认；已保留原申请键，只能继续核对，不会重发。");
    }
    const request = assertRequestMatchesPayload(
      assertRequestIdentity(existing, scope, saved.request_key),
      saved.payload,
    );
    if (!samePayload(saved.payload, payload)) {
      if (terminal(request.status)) window.localStorage.removeItem(storageKey);
      throw new Error(terminal(request.status)
        ? "原申请已结束，但当前申请内容已变化；请核对后再次点击提交。"
        : "已有同一目标的申请仍待处理或对账；不能用新内容替换原申请键。");
    }
    if (terminal(request.status)) {
      window.localStorage.removeItem(storageKey);
      return { request, reconciled: true };
    }
    return { request, reconciled: true };
  }

  const requestKey = createRequestId();
  const submission: StoredRequestSubmission = { request_key: requestKey, payload, rejected: false };
  window.localStorage.setItem(storageKey, JSON.stringify(submission));
  try {
    const created = await createProductApprovalRequest({ ...payload, request_key: requestKey });
    const request = assertRequestMatchesPayload(
      assertRequestIdentity(created, scope, requestKey),
      payload,
    );
    return { request, reconciled: false };
  } catch (error) {
    if (error instanceof ResearchRequestError && [400, 422].includes(error.status)) {
      window.localStorage.setItem(storageKey, JSON.stringify({ ...submission, rejected: true }));
      throw error;
    }
    try {
      const reconciled = await getProductApprovalRequestByKey(requestKey);
      return {
        request: assertRequestMatchesPayload(assertRequestIdentity(reconciled, scope, requestKey), payload),
        reconciled: true,
      };
    } catch {
      throw new Error("申请提交结果尚未确认；原申请键已保留，只能按该键核对，不会重发。");
    }
  }
}

export async function decideProductApprovalRequestOnce(
  scope: ProductApprovalScope,
  requestId: string,
  decision: "approved" | "rejected",
  rationale: string,
): Promise<ApprovalRequestOutcome> {
  requireScope(scope);
  const storageKey = scopedKey("decision", scope, requestId);
  const saved = readDecision(storageKey);
  if (saved) {
    const existing = await getProductApprovalRequest(requestId);
    const request = assertRequestIdentity(existing, scope, undefined, requestId);
    if (terminal(request.status)) {
      if (request.status !== saved.decision || (request.decision_key && request.decision_key !== saved.decision_key)) {
        throw new Error("已记录的决定与本地决定键不一致；请人工核对，不会重发。");
      }
      window.localStorage.removeItem(storageKey);
    }
    return { request, reconciled: true };
  }

  const current = assertRequestIdentity(await getProductApprovalRequest(requestId), scope, undefined, requestId);
  if (current.status !== "pending") return { request: current, reconciled: true };

  const decisionKey = createRequestId();
  window.localStorage.setItem(storageKey, JSON.stringify({ decision_key: decisionKey, decision }));
  let result: ProductApprovalRequestEnvelope;
  try {
    result = await decideProductApprovalRequest(requestId, {
      schema_version: "byq-product-approval-decision.v1",
      decision_key: decisionKey,
      decision,
      rationale,
    });
  } catch {
    const reconciled = await getProductApprovalRequest(requestId);
    const request = assertRequestIdentity(reconciled, scope, undefined, requestId);
    if (terminal(request.status)) {
      if (request.status !== decision || (request.decision_key && request.decision_key !== decisionKey)) {
        throw new Error("精确审批读取与本次决定不一致；本地决定键已保留，请人工核对。");
      }
      window.localStorage.removeItem(storageKey);
    }
    return { request, reconciled: true };
  }
  let request = assertRequestIdentity(result, scope, undefined, requestId);
  if (terminal(request.status)) {
    const exact = await getProductApprovalRequest(requestId);
    request = assertRequestIdentity(exact, scope, undefined, requestId);
    if (request.status !== decision || (request.decision_key && request.decision_key !== decisionKey)) {
      throw new Error("精确审批读取与本次决定不一致；本地决定键已保留，请人工核对。");
    }
    window.localStorage.removeItem(storageKey);
  }
  return { request, reconciled: false };
}
