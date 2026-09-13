import assert from "node:assert/strict";

import { fetchByqFactorCompute } from "../src/factor-research.js";

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
    return new Response(JSON.stringify({ input_manifest: { id: "fixture" }, factor: { reproducibility: "reproducible", input_manifest_id: "fixture" }, artifact: { artifact_id: "artifact_" + "a".repeat(32), task_id: request.task_id, kind: "factor_result", content: { input_manifest_id: "fixture" } } }), { status: 201 });
  },
);
assert.equal(success.isError, false);
assert.match(success.content[0].text, /reproducible/);

const invalid = await fetchByqFactorCompute(
  "http://backend:8000",
  request,
  async () => new Response(JSON.stringify({ detail: "look-ahead rejected" }), { status: 422 }),
);
assert.equal(invalid.isError, true);
assert.match(invalid.content[0].text, /factor_request_invalid/);

console.log("Factor MCP translation PASS: deterministic factor request and safe validation error");

for (const failure of ['transport', 'missing-artifact', 'wrong-task', 'wrong-manifest']) {
  let calls = 0;
  const response = await fetchByqFactorCompute('http://backend', request, async () => {
    calls++;
    if (failure === 'transport') throw new Error('private transport');
    return new Response(JSON.stringify({
      input_manifest: { id: 'fixture' }, factor: { input_manifest_id: 'fixture' },
      ...(failure === 'missing-artifact' ? {} : { artifact: {
        artifact_id: 'artifact_' + 'a'.repeat(32), kind: 'factor_result',
        task_id: failure === 'wrong-task' ? 'task_other' : request.task_id,
        content: { input_manifest_id: failure === 'wrong-manifest' ? 'other' : 'fixture' },
      } }),
    }), { status: 201 });
  });
  assert.equal(calls, 1);
  const body = JSON.parse(response.content[0].text);
  assert.equal(body.status, 'outcome_unknown');
  assert.equal(body.retryable, false);
  assert.deepEqual(body.reconciliation, { tool:'byq_research_get', arguments:{
    entity_type:'artifact', task_id:request.task_id, idempotency_key:request.idempotency_key,
  } });
  assert.doesNotMatch(response.content[0].text, /private transport|task_other/);
}
console.log('Factor recovery PASS: exact original artifact lookup and no automatic write replay');

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
