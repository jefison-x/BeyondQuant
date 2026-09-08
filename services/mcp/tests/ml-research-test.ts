import assert from "node:assert/strict";
import {
  fetchByqMlCapabilities, fetchByqMlPredictionCreate, fetchByqMlPredictionGet,
  fetchByqMlStudies, fetchByqMlStudy,
  fetchByqMlStrategyApprove, fetchByqMlStrategyCreate, fetchByqMlTrainingCancel,
  fetchByqMlTrainingCreate, fetchByqMlTrainingGet, fetchByqMlWorkspace,
} from "../src/ml-research.js";

const backend = "http://backend:8000";
const runId = "mlrun_0123456789abcdef0123456789abcdef";

for (const field of ["validation_plan.parameters.folds", "learner.parameters.alpha", "experts.0.learner.parameters.alpha", "experts.0.training_regimes"]) {
  const value = await fetchByqMlStrategyCreate(backend, {}, async () => new Response(JSON.stringify({ detail: {
    schema_version: "ml-validation-problem.v1", field, code: "out_of_range", message: "secret must never pass",
    repair_limit: 999, allowed_values: ["private-input"],
  } }), { status: 422 }));
  const payload = JSON.parse(value.content[0].text);
  assert.equal(payload.backend.validation.field, field);
  assert.equal(payload.backend.validation.repair_limit, 1);
  assert.doesNotMatch(value.content[0].text, /secret|private-input|999/);
}
for (const detail of ["token=secret", { schema_version: "ml-validation-problem.v1", field: "secret", code: "out_of_range" }]) {
  const value = await fetchByqMlStrategyCreate(backend, {}, async () => new Response(JSON.stringify({ detail }), { status: 422 }));
  assert.equal(JSON.parse(value.content[0].text).backend.validation, undefined);
}

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

const strategyApproval = await fetchByqMlStrategyApprove(backend, {
  task_id: "task_1", ml_strategy_artifact_id: "artifact_1", decision: "approved",
  agent_approval_id: "agent_approval_0123456789abcdef0123456789abcdef",
  trace_id: "trace-1", idempotency_key: "strategy-approval-1",
}, async (url, init) => {
  assert.equal(url, `${backend}/v1/research/ml/strategies/approvals`);
  assert.match(String(init?.body), /agent_approval_0123456789abcdef0123456789abcdef/);
  return new Response(JSON.stringify({ approval: { decision: "approved" } }), { status: 201 });
});
assert.equal(strategyApproval.isError, false);

const studies = await fetchByqMlStudies(backend, {
  query: "状态", status: "active", limit: 10, offset: 20,
}, async (url, init) => {
  assert.equal(url, `${backend}/v1/research/ml/studies?query=${encodeURIComponent("状态")}&status=active&limit=10&offset=20`);
  assert.equal(init?.method, "GET");
  return new Response(JSON.stringify({ studies: [], total: 0 }), { status: 200 });
});
assert.equal(studies.isError, false);

const study = await fetchByqMlStudy(backend, "artifact_0123456789abcdef0123456789abcdef", async (url, init) => {
  assert.equal(url, `${backend}/v1/research/ml/studies/artifact_0123456789abcdef0123456789abcdef`);
  assert.equal(init?.method, "GET");
  return new Response(JSON.stringify({ study: { artifact_id: "artifact_0123456789abcdef0123456789abcdef" } }), { status: 200 });
});
assert.equal(study.isError, false);

const watchRegistration = () => new Response(JSON.stringify({ receipt_watch: {
  watch_id: "mlwatch_synthetic", state: "awaiting_receipt", registration_created: true,
} }), { status: 202 });
const training = await fetchByqMlTrainingCreate(backend, {
  task_id: "task_1", ml_strategy_artifact_id: "artifact_1",
  stock_pool_snapshot_id: "snapshot_1", trace_id: "trace-1", idempotency_key: "training-1",
}, async (url, init) => {
  if (url.endsWith("/training-submissions")) return watchRegistration();
  assert.equal(url, `${backend}/v1/research/ml/training-runs`);
  assert.doesNotMatch(String(init?.body), /feature_rows|model_object|object_reference/i);
  return new Response(JSON.stringify({ training_run: { training_run_id: runId, status: "waiting_for_data" } }), { status: 202 });
});
assert.equal(training.isError, false);

for (const mode of ["registration_lost", "awaiting_receipt", "needs_attention", "rejected"]) {
  let calls = 0;
  const guarded = await fetchByqMlTrainingCreate(backend, { idempotency_key: "original-watch-key" }, async (url) => {
    calls++;
    assert.equal(url, `${backend}/v1/research/ml/training-submissions`);
    if (mode === "registration_lost") throw new Error("registration receipt lost");
    return new Response(JSON.stringify({ receipt_watch: {
      watch_id: "mlwatch_original", state: mode, registration_created: false,
    } }), { status: 202 });
  });
  assert.equal(calls, 1, "an existing or unknown registration must not dispatch training");
  assert.equal(JSON.parse(guarded.content[0].text).status, mode === "rejected" ? "error" : "outcome_unknown");
}

let timedOutCalls = 0;
const reconciledTraining = await fetchByqMlTrainingCreate(backend, {
  task_id: "task_1", ml_strategy_artifact_id: "artifact_1",
  stock_pool_snapshot_id: "snapshot_1", trace_id: "trace-1", idempotency_key: "training-timeout-1",
}, async (url, init) => {
  timedOutCalls += 1;
  if (url.endsWith("/training-submissions")) return watchRegistration();
  if (init?.method === "POST") throw new Error("response timed out after commit");
  assert.equal(
    url,
    `${backend}/v1/research/ml/training-runs/reconcile?idempotency_key=training-timeout-1`,
  );
  return new Response(JSON.stringify({
    training_run: { training_run_id: runId, status: "waiting_for_data" },
  }), { status: 200 });
});
assert.equal(timedOutCalls, 3);
assert.equal(reconciledTraining.isError, false);
const reconciledPayload = JSON.parse(reconciledTraining.content[0].text);
assert.equal(reconciledPayload.training_run.training_run_id, runId);
assert.equal(reconciledPayload.reconciliation.status, "confirmed");

const unknownTraining = await fetchByqMlTrainingCreate(backend, {
  task_id: "task_1", ml_strategy_artifact_id: "artifact_1",
  stock_pool_snapshot_id: "snapshot_1", trace_id: "trace-1", idempotency_key: "training-unknown-1",
}, async (_url, init) => {
  if (_url.endsWith("/training-submissions")) return watchRegistration();
  if (init?.method === "POST") throw new Error("response timed out");
  return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
});
assert.equal(unknownTraining.isError, false);
const unknownPayload = JSON.parse(unknownTraining.content[0].text);
assert.equal(unknownPayload.status, "outcome_unknown");
assert.equal(unknownPayload.retryable, false);
assert.match(unknownPayload.reconciliation.next_action, /byq_ml_training_get.*idempotency_key/);

const invalidReceipt = await fetchByqMlTrainingCreate(backend, {
  task_id: "task_1", ml_strategy_artifact_id: "artifact_1", stock_pool_snapshot_id: "snapshot_1",
  trace_id: "trace-1", idempotency_key: "training-invalid-receipt",
}, async (_url, init) => _url.endsWith("/training-submissions") ? watchRegistration() : init?.method === "POST"
  ? new Response("truncated receipt", { status: 202 })
  : new Response(JSON.stringify({ training_run: { training_run_id: runId } }), { status: 200 }));
assert.equal(JSON.parse(invalidReceipt.content[0].text).training_run.training_run_id, runId);
assert.equal(JSON.parse(invalidReceipt.content[0].text).reconciliation.status, "confirmed");

for (const status of [404, 503]) {
  const unknown = await fetchByqMlTrainingGet(backend, { idempotency_key: "unknown-key" }, async (url, init) => {
    assert.ok([`${backend}/v1/research/ml/training-runs/reconcile?idempotency_key=unknown-key`,
      `${backend}/v1/research/ml/training-submissions/reconcile?idempotency_key=unknown-key`].includes(url));
    assert.equal(init?.method, "GET");
    return new Response(JSON.stringify({ detail: "not yet visible" }), { status });
  });
  assert.equal(JSON.parse(unknown.content[0].text).status, "outcome_unknown");
}
const lateReceipt = await fetchByqMlTrainingGet(backend, { idempotency_key: "unknown-key" }, async () =>
  new Response(JSON.stringify({ training_run: { training_run_id: runId } }), { status: 200 }));
assert.equal(JSON.parse(lateReceipt.content[0].text).training_run.training_run_id, runId);

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
