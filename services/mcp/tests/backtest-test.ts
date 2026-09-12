import assert from "node:assert/strict";

import {
  fetchBudgetedByqBacktestAnalysis,
  fetchByqBacktestAnalysis,
  fetchByqBacktestCancel,
  fetchByqBacktestGet,
  fetchByqBacktestLookup,
  fetchByqBacktestRun,
  fetchByqBacktestSubmit,
  fetchByqBacktestTaskCancel,
  fetchByqBacktestTaskCreate,
  fetchByqBacktestTaskExecute,
  fetchByqBacktestTaskGet,
  fetchByqBacktestTaskLookup,
  fetchByqBacktestTaskPrepare,
} from "../src/backtest.js";

const jobId = "backtest_0123456789abcdef0123456789abcdef";
const request = { task_id: "task_0123456789abcdef0123456789abcdef", idempotency_key: "backtest-mcp-1" };
const taskId = "backtesttask_0123456789abcdef0123456789abcdef";
const taskRequest = {
  task_id: request.task_id,
  strategy_version_artifact_id: "artifact_version",
  stock_pool_snapshot_id: "snapshot_pool",
  start_date: "2026-01-01",
  end_date: "2026-06-30",
  order_quantity: 100,
};

const prepared = await fetchByqBacktestTaskPrepare("http://backend:8000", taskRequest, async (url, init) => {
  assert.equal(url, "http://backend:8000/v1/research/backtest-tasks/prepare");
  assert.equal(init?.method, "POST");
  assert.doesNotMatch(String(init?.body), /\"bars\"|\"signals\"/);
  return new Response(JSON.stringify({ task: { schema_version: "backtest-task.v1", phase: "prepared" } }), { status: 200 });
});
assert.equal(prepared.isError, false);

const taskCreated = await fetchByqBacktestTaskCreate(
  "http://backend:8000",
  { ...taskRequest, idempotency_key: "task-create-1" },
  async (url, init) => {
    assert.equal(url, "http://backend:8000/v1/research/backtest-tasks");
    assert.equal(init?.method, "POST");
    assert.doesNotMatch(String(init?.body), /\"bars\"|\"signals\"/);
    return new Response(JSON.stringify({ task: { backtest_task_id: taskId, phase: "waiting_for_data" } }), { status: 202 });
  },
);
assert.equal(taskCreated.isError, false);

for (const [call, suffix, method] of [
  [fetchByqBacktestTaskGet, "", "GET"],
  [fetchByqBacktestTaskExecute, "/execute", "POST"],
  [fetchByqBacktestTaskCancel, "/cancel", "POST"],
] as const) {
  const response = await call("http://backend:8000", taskId, async (url, init) => {
    assert.equal(url, `http://backend:8000/v1/research/backtest-tasks/${taskId}${suffix}`);
    assert.equal(init?.method, method);
    return new Response(JSON.stringify({ task: { backtest_task_id: taskId, phase: "completed" } }), { status: 200 });
  });
  assert.equal(response.isError, false);
}

const submitted = await fetchByqBacktestSubmit(
  "http://backend:8000",
  request,
  async (url, init) => {
    assert.equal(url, "http://backend:8000/v1/research/backtests");
    assert.equal(init?.method, "POST");
    assert.doesNotMatch(String(init?.body), /password|secret|token/i);
    return new Response(JSON.stringify({ job: { job_id: jobId, status: "queued" } }), { status: 202 });
  },
);
assert.equal(submitted.isError, false);
assert.match(submitted.content[0].text, /queued/);

const fetched = await fetchByqBacktestGet("http://backend:8000", jobId, async (url, init) => {
  assert.equal(url, `http://backend:8000/v1/research/backtests/${jobId}/summary`);
  assert.equal(init?.method, "GET");
  return new Response(JSON.stringify({ job: {
    job_id: jobId,
    status: "completed",
    result_artifact_id: "artifact_result",
    summary: { total_return: 0.12 },
  } }), { status: 200 });
});
assert.equal(fetched.isError, false);
assert.match(fetched.content[0].text, /completed/);
assert.match(fetched.content[0].text, /artifact_result/);
assert.doesNotMatch(fetched.content[0].text, /input_manifest|bars|signals|result_reference|object_id/);

const analysis = await fetchByqBacktestAnalysis(
  "http://backend:8000",
  jobId,
  { section: "blocked_trades", limit: 25, offset: 50 },
  async (url, init) => {
    assert.equal(
      url,
      `http://backend:8000/v1/research/backtests/${jobId}/analysis?section=blocked_trades&limit=25&offset=50`,
    );
    assert.equal(init?.method, "GET");
    return new Response(JSON.stringify({ analysis: { schema_version: "backtest-analysis.v1" } }), { status: 200 });
  },
);
assert.equal(analysis.isError, false);
assert.doesNotMatch(analysis.content[0].text, /object_reference|object_id/);

let boundedBackendCalls = 0;
const lastAllowed = await fetchBudgetedByqBacktestAnalysis(
  "http://backend:8000",
  jobId,
  { section: "daily_returns", limit: 100, offset: 200 },
  { allowed: true, limit: 6, remaining: 0 },
  async () => {
    boundedBackendCalls += 1;
    return new Response(JSON.stringify({ analysis: {
      schema_version: "backtest-analysis.v1",
      section: "daily_returns",
      page: { total: 241, limit: 100, offset: 200, has_more: false, rows: [] },
    } }), { status: 200 });
  },
);
assert.equal(lastAllowed.isError, false);
assert.equal(boundedBackendCalls, 1);
assert.deepEqual(JSON.parse(lastAllowed.content[0].text).analysis_page_budget, {
  status: "exhausted",
  call_limit: 6,
  remaining_calls: 0,
  backend_accessed: true,
  must_answer_from_collected_evidence: true,
});

const exhausted = await fetchBudgetedByqBacktestAnalysis(
  "http://backend:8000",
  jobId,
  { section: "equity_curve", limit: 100, offset: 0 },
  { allowed: false, limit: 6, remaining: 0 },
  async () => {
    boundedBackendCalls += 1;
    throw new Error("budget exhaustion must not access Backend");
  },
);
assert.equal(exhausted.isError, false);
assert.equal(boundedBackendCalls, 1);
assert.deepEqual(JSON.parse(exhausted.content[0].text), {
  service: "beyondquant-mcp",
  status: "bounded",
  analysis_page_budget: {
    status: "exhausted",
    call_limit: 6,
    remaining_calls: 0,
    backend_accessed: false,
    must_answer_from_collected_evidence: true,
    code: "analysis_page_budget_exceeded",
    retryable: false,
  },
});

const run = await fetchByqBacktestRun("http://backend:8000", jobId, async (url, init) => {
  assert.equal(url, `http://backend:8000/v1/research/backtests/${jobId}/run`);
  assert.equal(init?.method, "POST");
  return new Response(JSON.stringify({ job: { job_id: jobId, status: "completed" } }), { status: 200 });
});
assert.equal(run.isError, false);

const cancelled = await fetchByqBacktestCancel("http://backend:8000", jobId, async (url, init) => {
  assert.equal(url, `http://backend:8000/v1/research/backtests/${jobId}/cancel`);
  assert.equal(init?.method, "POST");
  return new Response(JSON.stringify({ job: { job_id: jobId, status: "cancelled" } }), { status: 200 });
});
assert.equal(cancelled.isError, false);

const invalid = await fetchByqBacktestGet("http://backend:8000", jobId, async () => {
  return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
});
assert.equal(invalid.isError, true);
assert.match(invalid.content[0].text, /backtest_not_found/);

console.log("Backtest MCP translation PASS: task facade, legacy transport and safe error mapping");


for (const status of ["confirmed", "outcome_unknown"] as const) {
  let calls = 0;
  const key = "original/key &中文";
  const reply = await fetchByqBacktestLookup("http://backend:8000", {
    task_id: request.task_id, idempotency_key: key,
  }, async (url, init) => {
    calls++;
    const target = new URL(url);
    assert.equal(target.pathname, "/v1/research/backtests/reconcile");
    assert.equal(target.searchParams.get("task_id"), request.task_id);
    assert.equal(target.searchParams.get("idempotency_key"), key);
    assert.equal(init?.method, "GET");
    assert.equal(init?.body, undefined);
    return new Response(JSON.stringify({ schema_version: "backtest-submission-reconciliation.v1",
      task_id: request.task_id, idempotency_key: key, status,
      ...(status === "confirmed" ? { job: { job_id: jobId, task_id: request.task_id, status: "queued" } } : {}),
    }));
  });
  assert.equal(calls, 1);
  assert.equal(reply.isError, false);
  assert.equal(JSON.parse(reply.content[0].text).status, status);
  if (status === "outcome_unknown") assert.equal(JSON.parse(reply.content[0].text).retryable, false);
}
for (const selector of [{}, { job_id: " " }, { task_id: request.task_id }, { idempotency_key: "key" },
  { job_id: jobId, task_id: request.task_id }, { job_id: jobId, idempotency_key: "key" },
  { task_id: request.task_id, idempotency_key: "x".repeat(129) }]) {
  const reply = await fetchByqBacktestLookup("http://backend:8000", selector, async () => {
    assert.fail("invalid identity must not contact Backend");
  });
  assert.equal(reply.isError, true);
}
for (const failure of ["transport", "json", "wrong_key", "wrong_task", "missing_job", "wrong_job_task", "http"] as const) {
  let calls = 0;
  const reply = await fetchByqBacktestLookup("http://backend:8000", request, async () => {
    calls++;
    if (failure === "transport") throw new Error("synthetic private transport error");
    if (failure === "json") return new Response("not JSON");
    return new Response(JSON.stringify({ schema_version: "backtest-submission-reconciliation.v1", status: "confirmed",
      task_id: failure === "wrong_task" ? "other" : request.task_id,
      idempotency_key: failure === "wrong_key" ? "other" : request.idempotency_key,
      ...(failure === "missing_job" ? {} : { job: { job_id: jobId, task_id: failure === "wrong_job_task" ? "other" : request.task_id } }),
    }), { status: failure === "http" ? 503 : 200 });
  });
  assert.equal(calls, 1);
  assert.equal(reply.isError, true);
  assert.doesNotMatch(reply.content[0].text, /private transport/);
}
const legacyLookup = await fetchByqBacktestLookup("http://backend:8000", { job_id: jobId }, async (url, init) => {
  assert.equal(url, `http://backend:8000/v1/research/backtests/${jobId}/summary`);
  assert.equal(init?.method, "GET");
  return new Response(JSON.stringify({ job: { job_id: jobId } }));
});
assert.equal(legacyLookup.isError, false);
console.log("Backtest original receipt lookup PASS: exact identity, bounded reads, unknown safety and ID compatibility");


const signalJobId = "signaljob_0123456789abcdef0123456789abcdef";
for (const status of ["confirmed", "outcome_unknown"] as const) {
  let calls = 0;
  const key = "task/key &中文";
  const response = await fetchByqBacktestTaskLookup("http://backend:8000", { task_id: request.task_id, idempotency_key: key }, async (url, init) => {
    calls++;
    const target = new URL(url);
    assert.equal(target.pathname, "/v1/research/backtest-tasks/reconcile");
    assert.equal(target.searchParams.get("task_id"), request.task_id);
    assert.equal(target.searchParams.get("idempotency_key"), key);
    assert.equal(init?.method, "GET");
    assert.equal(init?.body, undefined);
    return new Response(JSON.stringify({ schema_version: "backtest-task-submission-reconciliation.v1",
      status, task_id: request.task_id, idempotency_key: key, private_probe: "must not leak",
      ...(status === "confirmed" ? { receipt: { backtest_task_id: taskId, signal_producer_job_id: signalJobId,
        signal_status: "waiting_for_data", preparation: "must not leak" } } : {}),
    }));
  });
  assert.equal(calls, 1);
  assert.equal(response.isError, false);
  assert.equal(JSON.parse(response.content[0].text).status, status);
  assert.doesNotMatch(response.content[0].text, /must not leak|private_probe|preparation/);
  if (status === "outcome_unknown") assert.equal(JSON.parse(response.content[0].text).retryable, false);
}
for (const selector of [{}, { backtest_task_id: "bad" }, { task_id: request.task_id }, { idempotency_key: "key" },
  { backtest_task_id: taskId, task_id: request.task_id }, { backtest_task_id: taskId, idempotency_key: "key" },
  { task_id: request.task_id, idempotency_key: "x".repeat(129) }]) {
  const response = await fetchByqBacktestTaskLookup("http://backend:8000", selector, async () => assert.fail("invalid identity called Backend"));
  assert.equal(response.isError, true);
}
for (const failure of ["transport", "json", "key", "task", "mapping", "status", "missing", "http"] as const) {
  let calls = 0;
  const response = await fetchByqBacktestTaskLookup("http://backend:8000", request, async () => {
    calls++;
    if (failure === "transport") throw new Error("private synthetic failure");
    if (failure === "json") return new Response("not json");
    return new Response(JSON.stringify({ schema_version: "backtest-task-submission-reconciliation.v1", status: "confirmed",
      task_id: failure === "task" ? "other" : request.task_id,
      idempotency_key: failure === "key" ? "other" : request.idempotency_key,
      ...(failure === "missing" ? {} : { receipt: { backtest_task_id: failure === "mapping" ? "backtesttask_ml_0123456789abcdef0123456789abcdef" : taskId,
        signal_producer_job_id: signalJobId, signal_status: failure === "status" ? "invented" : "completed" } }),
    }), { status: failure === "http" ? 503 : 200 });
  });
  assert.equal(calls, 1);
  assert.equal(response.isError, true);
  assert.doesNotMatch(response.content[0].text, /private synthetic/);
}
for (const id of [taskId, "backtesttask_ml_0123456789abcdef0123456789abcdef"]) {
  const response = await fetchByqBacktestTaskLookup("http://backend:8000", { backtest_task_id: id }, async (url, init) => {
    assert.equal(url, `http://backend:8000/v1/research/backtest-tasks/${id}`);
    assert.equal(init?.method, "GET");
    return new Response(JSON.stringify({ task: { backtest_task_id: id } }));
  });
  assert.equal(response.isError, false);
}
console.log("Derived backtest task receipt PASS: original key, closed identity projection, unknown safety and ML ID compatibility");


for (const [detail, expected] of [
  ['strategy version is not approved for execution', /materialized strategy approval/],
  ['start_date must be YYYY-MM-DD', /start_date/],
] as const) {
  const invalid = await fetchByqBacktestTaskPrepare('http://backend', taskRequest,
    async () => new Response(JSON.stringify({detail}), {status: 422}));
  assert.equal(invalid.isError, true);
  assert.match(JSON.parse(invalid.content[0].text).backend.validation.message, expected);
}
const { safeRequestValidation } = await import('../src/request-validation.js');
assert.equal(safeRequestValidation({detail: 'password=secret-fixture /home/private'}), undefined);
assert.equal(safeRequestValidation({detail: 'constructor'}), undefined);
assert.match(safeRequestValidation({detail: 'input_snapshot.sources must be a non-empty list'})!.message, /request_fingerprint/);
