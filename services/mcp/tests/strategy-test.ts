import assert from "node:assert/strict";

import {
  fetchByqStrategyApprove,
  fetchByqStrategyExport,
  fetchByqStrategyValidate,
  fetchByqStrategyVersionCreate,
} from "../src/strategy.js";

const taskId = "task_0123456789abcdef0123456789abcdef";
const artifactId = "artifact_0123456789abcdef0123456789abcdef";
const request = {
  task_id: taskId,
  trace_id: "byq-trace-strategy-mcp",
  idempotency_key: "strategy-mcp-1",
};

const validated = await fetchByqStrategyValidate(
  "http://backend:8000",
  { ...request, strategy: { strategy_id: "MomentumStrategy", name: "Momentum", category: "momentum", script: "class CustomStrategy: pass" } },
  async (url, init) => {
    assert.equal(url, "http://backend:8000/v1/research/strategies/validate");
    assert.equal(init?.method, "POST");
    assert.doesNotMatch(String(init?.body), /password|secret|token/i);
    return new Response(JSON.stringify({ validation: { success: true }, artifact: { artifact_id: artifactId } }), { status: 201 });
  },
);
assert.equal(validated.isError, false);
assert.match(validated.content[0].text, /"success":true/);

const version = await fetchByqStrategyVersionCreate(
  "http://backend:8000",
  { ...request, draft_artifact_id: artifactId },
  async (url, init) => {
    assert.equal(url, "http://backend:8000/v1/research/strategies/versions");
    assert.equal(init?.method, "POST");
    return new Response(JSON.stringify({ artifact: { kind: "strategy_version", status: "validated" } }), { status: 201 });
  },
);
assert.equal(version.isError, false);

const approved = await fetchByqStrategyApprove(
  "http://backend:8000",
  { ...request, strategy_version_artifact_id: artifactId, reviewer_principal: "human-owner", decision: "approved" },
  async (url, init) => {
    assert.equal(url, "http://backend:8000/v1/research/strategies/approvals");
    assert.equal(init?.method, "POST");
    return new Response(JSON.stringify({ approval: { execution_authorized: true, execution_outcome: "not_started" } }), { status: 201 });
  },
);
assert.equal(approved.isError, false);
assert.match(approved.content[0].text, /not_started/);

const exported = await fetchByqStrategyExport(
  "http://backend:8000",
  artifactId,
  async (url, init) => {
    assert.equal(url, `http://backend:8000/v1/research/strategies/versions/${artifactId}/export`);
    assert.equal(init?.method, "GET");
    return new Response(JSON.stringify({ export: { version_id: "a".repeat(64) } }), { status: 200 });
  },
);
assert.equal(exported.isError, false);
assert.match(exported.content[0].text, /version_id/);

const invalid = await fetchByqStrategyValidate(
  "http://backend:8000",
  request,
  async () => new Response(JSON.stringify({ detail: "forbidden import" }), { status: 422 }),
);
assert.equal(invalid.isError, true);
assert.match(invalid.content[0].text, /strategy_request_invalid/);

console.log("Strategy MCP translation PASS: validation, version, approval, export and safe error mapping");
