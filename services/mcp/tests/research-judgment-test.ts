import assert from "node:assert/strict";
import { fetchByqResearchStageInput } from "../src/research-judgment.js";

const taskId = "task_" + "a".repeat(32);
const valid = {
  schema_version: "research-stage-input.v1", task_id: taskId, plan_version: 1, task_version: 3,
  stage: "backtest_analysis", iteration: 1, status: "active", objective: "研究", stage_instruction: "analyse",
  proposal_kinds: ["backtest_analysis", "escalate"], evidence: [], allowed_tools: ["byq_research_get"],
  model_call_limit: 2, escalation_allowed: true,
};

let calls = 0;
const response = await fetchByqResearchStageInput("http://synthetic-backend", taskId, async (url, init) => {
  calls += 1;
  assert.equal(url, `http://synthetic-backend/v1/research/tasks/${taskId}/stage-input`);
  assert.equal(init?.method, "GET");
  assert.ok(init?.signal instanceof AbortSignal);
  return new Response(JSON.stringify(valid));
});
assert.equal(calls, 1);
assert.equal(response.isError, false);
assert.deepEqual(JSON.parse(response.content[0].text), valid);

for (const body of [
  { ...valid, task_id: "task_" + "b".repeat(32) },
  { ...valid, schema_version: "research-stage-input.v2" },
  { ...valid, stage: "waiting_for_data" },
  { ...valid, evidence: Array.from({ length: 65 }, () => ({})) },
  { ...valid, plan_version: "1" },
  { raw_signal_snapshot: {} },
]) {
  const result = await fetchByqResearchStageInput(
    "http://synthetic", taskId, async () => new Response(JSON.stringify(body)));
  assert.equal(result.isError, true);
}

const oversized = await fetchByqResearchStageInput(
  "http://synthetic", taskId, async () => new Response("x".repeat(96 * 1024 + 1)));
assert.equal(oversized.isError, true);
assert.match(oversized.content[0].text, /stage_input_bound_exceeded/);

for (const reply of [new Response("private", { status: 403 }), new Response("{"), new Response("nope")]) {
  const result = await fetchByqResearchStageInput("http://synthetic", taskId, async () => reply);
  assert.equal(result.isError, true);
}
const invalidId = await fetchByqResearchStageInput("http://synthetic", "task_not-hex", async () => new Response("{}"));
assert.equal(invalidId.isError, true);
assert.match(invalidId.content[0].text, /research_request_invalid/);
const thrown = await fetchByqResearchStageInput("http://synthetic", taskId, async () => { throw new Error("timeout"); });
assert.equal(thrown.isError, true);

console.log("research-judgment: bounded read-only stage input; oversized/malformed/raw refused PASS");
