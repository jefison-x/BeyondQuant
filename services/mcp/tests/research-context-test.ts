import assert from "node:assert/strict";
import { fetchResearchContext } from "../src/research-context.js";

const task = { task_id: "task_" + "c".repeat(32), title: "沪深300三年研究", objective_excerpt: "每周调仓，先研究仓位管理",
  objective_truncated: false, status: "planned", version: 1, stage: null, next_action: null, blocked_reason: null };
const valid = { schema_version: "research-task-context.v1", status: "available", tasks: [task], has_more: false };
const unavailable = { schema_version: "research-task-context.v1", status: "unavailable", tasks: [], has_more: null };
let calls = 0;
assert.deepEqual(await fetchResearchContext("http://synthetic-backend", async (url, init) => {
  calls += 1;
  assert.equal(url, "http://synthetic-backend/v1/agent/research-context");
  assert.equal(init?.method, "GET");
  assert.ok(init?.signal instanceof AbortSignal);
  return new Response(JSON.stringify(valid));
}), valid);
assert.equal(calls, 1);

for (const body of [
  {}, { ...valid, request_hash: "must-not-leak" }, { ...valid, tasks: [{ ...task, continuation_permission: {} }] },
  { ...valid, tasks: [task, task] }, { ...valid, has_more: true }, { ...valid, status: "none_bound" },
  { ...valid, tasks: [{ ...task, version: true }] }, { ...valid, tasks: [{ ...task, objective_excerpt: "x".repeat(401) }] },
  { ...valid, tasks: [{ ...task, objective_truncated: true }] }, { ...valid, tasks: [{ ...task, stage: "secret-hook" }] },
  { ...valid, tasks: Array.from({ length: 21 }, (_, n) => ({ ...task, task_id: "task_" + n.toString(16).padStart(32, "0") })) },
]) {
  assert.deepEqual(await fetchResearchContext("http://synthetic", async () => new Response(JSON.stringify(body))), unavailable);
}
for (const reply of [new Response("private diagnostic", { status: 403 }), new Response("{"), new Response("x".repeat(131073))]) {
  assert.deepEqual(await fetchResearchContext("http://synthetic", async () => reply), unavailable);
}
assert.deepEqual(await fetchResearchContext("http://synthetic", async () => { throw new Error("private timeout"); }), unavailable);
const empty = { schema_version: "research-task-context.v1", status: "none_bound", tasks: [], has_more: false };
assert.deepEqual(await fetchResearchContext("http://synthetic", async () => new Response(JSON.stringify(empty))), empty);
const astral = { ...valid, tasks: [{ ...task, objective_excerpt: "😀".repeat(400), objective_truncated: true }] };
assert.deepEqual(await fetchResearchContext("http://synthetic", async () => new Response(JSON.stringify(astral))), astral);
console.log("research-context: closed bounded original-task projection; unknown is not absence PASS");
