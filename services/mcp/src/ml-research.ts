import { isWriteRequest, unknownWriteResult } from "./write-outcome.js";
import { safeDomainAdmission } from "./domain-admission.js";

const BACKEND_TIMEOUT_MS = 8000;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;
export type MlRequest = Record<string, unknown>;
export type ByqMlResult = { content: Array<{ type: "text"; text: string }>; isError: boolean };

function result(payload: unknown, isError: boolean): ByqMlResult {
  return { content: [{ type: "text", text: JSON.stringify(payload) }], isError };
}

function errorStatus(status: number): string {
  if (status === 403) return "ml_action_forbidden";
  if (status === 404) return "ml_resource_not_found";
  if (status === 409) return "ml_action_conflict";
  if (status === 422) return "ml_request_invalid";
  return "ml_research_unavailable";
}

const VALIDATION_FIELDS = new Set("strategy schema_version name learner kind profile parameters learner_parameters feature_set id target horizon_sessions split train validation prediction start end signal_policy top_n rebalance validation_plan development_window prediction_window portfolio_policy mode train_sessions validation_sessions step_sessions folds purge_sessions embargo_sessions alpha fit_intercept num_leaves learning_rate max_depth min_data_in_leaf feature_fraction bagging_fraction num_boost_round early_stopping_rounds regime definition enabled routing_policy fallback experts risk_on neutral risk_off training_regimes 0 1 2 3".split(" "));
const VALIDATION_CODES = new Set(["object_required", "unknown_fields", "text_required", "date_format", "integer_required", "number_required", "boolean_required", "out_of_range", "unsupported_value"]);
function safeValidation(payload: Record<string, unknown>) {
  const detail = payload.detail;
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return undefined;
  const value = detail as Record<string, unknown>;
  if (value.schema_version !== "ml-validation-problem.v1" || typeof value.field !== "string"
      || value.field.split(".").length > 6 || !value.field.split(".").every(part => VALIDATION_FIELDS.has(part))
      || typeof value.code !== "string" || !VALIDATION_CODES.has(value.code)) return undefined;
  return { schema_version: "ml-validation-problem.v1", field: value.field, code: value.code, repair_limit: 1,
    next_action: "Read byq_ml_capabilities for qualified types, ranges and allowed values; correct once with a distinct request identity. Stop if the same error recurs without progress." };
}

async function requestMl(
  backendUrl: string,
  path: string,
  init: RequestInit,
  fetcher: Fetcher,
  timeoutMs = BACKEND_TIMEOUT_MS,
): Promise<ByqMlResult> {
  try {
    const response = await fetcher(`${backendUrl}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init.headers ?? {}) },
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (isWriteRequest(init) && response.status >= 500) return unknownWriteResult(init);
    let payload: unknown;
    try { payload = await response.json(); } catch {
      if (isWriteRequest(init) && response.ok) return unknownWriteResult(init);
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
      if (isWriteRequest(init) && response.ok) return unknownWriteResult(init);
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (!response.ok) {
      const admission = safeDomainAdmission(payload);
      const validation = response.status === 422 ? safeValidation(payload as Record<string, unknown>) : undefined;
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: errorStatus(response.status), http_status: response.status,
        ...(admission ? { admission } : {}),
        ...(validation ? { validation } : {}),
      } }, true);
    }
    return result({ service: "beyondquant-mcp", status: "ok", ...payload }, false);
  } catch {
    if (isWriteRequest(init)) return unknownWriteResult(init);
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "unreachable" } }, true);
  }
}

export function fetchByqMlCapabilities(backendUrl: string, fetcher: Fetcher = fetch) {
  return requestMl(backendUrl, "/v1/research/ml/capabilities", { method: "GET" }, fetcher);
}

export function fetchByqMlWorkspace(backendUrl: string, fetcher: Fetcher = fetch) {
  return requestMl(backendUrl, "/v1/research/ml/workspace", { method: "GET" }, fetcher);
}

export function fetchByqMlStudies(
  backendUrl: string,
  request: { query?: string; status?: "all" | "active" | "completed" | "failed"; limit?: number; offset?: number },
  fetcher: Fetcher = fetch,
) {
  const params = new URLSearchParams({
    query: request.query ?? "", status: request.status ?? "all",
    limit: String(request.limit ?? 20), offset: String(request.offset ?? 0),
  });
  return requestMl(backendUrl, `/v1/research/ml/studies?${params.toString()}`, { method: "GET" }, fetcher);
}

export function fetchByqMlStudy(backendUrl: string, artifactId: string, fetcher: Fetcher = fetch) {
  return requestMl(
    backendUrl, `/v1/research/ml/studies/${encodeURIComponent(artifactId)}`,
    { method: "GET" }, fetcher,
  );
}

export function fetchByqMlStrategyCreate(backendUrl: string, request: MlRequest, fetcher: Fetcher = fetch) {
  return requestMl(backendUrl, "/v1/research/ml/strategies/versions", { method: "POST", body: JSON.stringify(request) }, fetcher);
}

export function fetchByqMlStrategyApprove(backendUrl: string, request: MlRequest, fetcher: Fetcher = fetch) {
  return requestMl(backendUrl, "/v1/research/ml/strategies/approvals", { method: "POST", body: JSON.stringify(request) }, fetcher);
}

export function fetchByqMlTrainingCreate(backendUrl: string, request: MlRequest, fetcher: Fetcher = fetch) {
  return createTrainingWithReconciliation(backendUrl, request, fetcher);
}

async function createTrainingWithReconciliation(
  backendUrl: string, request: MlRequest, fetcher: Fetcher,
): Promise<ByqMlResult> {
  const registered = await requestMl(backendUrl, "/v1/research/ml/training-submissions",
    { method: "POST", body: JSON.stringify(request) }, fetcher);
  if (registered.isError) return registered;
  const registration = JSON.parse(registered.content[0]?.text ?? "{}");
  const watch = registration.receipt_watch;
  if (registration.status === "outcome_unknown" || !watch || typeof watch.watch_id !== "string"
      || typeof watch.registration_created !== "boolean") {
    return result({ service: "beyondquant-mcp", status: "outcome_unknown", retryable: false,
      idempotency_key: request.idempotency_key, training_submit_attempted: false,
      reconciliation: { status: "registration_not_confirmed", next_action: "Read byq_ml_training_get with the same idempotency_key; do not create a replacement submission." } }, false);
  }
  if (watch.state === "confirmed" && typeof watch.training_run_id === "string") {
    return fetchByqMlTrainingGet(backendUrl, watch.training_run_id, fetcher);
  }
  if (watch.state === "rejected") {
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "ml_submission_rejected" },
      receipt_watch: watch }, true);
  }
  if (!watch.registration_created || watch.state !== "awaiting_receipt") {
    return result({ service: "beyondquant-mcp", status: "outcome_unknown", retryable: false,
      idempotency_key: request.idempotency_key, receipt_watch: watch,
      reconciliation: { status: "not_confirmed", next_action: "Read byq_ml_training_get with this idempotency_key. Persistent receipt checks never resubmit training." } }, false);
  }
  const created = await requestMl(
    backendUrl, "/v1/research/ml/training-runs",
    { method: "POST", body: JSON.stringify(request) }, fetcher,
  );
  let failureStatus = "";
  try {
    const failure = JSON.parse(created.content[0]?.text ?? "{}") as { status?: string; backend?: { status?: unknown } };
    if (!created.isError && failure.status !== "outcome_unknown") return created;
    failureStatus = failure.status === "outcome_unknown" ? "outcome_unknown"
      : typeof failure.backend?.status === "string" ? failure.backend.status : "";
  } catch {
    return created;
  }
  if (!new Set(["outcome_unknown", "unreachable", "ml_research_unavailable", "invalid_response"]).has(failureStatus)) return created;
  const key = request.idempotency_key;
  if (typeof key !== "string" || key.length === 0) return created;

  const reconciled = await requestMl(
    backendUrl,
    `/v1/research/ml/training-runs/reconcile?${new URLSearchParams({ idempotency_key: key }).toString()}`,
    { method: "GET" }, fetcher, 2500,
  );
  if (!reconciled.isError) {
    try {
      const payload = JSON.parse(reconciled.content[0]?.text ?? "{}") as Record<string, unknown>;
      return result({
        ...payload,
        reconciliation: { status: "confirmed", reason: "create_response_timeout" },
      }, false);
    } catch {
      return reconciled;
    }
  }
  return result({
    service: "beyondquant-mcp",
    status: "outcome_unknown",
    operation: "ml_training_create",
    idempotency_key: key,
    retryable: false,
    reconciliation: {
      status: "not_confirmed",
      next_action: "Call byq_ml_training_get with this same idempotency_key to reconcile the exact submission. A not-yet-visible receipt remains unknown; never infer absence from a workspace list or repeat the write.",
    },
  }, false);
}

export async function fetchByqMlTrainingGet(backendUrl: string, runId: string | { idempotency_key: string }, fetcher: Fetcher = fetch) {
  if (typeof runId !== "string") {
    const key = runId.idempotency_key;
    const reconciled = await requestMl(backendUrl,
      `/v1/research/ml/training-runs/reconcile?${new URLSearchParams({ idempotency_key: key })}`,
      { method: "GET" }, fetcher, 2500);
    const payload = JSON.parse(reconciled.content[0]?.text ?? "{}");
    if (reconciled.isError && ["ml_resource_not_found", "unreachable", "ml_research_unavailable", "invalid_response"].includes(payload.backend?.status)) {
      const watched = await requestMl(backendUrl,
        `/v1/research/ml/training-submissions/reconcile?${new URLSearchParams({ idempotency_key: key })}`,
        { method: "GET" }, fetcher, 2500);
      const watchPayload = JSON.parse(watched.content[0]?.text ?? "{}");
      if (!watched.isError && watchPayload.receipt_watch?.state === "rejected") {
        return result({ service: "beyondquant-mcp", status: "error", backend: { status: "ml_submission_rejected" },
          receipt_watch: watchPayload.receipt_watch }, true);
      }
      return result({ service: "beyondquant-mcp", status: "outcome_unknown", idempotency_key: key,
        ...(!watched.isError && watchPayload.receipt_watch ? { receipt_watch: watchPayload.receipt_watch } : {}),
        retryable: false, reconciliation: { status: "not_confirmed", next_action: "Preserve this key for later exact read reconciliation; do not repeat the write." } }, false);
    }
    return reconciled;
  }
  return requestMl(backendUrl, `/v1/research/ml/training-runs/${encodeURIComponent(runId)}`, { method: "GET" }, fetcher);
}

export function fetchByqMlTrainingCancel(backendUrl: string, runId: string, fetcher: Fetcher = fetch) {
  return requestMl(backendUrl, `/v1/research/ml/training-runs/${encodeURIComponent(runId)}/cancel`, { method: "POST", body: "{}" }, fetcher);
}

export function fetchByqMlPredictionCreate(backendUrl: string, request: MlRequest, fetcher: Fetcher = fetch) {
  return requestMl(backendUrl, "/v1/research/ml/prediction-runs", { method: "POST", body: JSON.stringify(request) }, fetcher);
}

export function fetchByqMlPredictionGet(backendUrl: string, runId: string, fetcher: Fetcher = fetch) {
  return requestMl(backendUrl, `/v1/research/ml/prediction-runs/${encodeURIComponent(runId)}`, { method: "GET" }, fetcher);
}
