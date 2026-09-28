import assert from "node:assert/strict";

import { fetchByqFactorCompute, fetchByqFactorJobGet } from "../src/factor-research.js";

const request = {
  task_id: "task_0123456789abcdef0123456789abcdef",
  trace_id: "byq-trace-factor-mcp",
  idempotency_key: "factor-mcp-1",
  as_of_date: "20260815",
  factor: { name: "daily_return", version: "1", lookback: 1 },
};

const success = await fetchByqFactorCompute(
  "http://backend:8000",
  request,
  async (url, init) => {
    assert.equal(url, "http://backend:8000/v1/research/factors/compute");
    assert.equal(init?.method, "POST");
    assert.doesNotMatch(String(init?.body), /password|secret|token/i);
    return new Response(JSON.stringify({ job: { job_id: "factorjob_" + "a".repeat(32),
      task_id: request.task_id, status: "QUEUED", result_ref: null } }), { status: 201 });
  },
);
assert.equal(success.isError, false);
assert.match(success.content[0].text, /factorjob_/);

const invalid = await fetchByqFactorCompute(
  "http://backend:8000",
  request,
  async () => new Response(JSON.stringify({ detail: "look-ahead rejected" }), { status: 422 }),
);
assert.equal(invalid.isError, true);
assert.match(invalid.content[0].text, /factor_request_invalid/);

console.log("Factor MCP translation PASS: queued factor job and safe validation error");

for (const failure of ['transport', 'missing-job', 'wrong-task', 'wrong-result']) {
  let calls = 0;
  const response = await fetchByqFactorCompute('http://backend', request, async () => {
    calls++;
    if (failure === 'transport') throw new Error('private transport');
    return new Response(JSON.stringify({
      ...(failure === 'missing-job' ? {} : { job: {
        job_id: 'factorjob_' + 'a'.repeat(32), status: 'SUCCEEDED',
        task_id: failure === 'wrong-task' ? 'task_other' : request.task_id,
        result_ref: failure === 'wrong-result' ? 'private' : 'artifact_' + 'a'.repeat(32),
      } }),
    }), { status: 201 });
  });
  assert.equal(calls, 1);
  const body = JSON.parse(response.content[0].text);
  assert.equal(body.status, 'outcome_unknown');
  assert.equal(body.retryable, false);
  assert.deepEqual(body.reconciliation, { tool:'byq_factor_job_get', arguments:{
    task_id:request.task_id, idempotency_key:request.idempotency_key,
  } });
  assert.doesNotMatch(response.content[0].text, /private transport|task_other/);
}
console.log('Factor recovery PASS: exact original Job lookup and no automatic write replay');

const read = await fetchByqFactorJobGet('http://backend', {job_id:'factorjob_' + 'a'.repeat(32)},
  async (url, init) => {
    assert.equal(url, 'http://backend/v1/research/factor-jobs/factorjob_' + 'a'.repeat(32));
    assert.equal(init?.method, 'GET');
    return Response.json({job:{job_id:'factorjob_' + 'a'.repeat(32), task_id:request.task_id,
      status:'SUCCEEDED',result_ref:'artifact_' + 'b'.repeat(32)}});
  });
assert.equal(read.isError, false);

for (const reason of ["domain_validation_failed", "unchanged_failed_input", "correction_budget_exhausted"]) {
  const translated = await fetchByqFactorCompute("http://backend", request, async () => Response.json({ detail: {
    schema_version: "domain-call-admission.v1", state: reason === "domain_validation_failed" ? "correctable_failure" : "blocked",
    reason, ...(reason === "domain_validation_failed" ? { validation: {
      schema_version: "factor-validation-problem.v1", field: "factor.name", code: "unsupported_value",
      allowed_values: ["private-value"], message: "secret" } } : {}),
  } }, { status: reason === "domain_validation_failed" ? 422 : 409 }));
  const body = JSON.parse(translated.content[0].text);
  assert.equal(translated.isError, true);
  assert.equal(body.backend.admission.stop, reason !== "domain_validation_failed");
  assert.doesNotMatch(translated.content[0].text, /private-value|secret/);
  if (reason === "domain_validation_failed") assert.deepEqual(body.backend.validation.allowed_values, ["daily_return", "momentum"]);
}
