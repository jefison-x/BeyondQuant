import assert from "node:assert/strict";
import { fetchByqStrategyVersionCreate, fetchByqStrategyExport } from "../src/strategy.js";
import { fetchByqBacktestSubmit, fetchByqBacktestGet } from "../src/backtest.js";
import { fetchByqResearchTaskCreate, fetchByqResearchGet } from "../src/research.js";
import { fetchByqFactorCompute } from "../src/factor-research.js";
import { fetchByqDataDemandCreate, fetchByqDataDemandGet } from "../src/data-demand.js";
import { fetchByqFeedbackCreate, fetchByqFeedbackGet } from "../src/feedback.js";
import { fetchByqAgentRunStart, fetchByqAgentRoles } from "../src/agent.js";
import { fetchByqLearningRunStart, fetchByqLearningRunGet } from "../src/learning.js";

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;
const url = "http://synthetic-backend.invalid";
const request = { owner_principal: "synthetic", title: "Synthetic", objective: "No execution",
  trace_id: "synthetic-trace", idempotency_key: "original-request-1" };
const writes = [
  (fetcher: Fetcher) => fetchByqStrategyVersionCreate(url, request, fetcher),
  (fetcher: Fetcher) => fetchByqBacktestSubmit(url, request, fetcher),
  (fetcher: Fetcher) => fetchByqResearchTaskCreate(url, request, fetcher),
  (fetcher: Fetcher) => fetchByqFactorCompute(url, request, fetcher),
  (fetcher: Fetcher) => fetchByqDataDemandCreate(url, request, fetcher),
  (fetcher: Fetcher) => fetchByqFeedbackCreate(url, request, fetcher),
  (fetcher: Fetcher) => fetchByqAgentRunStart(url, request, {}, fetcher),
  (fetcher: Fetcher) => fetchByqLearningRunStart(url, request, {}, fetcher),
];
const unknownResponses = [
  () => { throw new Error("private transport exception"); },
  () => new Response("private proxy body", { status: 503 }),
  () => new Response("private broken json", { status: 201 }),
  () => new Response("[]", { status: 200 }),
  () => new Response("null", { status: 200 }),
];
for (const write of writes) {
  for (const respond of unknownResponses) {
    let calls = 0;
    const result = await write(async () => { calls++; return respond(); });
    const payload = JSON.parse(result.content[0].text);
    assert.equal(calls, 1, "classification must never retry writes");
    assert.equal(payload.status, "outcome_unknown");
    assert.equal(payload.retryable, false);
    assert.equal(payload.idempotency_key, request.idempotency_key);
    assert.doesNotMatch(result.content[0].text, /private/);
  }
  for (const status of [401, 403, 404, 409, 422, 429]) {
    const result = await write(async () => new Response(JSON.stringify({ detail: "rejected" }), { status }));
    assert.equal(result.isError, true);
    assert.equal(JSON.parse(result.content[0].text).status, "error");
  }
}
const reads = [
  (fetcher: Fetcher) => fetchByqStrategyExport(url, "artifact-test", fetcher),
  (fetcher: Fetcher) => fetchByqBacktestGet(url, "job-test", fetcher),
  (fetcher: Fetcher) => fetchByqResearchGet(url, "research_task", "task-test", fetcher),
  (fetcher: Fetcher) => fetchByqDataDemandGet(url, "demand-test", fetcher),
  (fetcher: Fetcher) => fetchByqFeedbackGet(url, "feedback-test", fetcher),
  (fetcher: Fetcher) => fetchByqAgentRoles(url, fetcher),
  (fetcher: Fetcher) => fetchByqLearningRunGet(url, "learning-test", {}, fetcher),
];
for (const read of reads) {
  const result = await read(async () => { throw new Error("private transport exception"); });
  assert.equal(result.isError, true);
  assert.equal(JSON.parse(result.content[0].text).backend.status, "unreachable");
}
console.log("Write outcome matrix PASS: 8 write families, 5 unknown modes, 6 explicit rejections, 7 read families");
