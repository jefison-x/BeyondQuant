import assert from "node:assert/strict";

import {
  fetchByqBacktestAnalysis,
  fetchByqBacktestCancel,
  fetchByqBacktestGet,
  fetchByqBacktestRun,
  fetchByqBacktestSubmit,
  fetchByqBacktestTaskCancel,
  fetchByqBacktestTaskCreate,
  fetchByqBacktestTaskExecute,
  fetchByqBacktestTaskGet,
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
  assert.equal(url, `http://backend:8000/v1/research/backtests/${jobId}`);
  assert.equal(init?.method, "GET");
  return new Response(JSON.stringify({ job: { job_id: jobId, status: "completed" } }), { status: 200 });
});
assert.equal(fetched.isError, false);
assert.match(fetched.content[0].text, /completed/);

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
