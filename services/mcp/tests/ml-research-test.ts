import assert from "node:assert/strict";
import {
  fetchByqMlCapabilities, fetchByqMlStrategyCreate, fetchByqMlTrainingCancel,
  fetchByqMlTrainingCreate, fetchByqMlTrainingGet, fetchByqMlWorkspace,
} from "../src/ml-research.js";

const backend = "http://backend:8000";
const runId = "mlrun_0123456789abcdef0123456789abcdef";

for (const [call, path] of [
  [fetchByqMlCapabilities, "/v1/research/ml/capabilities"],
  [fetchByqMlWorkspace, "/v1/research/ml/workspace"],
] as const) {
  const response = await call(backend, async (url, init) => {
    assert.equal(url, `${backend}${path}`);
    assert.equal(init?.method, "GET");
    return new Response(JSON.stringify({ schema_version: "safe.v1" }), { status: 200 });
  });
  assert.equal(response.isError, false);
}

const strategy = await fetchByqMlStrategyCreate(backend, {
  task_id: "task_1", strategy: { schema_version: "ml-strategy-version.v1" },
  trace_id: "trace-1", idempotency_key: "strategy-1",
}, async (url, init) => {
  assert.equal(url, `${backend}/v1/research/ml/strategies/versions`);
  assert.doesNotMatch(String(init?.body), /python|sql|url|model_object|object_reference/i);
  return new Response(JSON.stringify({ artifact: { artifact_id: "artifact_1" } }), { status: 201 });
});
assert.equal(strategy.isError, false);

const training = await fetchByqMlTrainingCreate(backend, {
  task_id: "task_1", ml_strategy_artifact_id: "artifact_1",
  stock_pool_snapshot_id: "snapshot_1", trace_id: "trace-1", idempotency_key: "training-1",
}, async (url, init) => {
  assert.equal(url, `${backend}/v1/research/ml/training-runs`);
  assert.doesNotMatch(String(init?.body), /feature_rows|model_object|object_reference/i);
  return new Response(JSON.stringify({ training_run: { training_run_id: runId, status: "waiting_for_data" } }), { status: 202 });
});
assert.equal(training.isError, false);

for (const [call, suffix, method] of [
  [fetchByqMlTrainingGet, "", "GET"],
  [fetchByqMlTrainingCancel, "/cancel", "POST"],
] as const) {
  const response = await call(backend, runId, async (url, init) => {
    assert.equal(url, `${backend}/v1/research/ml/training-runs/${runId}${suffix}`);
    assert.equal(init?.method, method);
    return new Response(JSON.stringify({ training_run: { training_run_id: runId, status: "cancelled" } }), { status: 200 });
  });
  assert.equal(response.isError, false);
}

console.log("ML MCP translation PASS: closed capabilities, safe workspace, strategy and training lifecycle");
