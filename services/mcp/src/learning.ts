import { isWriteRequest, unknownWriteResult } from "./write-outcome.js";

const BACKEND_TIMEOUT_MS = 8000;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

export type LearningContext = {
  workspace_id?: string;
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
    ["workspace_id", "x-byq-workspace-id"],
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
  const unknown = () => {
    const base = unknownWriteResult(init);
    const value = JSON.parse(base.content[0].text);
    let body:Record<string,unknown> = {};
    try { body = JSON.parse(String(init.body)); } catch {}
    const match = path.match(/^\/v1\/learning\/runs\/(learning_run_[0-9a-f]{32})\/iterations$/);
    const tool = path === '/v1/learning/runs' ? 'byq_learning_run_get' : path === '/v1/learning/signals' ? 'byq_evaluation_signal_get'
      : path === '/v1/learning/lessons' ? 'byq_lesson_get' : match ? 'byq_learning_iteration_list' : null;
    if (tool && typeof body.idempotency_key === 'string' && /^[A-Za-z0-9_.:-]{1,128}$/.test(body.idempotency_key)
        && (match || (typeof body.task_id === 'string' && /^task_[0-9a-f]{32}$/.test(body.task_id)))) {
      value.reconciliation = {tool, arguments:{...(match ? {run_id:match[1]} : {task_id:body.task_id}),idempotency_key:body.idempotency_key}};
    }
    return result(value,false);
  };
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
    if (isWriteRequest(init) && response.status >= 500) return unknown();
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      if (isWriteRequest(init) && response.ok) return unknown();
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
      if (isWriteRequest(init) && response.ok) return unknown();
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (!response.ok) {
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: errorStatus(response.status), http_status: response.status } }, true);
    }
    const value = payload as Record<string,any>;
    const body = init.body ? JSON.parse(String(init.body)) : {};
    const route = path.match(/^\/v1\/learning\/(runs|signals|lessons)(?:\/([^/?]+))?$/);
    const shapes:Record<string,[string,string,string]> = {runs:['run','learning_run_id','learning_run'],signals:['signal','signal_id','evaluation_signal'],lessons:['lesson','lesson_id','lesson']};
    if (route) {
      const [field,id,prefix] = shapes[route[1]];
      const valid = new RegExp('^'+prefix+'_[0-9a-f]{32}$').test(value[field]?.[id] ?? '')
        && (!route[2] || value[field][id] === decodeURIComponent(route[2]))
        && (!isWriteRequest(init) || value[field].task_id === body.task_id);
      if (!valid) return isWriteRequest(init) ? unknown() : result({status:'error',backend:{status:'invalid_response'}},true);
    }
    const iterationPath = path.match(/^\/v1\/learning\/runs\/([^/?]+)\/iterations$/);
    if (iterationPath && isWriteRequest(init)) {
      const valid = /^learning_iteration_[0-9a-f]{32}$/.test(value.iteration?.iteration_id ?? '')
        && value.iteration.learning_run_id === decodeURIComponent(iterationPath[1])
        && value.run?.learning_run_id === decodeURIComponent(iterationPath[1]);
      if (!valid) return unknown();
    }
    if (path.startsWith('/v1/learning/receipts?')) {
      const query = new URLSearchParams(path.split('?')[1]);
      const kind = query.get('kind')!;
      const fields:Record<string,[string,string]> = {run:['learning_run_id','learning_run'],signal:['signal_id','evaluation_signal'],lesson:['lesson_id','lesson'],iteration:['iteration_id','learning_iteration']};
      const [id,prefix] = fields[kind];
      const missing = value.state === 'not_found' && Object.keys(value).length === 1;
      const valid = value.state === 'confirmed' && new RegExp('^'+prefix+'_[0-9a-f]{32}$').test(value[kind]?.[id] ?? '')
        && (kind === 'iteration' ? value.iteration.learning_run_id === query.get('run_id') && value.run?.learning_run_id === query.get('run_id')
          : value[kind].task_id === query.get('task_id'));
      if (!missing && !valid) return result({status:'error',backend:{status:'invalid_response'}},true);
    }
    return result({ service: "beyondquant-mcp", status: "ok", ...payload }, false);
  } catch {
    if (isWriteRequest(init)) return unknown();
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

export function fetchByqLearningReceipt(backendUrl:string, kind:'run'|'signal'|'lesson'|'iteration', args:{task_id?:string;run_id?:string;idempotency_key:string}, context:LearningContext, fetcher:Fetcher=fetch) {
  const query = new URLSearchParams({kind,idempotency_key:args.idempotency_key});
  if(args.task_id) query.set('task_id',args.task_id);
  if(args.run_id) query.set('run_id',args.run_id);
  return requestLearning(backendUrl,'/v1/learning/receipts?'+query,{method:'GET'},context,fetcher);
}
