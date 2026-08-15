import assert from "node:assert/strict";

import {
  fetchByqBacktestCancel,
  fetchByqBacktestGet,
  fetchByqBacktestRun,
  fetchByqBacktestSubmit,
} from "../src/backtest.js";

const jobId = "backtest_0123456789abcdef0123456789abcdef";
const request = { task_id: "task_0123456789abcdef0123456789abcdef", idempotency_key: "backtest-mcp-1" };

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

console.log("Backtest MCP translation PASS: submit, get, run, cancel and safe error mapping");
