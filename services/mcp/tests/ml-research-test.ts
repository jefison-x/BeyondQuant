import assert from "node:assert/strict";
import {
  fetchByqMlCapabilities, fetchByqMlPredictionCreate, fetchByqMlPredictionGet,
  fetchByqMlStrategyCreate, fetchByqMlTrainingCancel,
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

let timedOutCalls = 0;
const reconciledTraining = await fetchByqMlTrainingCreate(backend, {
  task_id: "task_1", ml_strategy_artifact_id: "artifact_1",
  stock_pool_snapshot_id: "snapshot_1", trace_id: "trace-1", idempotency_key: "training-timeout-1",
}, async (url, init) => {
  timedOutCalls += 1;
  if (init?.method === "POST") throw new Error("response timed out after commit");
  assert.equal(
    url,
    `${backend}/v1/research/ml/training-runs/reconcile?idempotency_key=training-timeout-1`,
  );
  return new Response(JSON.stringify({
    training_run: { training_run_id: runId, status: "waiting_for_data" },
  }), { status: 200 });
});
assert.equal(timedOutCalls, 2);
assert.equal(reconciledTraining.isError, false);
const reconciledPayload = JSON.parse(reconciledTraining.content[0].text);
assert.equal(reconciledPayload.training_run.training_run_id, runId);
assert.equal(reconciledPayload.reconciliation.status, "confirmed");

const unknownTraining = await fetchByqMlTrainingCreate(backend, {
  task_id: "task_1", ml_strategy_artifact_id: "artifact_1",
  stock_pool_snapshot_id: "snapshot_1", trace_id: "trace-1", idempotency_key: "training-unknown-1",
}, async (_url, init) => {
  if (init?.method === "POST") throw new Error("response timed out");
  return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
});
assert.equal(unknownTraining.isError, false);
const unknownPayload = JSON.parse(unknownTraining.content[0].text);
assert.equal(unknownPayload.status, "outcome_unknown");
assert.equal(unknownPayload.retryable, false);
assert.match(unknownPayload.reconciliation.next_action, /workspace_get once/);

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

const predictionId = "mlpred_0123456789abcdef0123456789abcdef";
const prediction = await fetchByqMlPredictionCreate(backend, {
  task_id: "task_1", model_artifact_id: "artifact_model", approval_artifact_id: "artifact_approval",
  execution: { initial_capital: 100000, lot_size: 100 }, trace_id: "trace-1", idempotency_key: "prediction-1",
}, async (url, init) => {
  assert.equal(url, `${backend}/v1/research/ml/prediction-runs`);
  assert.doesNotMatch(String(init?.body), /model_object|object_reference|feature_rows|python|sql|url/i);
  return new Response(JSON.stringify({
    prediction_run: { prediction_run_id: predictionId, status: "queued" },
    backtest_task: { schema_version: "backtest-task.v1", backtest_task_id: "backtesttask_ml_0123456789abcdef0123456789abcdef" },
  }), { status: 202 });
});
assert.equal(prediction.isError, false);

const predictionStatus = await fetchByqMlPredictionGet(backend, predictionId, async (url, init) => {
  assert.equal(url, `${backend}/v1/research/ml/prediction-runs/${predictionId}`);
  assert.equal(init?.method, "GET");
  return new Response(JSON.stringify({ prediction_run: { prediction_run_id: predictionId, status: "completed" } }), { status: 200 });
});
assert.equal(predictionStatus.isError, false);

console.log("ML prediction MCP translation PASS: prediction lifecycle returns the derived backtest task without model objects");
