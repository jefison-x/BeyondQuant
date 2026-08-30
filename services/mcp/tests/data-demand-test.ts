import assert from "node:assert/strict";

import {
  fetchByqDataDemandCreate,
  fetchByqDataDemandGet,
  fetchByqDataDemandNotifications,
} from "../src/data-demand.js";

const fetcher = async (url: string, init?: RequestInit): Promise<Response> => {
  assert.equal((init?.headers as Record<string, string> | undefined)?.authorization, undefined);
  if (url.endsWith("/v1/agent/data-demands") && init?.method === "POST") {
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    assert.equal(body.stock_pool_snapshot_id, "stock_pool_snapshot_1");
    assert.equal(body.purpose, "machine_learning");
    return new Response(JSON.stringify({ demand: { schema_version: "data-demand.v1", demand_id: "datademand_0123456789abcdef0123456789abcdef", status: "queued" }, created: true }), { status: 202 });
  }
  if (url.endsWith("/v1/agent/data-demand-notifications")) {
    return new Response(JSON.stringify({ notifications: [{ demand_id: "datademand_0123456789abcdef0123456789abcdef", status: "ready" }] }), { status: 200 });
  }
  assert.match(url, /\/v1\/agent\/data-demands\/datademand_/);
  return new Response(JSON.stringify({ demand: { schema_version: "data-demand.v1", demand_id: "datademand_0123456789abcdef0123456789abcdef", status: "ready" } }), { status: 200 });
};

const created = await fetchByqDataDemandCreate("http://backend:8000", {
  purpose: "machine_learning", stock_pool_snapshot_id: "stock_pool_snapshot_1",
  start_date: "2023-01-01", end_date: "2026-08-28", idempotency_key: "demand-1",
}, fetcher);
assert.equal(created.isError, false);

const read = await fetchByqDataDemandGet(
  "http://backend:8000", "datademand_0123456789abcdef0123456789abcdef", fetcher,
);
assert.equal(read.isError, false);
assert.match(read.content[0].text, /"status":"ready"/);

const inbox = await fetchByqDataDemandNotifications("http://backend:8000", fetcher);
assert.equal(inbox.isError, false);
assert.match(inbox.content[0].text, /notifications/);

const forbidden = await fetchByqDataDemandCreate("http://backend:8000", {}, async () =>
  new Response(JSON.stringify({ detail: "admin token /var/lib/private" }), { status: 403 }),
);
assert.equal(forbidden.isError, true);
assert.match(forbidden.content[0].text, /data_demand_forbidden/);
assert.doesNotMatch(forbidden.content[0].text, /var\/lib|token/i);

console.log("Data-demand MCP translation PASS: bounded create/get/inbox and safe errors");
