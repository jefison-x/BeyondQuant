import { safeRequestValidation } from "./request-validation.js";
import type { PageBudgetDecision } from "./page-budget.js";

import { isWriteRequest, unknownWriteResult } from "./write-outcome.js";

const BACKEND_TIMEOUT_MS = 8000;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

export type BacktestRequest = Record<string, unknown>;

export type ByqBacktestResult = {
  content: Array<{ type: "text"; text: string }>;
  isError: boolean;
};

export type BacktestAnalysisBudget = {
  status: "available" | "exhausted";
  call_limit: number;
  remaining_calls: number;
  backend_accessed: boolean;
  must_answer_from_collected_evidence: boolean;
};

function result(payload: unknown, isError: boolean): ByqBacktestResult {
  return { content: [{ type: "text", text: JSON.stringify(payload) }], isError };
}

function errorStatus(status: number): string {
  if (status === 404) return "backtest_not_found";
  if (status === 409) return "backtest_conflict";
  if (status === 422) return "backtest_request_invalid";
  return "backtest_unavailable";
}

function unknownBacktestWrite(path:string,init:RequestInit):ByqBacktestResult {
  const response = unknownWriteResult(init), value = JSON.parse(response.content[0].text);
  let request:any = {};try {request=JSON.parse(String(init.body ?? '{}'));} catch { /* keep original unknown */ }
  const job=path.match(/^\/v1\/research\/backtests\/(backtest_[0-9a-f]{32})\/(?:run|cancel)$/);
  const task=path.match(/^\/v1\/research\/backtest-tasks\/(backtesttask_(?:ml_)?[0-9a-f]{32})\/(?:execute|cancel)$/);
  if(job) value.reconciliation={tool:'byq_backtest_get',arguments:{job_id:job[1]}};
  else if(task) value.reconciliation={tool:'byq_backtest_task_get',arguments:{backtest_task_id:task[1]}};
  else if(['/v1/research/backtests','/v1/research/backtest-tasks'].includes(path)
    && /^task_[0-9a-f]{32}$/.test(request.task_id ?? '') && typeof value.idempotency_key === 'string') {
    value.reconciliation={tool:path.endsWith('/backtests')?'byq_backtest_get':'byq_backtest_task_get',
      arguments:{task_id:request.task_id,idempotency_key:value.idempotency_key}};
  }
  return result(value,false);
}

function exactBacktestResponse(path:string,value:Record<string,any>):boolean {
  const job=path.match(/^\/v1\/research\/backtests\/(backtest_[0-9a-f]{32})\/(summary|analysis|run|cancel)(?:\?|$)/);
  if(job) return job[2] === 'analysis' ? value.job_id === job[1] && value.analysis?.schema_version === 'backtest-analysis.v1'
    : value.job?.job_id === job[1];
  const task=path.match(/^\/v1\/research\/backtest-tasks\/(backtesttask_(?:ml_)?[0-9a-f]{32})(?:\/(?:execute|cancel))?$/);
  if(task) return value.task?.backtest_task_id === task[1];
  const snapshot=path.match(/^\/v1\/research\/signal-snapshots\/(artifact_[0-9a-f]{32})\/summary$/);
  if(snapshot) return value.summary?.schema_version === 'signal-snapshot-summary.v1'
    && value.summary?.artifact?.artifact_id === snapshot[1]
    && value.summary?.artifact?.kind === 'signal_snapshot';
  return true;
}

async function requestBacktest(
  backendUrl: string,
  path: string,
  init: RequestInit,
  fetcher: Fetcher,
): Promise<ByqBacktestResult> {
  try {
    const response = await fetcher(`${backendUrl}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init.headers ?? {}) },
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    if (isWriteRequest(init) && response.status >= 500) return unknownBacktestWrite(path,init);
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      if (isWriteRequest(init) && response.ok) return unknownBacktestWrite(path,init);
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
      if (isWriteRequest(init) && response.ok) return unknownBacktestWrite(path,init);
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (!response.ok) {
      return result(
        { service: "beyondquant-mcp", status: "error", backend: { status: errorStatus(response.status), http_status: response.status,
          ...(response.status === 422 && safeRequestValidation(payload)
            ? { validation: safeRequestValidation(payload) } : {}) } },
        true,
      );
    }
    if(!exactBacktestResponse(path,payload as Record<string,any>)) return isWriteRequest(init)
      ? unknownBacktestWrite(path,init) : result({service:'beyondquant-mcp',status:'error',backend:{status:'invalid_response'}},true);
    return result({ service: "beyondquant-mcp", status: "ok", ...payload }, false);
  } catch {
    if (isWriteRequest(init)) return unknownBacktestWrite(path,init);
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "unreachable" } }, true);
  }
}

export function fetchByqBacktestSubmit(
  backendUrl: string,
  request: BacktestRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  return requestBacktest(
    backendUrl,
    "/v1/research/backtests",
    { method: "POST", body: JSON.stringify(request) },
    fetcher,
  );
}

export function fetchByqBacktestGet(
  backendUrl: string,
  jobId: string,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  return requestBacktest(
    backendUrl,
    `/v1/research/backtests/${encodeURIComponent(jobId)}/summary`,
    { method: "GET" },
    fetcher,
  );
}

export function fetchByqBacktestAnalysis(
  backendUrl: string,
  jobId: string,
  options: { section: string; limit: number; offset: number },
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  const query = new URLSearchParams({
    section: options.section,
    limit: String(options.limit),
    offset: String(options.offset),
  });
  return requestBacktest(
    backendUrl,
    `/v1/research/backtests/${encodeURIComponent(jobId)}/analysis?${query.toString()}`,
    { method: "GET" },
    fetcher,
  );
}

function analysisBudgetPayload(
  decision: PageBudgetDecision,
  backendAccessed: boolean,
): BacktestAnalysisBudget {
  return {
    status: decision.remaining > 0 ? "available" : "exhausted",
    call_limit: decision.limit,
    remaining_calls: decision.remaining,
    backend_accessed: backendAccessed,
    must_answer_from_collected_evidence: decision.remaining === 0,
  };
}

export async function fetchBudgetedByqBacktestAnalysis(
  backendUrl: string,
  jobId: string,
  options: { section: string; limit: number; offset: number },
  decision: PageBudgetDecision,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  if (!decision.allowed) {
    return result({
      service: "beyondquant-mcp",
      status: "bounded",
      analysis_page_budget: {
        ...analysisBudgetPayload(decision, false),
        code: "analysis_page_budget_exceeded",
        retryable: false,
      },
    }, false);
  }

  const fetched = await fetchByqBacktestAnalysis(
    backendUrl, jobId, options, fetcher,
  );
  if (fetched.isError) return fetched;
  const text = fetched.content[0]?.text;
  if (typeof text !== "string") return fetched;
  try {
    const payload = JSON.parse(text) as unknown;
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) return fetched;
    return result({
      ...(payload as Record<string, unknown>),
      analysis_page_budget: analysisBudgetPayload(decision, true),
    }, false);
  } catch {
    return fetched;
  }
}

export function fetchByqSignalSnapshotGet(
  backendUrl: string,
  artifactId: string,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  return requestBacktest(backendUrl, `/v1/research/signal-snapshots/${encodeURIComponent(artifactId)}/summary`, { method: "GET" }, fetcher);
}

export function fetchByqBacktestRun(
  backendUrl: string,
  jobId: string,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  return requestBacktest(backendUrl, `/v1/research/backtests/${encodeURIComponent(jobId)}/run`, { method: "POST", body: "{}" }, fetcher);
}

export function fetchByqBacktestCancel(
  backendUrl: string,
  jobId: string,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  return requestBacktest(backendUrl, `/v1/research/backtests/${encodeURIComponent(jobId)}/cancel`, { method: "POST", body: "{}" }, fetcher);
}

export function fetchByqBacktestTaskPrepare(
  backendUrl: string,
  request: BacktestRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  return requestBacktest(
    backendUrl,
    "/v1/research/backtest-tasks/prepare",
    { method: "POST", body: JSON.stringify(request) },
    fetcher,
  );
}

export function fetchByqBacktestTaskCreate(
  backendUrl: string,
  request: BacktestRequest,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  return requestBacktest(
    backendUrl,
    "/v1/research/backtest-tasks",
    { method: "POST", body: JSON.stringify(request) },
    fetcher,
  );
}

const BACKTEST_EXECUTION_NOTE =
  "Business next_action/actions describe task readiness. This query grants no execution permission; follow the current trusted Root instruction and obtain required authorization before any allowed action.";

// Fixed bounded explanations selected only from a legal projected phase or from
// the validated approval_required blocker code. A Map is an own-entry lookup, so
// hostile keys such as __proto__, constructor or toString are never treated as
// facts. Arbitrary blocker messages or error detail are never copied into
// executable wording.
const BACKTEST_PHASE_NOTES = new Map<string, string>([
  ["prepared", "Task is prepared. Business next_action describes readiness; this query grants no execution permission."],
  ["waiting_for_data", "Task is waiting for existing market-input preparation; this query does not start or resume that work."],
  ["producing_signals", "Task is producing signals from existing inputs; this query does not advance or resume that work."],
  ["ready_to_execute", "Business state is ready for an allowed execution action, but this query grants no execution permission."],
  ["queued", "Task is queued for execution; this query does not grant or perform execution."],
  ["running", "Task is running. Report its current state; this query does not grant or perform execution."],
  ["completed", "This reports a confirmed business result; it does not assert completion of the broader ResearchTask."],
  ["failed", "Task reports failure. Review the existing business result; this query does not resubmit or retry work."],
  ["cancelled", "Task is cancelled. A new task requires its own separate authorization, not this query."],
]);

function backtestContinuationNote(task: Record<string, unknown>): string {
  const blockers = Array.isArray(task.blockers) ? task.blockers : [];
  if (blockers.some(entry => entry !== null && typeof entry === "object"
    && (entry as Record<string, unknown>).code === "approval_required")) {
    return "An approval is required before execution. Request that human approval outside this query; this query does not grant it.";
  }
  const phase = typeof task.phase === "string" ? task.phase : undefined;
  const note = phase === undefined ? undefined : BACKTEST_PHASE_NOTES.get(phase);
  return typeof note === "string" ? note
    : "This query alone is insufficient to determine a safe next step.";
}

// Notes attach only to a successful exact backtest_task_id GET whose parsed
// task identity matches the requested id. The success test uses the real
// response path and parsed identity, never the spread top-level status.
function withBacktestTaskNotes(response: ByqBacktestResult, taskId: string): ByqBacktestResult {
  if (response.isError) return response;
  const text = response.content[0]?.text;
  if (typeof text !== "string") return response;
  let payload: unknown;
  try { payload = JSON.parse(text); } catch { return response; }
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) return response;
  const record = payload as Record<string, unknown>;
  const task = record.task;
  if (task === null || typeof task !== "object" || Array.isArray(task)) return response;
  const taskRecord = task as Record<string, unknown>;
  if (taskRecord.backtest_task_id !== taskId) return response;
  return result({
    ...record,
    execution_note: BACKTEST_EXECUTION_NOTE,
    continuation_note: backtestContinuationNote(taskRecord),
  }, false);
}

export async function fetchByqBacktestTaskGet(
  backendUrl: string,
  taskId: string,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  const response = await requestBacktest(
    backendUrl,
    `/v1/research/backtest-tasks/${encodeURIComponent(taskId)}`,
    { method: "GET" },
    fetcher,
  );
  return withBacktestTaskNotes(response, taskId);
}

export function fetchByqBacktestTaskExecute(
  backendUrl: string,
  taskId: string,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  return requestBacktest(
    backendUrl,
    `/v1/research/backtest-tasks/${encodeURIComponent(taskId)}/execute`,
    { method: "POST", body: "{}" },
    fetcher,
  );
}

export function fetchByqBacktestTaskCancel(
  backendUrl: string,
  taskId: string,
  agentApprovalId: string,
  fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  return requestBacktest(
    backendUrl,
    `/v1/research/backtest-tasks/${encodeURIComponent(taskId)}/cancel`,
    { method: "POST", body: JSON.stringify({ agent_approval_id: agentApprovalId }) },
    fetcher,
  );
}


export type BacktestLookup = { job_id?: string; task_id?: string; idempotency_key?: string };

export async function fetchByqBacktestLookup(
  backendUrl: string, request: BacktestLookup, fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  const byId = request.job_id !== undefined;
  if (byId ? (!request.job_id?.trim() || request.task_id !== undefined || request.idempotency_key !== undefined)
      : (!request.task_id?.trim() || !request.idempotency_key?.trim() || request.idempotency_key.trim().length > 128)) {
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "backtest_request_invalid" } }, true);
  }
  if (byId) return fetchByqBacktestGet(backendUrl, request.job_id!, fetcher);
  const query = new URLSearchParams({ task_id: request.task_id!, idempotency_key: request.idempotency_key! });
  const response = await requestBacktest(backendUrl, `/v1/research/backtests/reconcile?${query}`, { method: "GET" }, fetcher);
  if (response.isError) return response;
  const payload = JSON.parse(response.content[0]?.text ?? "{}");
  if (payload.schema_version !== "backtest-submission-reconciliation.v1"
      || payload.task_id !== request.task_id!.trim() || payload.idempotency_key !== request.idempotency_key!.trim()
      || !["confirmed", "outcome_unknown"].includes(payload.status)
      || (payload.status === "confirmed" && (!payload.job || Array.isArray(payload.job)
        || typeof payload.job.job_id !== "string" || !/^backtest_[0-9a-f]{32}$/.test(payload.job.job_id)
        || payload.job.task_id !== payload.task_id))) {
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
  }
  if (payload.status === "outcome_unknown") return result({ service: "beyondquant-mcp",
    schema_version: payload.schema_version, task_id: payload.task_id, idempotency_key: payload.idempotency_key,
    status: "outcome_unknown", retryable: false,
    next_action: "Preserve the original task and request key. Query this identity within the task budget; do not repeat submission or infer absence from a list.",
  }, false);
  return response;
}


export type BacktestTaskLookup = { backtest_task_id?: string; task_id?: string; idempotency_key?: string };

export async function fetchByqBacktestTaskLookup(
  backendUrl: string, request: BacktestTaskLookup, fetcher: Fetcher = fetch,
): Promise<ByqBacktestResult> {
  const byId = request.backtest_task_id !== undefined;
  if (byId ? (!/^backtesttask_(?:ml_)?[0-9a-f]{32}$/.test(request.backtest_task_id!)
        || request.task_id !== undefined || request.idempotency_key !== undefined)
      : (!request.task_id?.trim() || !request.idempotency_key?.trim() || request.idempotency_key.trim().length > 128)) {
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "backtest_request_invalid" } }, true);
  }
  if (byId) return fetchByqBacktestTaskGet(backendUrl, request.backtest_task_id!, fetcher);
  const query = new URLSearchParams({ task_id: request.task_id!, idempotency_key: request.idempotency_key! });
  const response = await requestBacktest(backendUrl, `/v1/research/backtest-tasks/reconcile?${query}`, { method: "GET" }, fetcher);
  if (response.isError) return response;
  const payload = JSON.parse(response.content[0]?.text ?? "{}");
  const receipt = payload.receipt;
  if (payload.schema_version !== "backtest-task-submission-reconciliation.v1"
      || payload.task_id !== request.task_id!.trim() || payload.idempotency_key !== request.idempotency_key!.trim()
      || !["confirmed", "outcome_unknown"].includes(payload.status)
      || (payload.status === "confirmed" && (!receipt || Array.isArray(receipt)
        || typeof receipt.signal_producer_job_id !== "string" || !/^signaljob_[0-9a-f]{32}$/.test(receipt.signal_producer_job_id)
        || receipt.backtest_task_id !== receipt.signal_producer_job_id.replace("signaljob_", "backtesttask_")
        || !["waiting_for_data", "queued", "running", "completed", "failed", "cancelled"].includes(receipt.signal_status)))) {
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
  }
  return result({ service: "beyondquant-mcp", schema_version: payload.schema_version,
    task_id: payload.task_id, idempotency_key: payload.idempotency_key, status: payload.status,
    ...(payload.status === "confirmed" ? { receipt: {
      backtest_task_id: receipt.backtest_task_id, signal_producer_job_id: receipt.signal_producer_job_id,
      signal_status: receipt.signal_status,
    }, next_action: "Read the recovered backtest_task_id for current state; confirmation grants no execution permission." }
    : { retryable: false, next_action: "Preserve the original task and key. Query this identity within the task budget; do not repeat submission or infer absence from a list." }),
  }, false);
}
