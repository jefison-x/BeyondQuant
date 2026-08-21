import assert from "node:assert/strict";

import { fetchByqPaperAccount, fetchByqPaperOrder, fetchByqPaperSnapshots, type PaperContext } from "../src/paper-trading.js";

const context: PaperContext = {
  owner_principal: "alice", actor_principal: "agent-1", trace_id: "trace-1",
  session_id: "session-1", dsh_run_id: "run-1",
};
const calls: Array<{ input: string; init?: RequestInit }> = [];
const fetcher = async (input: string, init?: RequestInit): Promise<Response> => {
  calls.push({ input, init });
  return new Response(JSON.stringify({ status: "ok" }), { status: 200, headers: { "content-type": "application/json" } });
};

await fetchByqPaperAccount("http://backend", "paper_account_123", context, fetcher);
await fetchByqPaperOrder("http://backend", "paper_account_123", "paper_order_456", context, fetcher);
await fetchByqPaperSnapshots("http://backend", "paper_account_123", context, fetcher);
assert.deepEqual(calls.map((call) => call.init?.method), ["GET", "GET", "GET"]);
assert.ok(calls[1].input.endsWith("/v1/paper/accounts/paper_account_123/orders/paper_order_456"));
assert.ok(calls[2].input.endsWith("/v1/paper/accounts/paper_account_123/snapshots"));
const headers = calls[0].init?.headers as Record<string, string>;
assert.equal(headers["x-byq-owner-principal"], "alice");
assert.equal(headers["x-byq-actor-principal"], "agent-1");
assert.equal(headers["x-byq-dsh-run-id"], "run-1");
console.log("Paper Trading MCP translation PASS: trusted context and bounded read projections");
