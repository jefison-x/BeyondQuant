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
    return new Response(JSON.stringify({ input_manifest: { id: "fixture" }, factor: { reproducibility: "reproducible" } }), { status: 201 });
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
