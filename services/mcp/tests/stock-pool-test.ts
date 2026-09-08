import assert from "node:assert/strict";

import {
  fetchByqPoolCreate,
  fetchByqIndexPoolCatalog, fetchByqIndexPoolCreate, fetchByqIndexPoolStatus, fetchByqIndexPoolReconcile,
  fetchByqPoolHistory,
  fetchByqPoolLifecycle,
  fetchByqPoolSnapshotReplace,
  type PoolContext,
} from "../src/stock-pool.js";

const context: PoolContext = {
  workspace_id: "workspace_alice",
  owner_principal: "alice", actor_principal: "agent-1", trace_id: "trace-1",
  session_id: "session-1", dsh_run_id: "run-1",
};

const calls: Array<{ input: string; init?: RequestInit }> = [];
const fetcher = async (input: string, init?: RequestInit): Promise<Response> => {
  calls.push({ input, init });
  return new Response(JSON.stringify({ pool: { pool_id: "stock_pool_123" } }), {
    status: 200, headers: { "content-type": "application/json" },
  });
};

await fetchByqPoolCreate("http://backend", { name: "p1", symbols: ["000001.SZ"] }, context, fetcher);
await fetchByqPoolSnapshotReplace("http://backend", "stock_pool_123", {
  expected_current_snapshot_id: "snapshot-1", idempotency_key: "edit-1", symbols: ["600000.SH"],
}, context, fetcher);
await fetchByqPoolHistory("http://backend", "stock_pool_123", context, fetcher);
await fetchByqPoolLifecycle("http://backend", "stock_pool_123", {
  status: "inactive", reason: "pause", idempotency_key: "life-1",
}, context, fetcher);

assert.deepEqual(calls.map((call) => call.init?.method), ["POST", "PUT", "GET", "PATCH"]);
assert.ok(calls[1].input.endsWith("/v1/paper/pools/stock_pool_123/snapshot"));
assert.ok(calls[2].input.endsWith("/v1/paper/pools/stock_pool_123/snapshots"));
const headers = calls[0].init?.headers as Record<string, string>;
assert.equal(headers["x-byq-owner-principal"], "alice");
assert.equal(headers["x-byq-actor-principal"], "agent-1");
assert.equal(headers["x-byq-dsh-run-id"], "run-1");

console.log("Stock Pool MCP translation PASS: trusted context, snapshot, history, lifecycle");

await fetchByqIndexPoolCatalog("http://backend", "20240131", context, async (url, init) => {
  assert.equal(url, "http://backend/v1/paper/index-pools/catalog?requested_as_of=20240131&limit=6&offset=0");
  assert.equal(init?.method, "GET");
  return new Response(JSON.stringify({ indices: [] }));
});
await fetchByqIndexPoolCreate("http://backend", { index_symbol: "000905.SH", requested_as_of: "20240131", tracking_mode: "historical_snapshot", idempotency_key: "index-original" }, context, async (url, init) => {
  assert.equal(url, "http://backend/v1/paper/index-pools");
  assert.equal(init?.method, "POST");
  assert.equal(JSON.parse(String(init?.body)).index_symbol, "000905.SH");
  assert.equal(JSON.parse(String(init?.body)).tracking_mode, "historical_snapshot");
  return new Response(JSON.stringify({ run: { status: "queued" } }), { status: 202 });
});
await fetchByqIndexPoolStatus("http://backend", "stock_pool_123", context, async (url, init) => {
  assert.equal(url, "http://backend/v1/paper/pools/stock_pool_123/materializations?limit=10&offset=0");
  assert.equal(init?.method, "GET");
  return new Response(JSON.stringify({ runs: [] }));
});
for (const failure of ["timeout", "invalid", "server"]) {
  const value = await fetchByqIndexPoolCreate("http://backend", { idempotency_key: "original" }, context, async () => {
    if (failure === "timeout") throw new Error("secret");
    return new Response("truncated", { status: failure === "server" ? 503 : 202 });
  });
  const payload = JSON.parse(value.content[0].text);
  assert.equal(payload.status, "outcome_unknown");
  assert.equal(payload.idempotency_key, "original");
  assert.equal(payload.retryable, false);
  assert.doesNotMatch(value.content[0].text, /secret/);
}
for (const status of [404, 503]) {
  const value = await fetchByqIndexPoolReconcile("http://backend", "index-original", context, async (url, init) => {
    assert.equal(url, "http://backend/v1/paper/index-pools/reconcile?idempotency_key=index-original");
    assert.equal(init?.method, "GET");
    return new Response(JSON.stringify({ detail: "not confirmed" }), { status });
  });
  assert.equal(JSON.parse(value.content[0].text).status, "outcome_unknown");
}
