import assert from "node:assert/strict";

import {
  fetchByqDataDemandCancel,
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

const demandId = "datademand_" + "c".repeat(32);
const taskId = "task_" + "d".repeat(32);
const businessJob = {
  job_id: demandId, workspace_id: "workspace_" + "e".repeat(32), type: "DATA_IMPORT",
  status: "QUEUED", progress: 0, input_ref: "f".repeat(64), result_ref: null,
  error: null, created_at: "2026-09-28T00:00:00+00:00", started_at: null, finished_at: null,
};
const taskBoundDemand = {
  schema_version: "data-demand.v1", demand_id: demandId, task_id: taskId, status: "queued",
  job: businessJob,
};
const taskFetcher = async (url: string, init?: RequestInit): Promise<Response> => {
  if (url.endsWith("/v1/agent/data-demands") && init?.method === "POST") {
    const request = JSON.parse(String(init.body)) as Record<string, unknown>;
    assert.equal(request.task_id, taskId);
    assert.equal(request.idempotency_key, "task-demand-1");
    return Response.json({ demand: taskBoundDemand, business_job: businessJob, created: true }, { status: 202 });
  }
  assert.equal(url, `http://backend/v1/agent/data-demands/${demandId}`);
  return Response.json({ demand: taskBoundDemand, business_job: businessJob });
};
const taskCreate = await fetchByqDataDemandCreate("http://backend", {
  purpose: "research", task_id: taskId, stock_pool_snapshot_id: "pool_snapshot_1",
  start_date: "2026-01-01", end_date: "2026-01-31", idempotency_key: "task-demand-1",
}, taskFetcher);
assert.equal(taskCreate.isError, false);
assert.match(taskCreate.content[0].text, /"type":"DATA_IMPORT"/);
const taskRead = await fetchByqDataDemandGet("http://backend", { job_id: demandId }, taskFetcher);
assert.equal(taskRead.isError, false);
assert.match(taskRead.content[0].text, /"business_job"/);
const invalidTaskRead = await fetchByqDataDemandGet("http://backend", { job_id: demandId }, async () =>
  Response.json({ demand: taskBoundDemand, business_job: { ...businessJob, status: "SUCCEEDED" } }));
assert.equal(invalidTaskRead.isError, true);

const cancelledJob = { ...businessJob, status: "CANCELLED", finished_at: "2026-09-28T00:01:00+00:00" };
const cancelledDemand = { ...taskBoundDemand, status: "cancelled", job: cancelledJob };
const cancelled = await fetchByqDataDemandCancel("http://backend", demandId, async (url, init) => {
  assert.equal(url, `http://backend/v1/agent/data-demands/${demandId}/cancel`);
  assert.equal(init?.method, "POST");
  return Response.json({ demand: cancelledDemand, business_job: cancelledJob });
});
assert.equal(cancelled.isError, false);
assert.match(cancelled.content[0].text, /"status":"CANCELLED"/);
const uncertainCancel = await fetchByqDataDemandCancel("http://backend", demandId, async () => {
  throw new Error("private lost cancel response");
});
assert.equal(uncertainCancel.isError, false);
assert.deepEqual(JSON.parse(uncertainCancel.content[0].text).reconciliation, {
  tool: "byq_data_demand_get", arguments: { job_id: demandId },
});

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

let writes = 0;
const lost = await fetchByqDataDemandCreate('http://backend', { idempotency_key:'original' }, async () => {
  writes++; throw new Error('private lost reply');
});
assert.equal(writes, 1);
assert.deepEqual(JSON.parse(lost.content[0].text).reconciliation, {
  tool:'byq_data_demand_get', arguments:{idempotency_key:'original'},
});
const recovered = await fetchByqDataDemandGet('http://backend', {idempotency_key:'original'}, async (url, init) => {
  assert.equal(init?.method, 'GET');
  assert.equal(url, 'http://backend/v1/agent/data-demands/by-key/original');
  return Response.json({state:'confirmed', demand:{schema_version:'data-demand.v1', demand_id:'datademand_'+'a'.repeat(32)}});
});
assert.equal(recovered.isError, false);
const mismatched = await fetchByqDataDemandGet('http://backend', 'datademand_'+'a'.repeat(32), async () =>
  Response.json({demand:{schema_version:'data-demand.v1', demand_id:'datademand_'+'b'.repeat(32)}}));
assert.equal(mismatched.isError, true);
