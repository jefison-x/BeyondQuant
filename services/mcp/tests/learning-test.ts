import assert from "node:assert/strict";

import {
  fetchByqLearningIterationRecord,
  fetchByqLearningRunStart,
  fetchByqLessonPropose,
} from "../src/learning.js";

const context = {
  owner_principal: "alice",
  actor_principal: "alice",
  trace_id: "trace-learning-mcp-1",
  session_id: "session-learning-mcp-1",
  dsh_run_id: "dsh-run-learning-mcp-1",
};

const start = await fetchByqLearningRunStart(
  "http://backend:8000",
  { task_id: "task_0123456789abcdef0123456789abcdef", budget: { max_iterations: 1, max_repairs: 0 }, idempotency_key: "learning-mcp-1" },
  context,
  async (url, init) => {
    assert.equal(url, "http://backend:8000/v1/learning/runs");
    assert.equal(init?.headers && (init.headers as Record<string, string>)["x-byq-owner-principal"], "alice");
    assert.doesNotMatch(String(init?.body), /password|secret|token/i);
    return new Response(JSON.stringify({ run: { learning_run_id: "learning_run_0123456789abcdef0123456789abcdef", status: "active" } }), { status: 201 });
  },
);
assert.equal(start.isError, false);

const iterated = await fetchByqLearningIterationRecord(
  "http://backend:8000",
  "learning_run_0123456789abcdef0123456789abcdef",
  { iteration_index: 1, attempt: 1, outcome: "produced", idempotency_key: "iteration-mcp-1" },
  context,
  async (url, init) => {
    assert.equal(url, "http://backend:8000/v1/learning/runs/learning_run_0123456789abcdef0123456789abcdef/iterations");
    assert.equal((init?.headers as Record<string, string>)["x-byq-session-id"], "session-learning-mcp-1");
    return new Response(JSON.stringify({ iteration: { iteration_index: 1 }, run: { status: "awaiting_review" } }), { status: 201 });
  },
);
assert.equal(iterated.isError, false);

const safeError = await fetchByqLessonPropose(
  "http://backend:8000",
  { task_id: "task_0123456789abcdef0123456789abcdef", content: {}, evidence: [], idempotency_key: "lesson-mcp-1" },
  context,
  async () => new Response(JSON.stringify({ detail: "evidence must not be empty /var/lib/byq/domain" }), { status: 422 }),
);
assert.equal(safeError.isError, true);
assert.match(safeError.content[0].text, /learning_request_invalid/);
assert.doesNotMatch(safeError.content[0].text, /var\/lib/);

console.log("Learning MCP translation PASS: bounded run/iteration paths, trusted context, and safe errors");
