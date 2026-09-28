import assert from "node:assert/strict";

import {
  fetchByqOptimizationCancel,
  fetchByqOptimizationGet,
  fetchByqOptimizationSubmit,
} from "../src/optimization-research.js";

const taskId = "task_" + "a".repeat(32);
const jobId = "optimizationjob_" + "b".repeat(32);
const artifactId = "artifact_" + "c".repeat(32);
const request = {
  task_id: taskId,
  trace_id: "trace-optimization-mcp",
  idempotency_key: "optimization-mcp-1",
  objective: "sharpe_ratio" as const,
  candidates: [
    { backtest_job_id: "backtest_" + "d".repeat(32), parameters: { window: 10 } },
    { backtest_job_id: "backtest_" + "e".repeat(32), parameters: { window: 20 } },
  ],
};

function envelope(status: string, resultRef: string | null = null) {
  return {
    job: {
      job_id: jobId, task_id: taskId, type: "OPTIMIZATION", status,
      candidate_count: 2, result_artifact_id: resultRef,
    },
    business_job: { job_id: jobId, type: "OPTIMIZATION", status },
  };
}

const submitted = await fetchByqOptimizationSubmit("http://backend:8000", request, async (url, init) => {
  assert.equal(url, "http://backend:8000/v1/research/optimization-jobs");
  assert.equal(init?.method, "POST");
  const body = JSON.parse(String(init?.body));
  assert.equal(body.trace_id, request.trace_id);
  assert.deepEqual(body.candidates, request.candidates);
  return Response.json(envelope("QUEUED"), { status: 202 });
});
assert.equal(submitted.isError, false);
assert.match(submitted.content[0].text, /optimizationjob_/);

let calls = 0;
const unknown = await fetchByqOptimizationSubmit("http://backend:8000", request, async () => {
  calls += 1;
  throw new Error("private transport detail");
});
const unknownBody = JSON.parse(unknown.content[0].text);
assert.equal(calls, 1);
assert.equal(unknownBody.status, "outcome_unknown");
assert.equal(unknownBody.retryable, false);
assert.deepEqual(unknownBody.reconciliation, {
  tool: "byq_optimization_get",
  arguments: { task_id: taskId, idempotency_key: request.idempotency_key },
});
assert.doesNotMatch(unknown.content[0].text, /private transport detail/);

const reconciled = await fetchByqOptimizationGet("http://backend:8000", {
  task_id: taskId, idempotency_key: request.idempotency_key,
}, async (url, init) => {
  assert.match(url, /\/v1\/research\/optimization-jobs\?task_id=/);
  assert.match(url, /idempotency_key=optimization-mcp-1/);
  assert.equal(init?.method, "GET");
  return Response.json(envelope("SUCCEEDED", artifactId));
});
assert.equal(reconciled.isError, false);

const cancelled = await fetchByqOptimizationCancel("http://backend:8000", jobId, async (url, init) => {
  assert.equal(url, `http://backend:8000/v1/research/optimization-jobs/${jobId}/cancel`);
  assert.equal(init?.method, "POST");
  return Response.json(envelope("CANCELLED"));
});
assert.equal(cancelled.isError, false);

const cancelUnknown = await fetchByqOptimizationCancel("http://backend:8000", jobId, async () => {
  throw new Error("private cancel transport");
});
assert.deepEqual(JSON.parse(cancelUnknown.content[0].text).reconciliation, {
  tool: "byq_optimization_get", arguments: { job_id: jobId },
});

let unexpectedRequest = false;
const invalid = await fetchByqOptimizationGet("http://backend:8000", { task_id: taskId }, async () => {
  unexpectedRequest = true;
  throw new Error("must not fetch");
});
assert.equal(invalid.isError, true);
assert.equal(unexpectedRequest, false);

console.log("Optimization MCP submit, exact-key recovery, scoped read and cancel PASS");
