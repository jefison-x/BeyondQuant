import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { setTimeout as delay } from "node:timers/promises";
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";

// Runs the actual BYQ server factory. The Backend is deliberately synthetic;
// authoritative persistence/ownership is tested separately against PostgreSQL.
const root = "a".repeat(32);
const requests: Array<{ path: string; body: Record<string, unknown> }> = [];
let schemaCalls = 0;
const researchContext = { schema_version: "research-task-context.v1", status: "available", has_more: false,
  tasks: [{ task_id: "task_" + "c".repeat(32), title: "原会话研究", objective_excerpt: "不使用其他会话的最新任务",
    objective_truncated: false, status: "planned", version: 1, stage: null, next_action: null, blocked_reason: null }] };
const backend = createServer(async (req, res) => {
  if (req.method === "GET") {
    assert.ok(["/v1/agent/data-demand-notifications", "/v1/agent/research-context"].includes(req.url ?? ""));
    assert.equal(req.headers["x-byq-root-run-id"], undefined); // private header is limited to the two admitted actions
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify(req.url === "/v1/agent/research-context" ? researchContext : { notifications: [] }));
    return;
  }
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(Buffer.from(chunk));
  const body = JSON.parse(Buffer.concat(chunks).toString());
  assert.equal(req.headers["x-byq-root-run-id"], root);
  assert.equal(req.headers["x-byq-actor-principal"], "byq-product-agent-session-wire");
  assert.equal(req.headers["x-byq-dsh-run-id"], "generation-wire");
  requests.push({ path: req.url ?? "", body });
  let status = 201;
  let result: unknown = { artifact: { artifact_id: "synthetic-artifact", status: "validated" } };
  if (req.url === "/internal/domain-validation/schema-rejection") {
    schemaCalls += 1;
    status = schemaCalls === 1 ? 422 : 409;
    result = { detail: { schema_version: "domain-call-admission.v1",
      state: schemaCalls === 1 ? "correctable_failure" : "blocked",
      reason: schemaCalls === 1 ? "domain_validation_failed" : "correction_budget_exhausted" } };
  } else if (requests.length === 1) {
    status = 425;
    result = { detail: { schema_version: "domain-call-admission.v1", state: "blocked", reason: "call_evidence_pending" } };
  }
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(result));
});
await new Promise<void>(resolve => backend.listen(0, "127.0.0.1", resolve));
const address = backend.address();
assert.ok(address && typeof address === "object");
const reserve = createServer();
await new Promise<void>(resolve => reserve.listen(0, "127.0.0.1", resolve));
const selected = reserve.address();
assert.ok(selected && typeof selected === "object");
await new Promise<void>(resolve => reserve.close(() => resolve()));
const server = spawn(process.execPath, ["dist/src/server.js"], { env: { ...process.env,
  PORT: String(selected.port), BYQ_MCP_TOKEN: "synthetic-wire-token",
  BYQ_BACKEND_URL: `http://127.0.0.1:${address.port}` }, stdio: "ignore" });
const client = new Client({ name: "byq-private-wire", version: "1.0.0" });
try {
  const endpoint = `http://127.0.0.1:${selected.port}`;
  let ready = false;
  for (let attempt = 0; attempt < 50; attempt += 1) {
    ready = await fetch(endpoint + "/healthz").then(reply => reply.ok).catch(() => false);
    if (ready) break;
    await delay(50);
  }
  assert.ok(ready, "actual MCP server must start");
  await client.connect(new StreamableHTTPClientTransport(new URL(endpoint + "/mcp/v1"), {
    authProvider: { token: async () => "synthetic-wire-token" }, requestInit: { headers: {
      "x-byq-root-run-id": root, "x-byq-owner-principal": "alice", "x-byq-workspace-id": "workspace-wire",
      "x-byq-session-id": "session-wire", "x-byq-trace-id": "trace-wire",
      "x-byq-dsh-run-id": "generation-wire", "x-byq-actor-principal": "byq-product-agent-session-wire",
    } },
  }));
  const context = await client.callTool({ name: "byq_agent_context", arguments: {} });
  assert.ok(!JSON.stringify(context).includes(root));
  assert.ok(!JSON.stringify(context).includes("root_run_id"));
  assert.deepEqual(JSON.parse((context.content as Array<{ text: string }>)[0].text).research_context, researchContext);
  const args = { task_id: "task-wire", agent_run_id: "run-wire", trace_id: "model-supplied-trace",
    idempotency_key: "same-request", strategy: { strategy_id: "synthetic", name: "合成", category: "custom", script: "pass" } };
  const reply = await client.callTool({ name: "byq_strategy_validate", arguments: args });
  assert.notEqual(reply.isError, true);
  assert.equal(requests.length, 2);
  assert.deepEqual(requests[0], requests[1]);
  assert.equal(requests[0].body.trace_id, "trace-wire");
  assert.equal(requests[0].body.agent_run_id, "run-wire");
  const bad = { ...args, strategy: {} };
  const rejected = await client.callTool({ name: "byq_strategy_validate", arguments: bad }).catch(error => ({ error }));
  assert.ok("error" in rejected || rejected.isError === true);
  const stopped = await client.callTool({ name: "byq_strategy_validate", arguments: { ...bad, idempotency_key: "repair" } });
  assert.equal(stopped.isError, true);
  const content = stopped.content as Array<{ text: string }>;
  assert.equal(JSON.parse(content[0].text).backend.admission.stop, true);
  assert.match(content[1].text, /(?:Invalid|validation|invalid)/);
  assert.equal(requests.filter(item => item.path === "/v1/research/strategies/validate").length, 2);
  assert.equal(schemaCalls, 2);
  console.log("domain-server-wire: trusted factory root, exact pending resend, SDK rejection and closed stop PASS");
} finally {
  await client.close();
  server.kill("SIGTERM");
  await new Promise<void>(resolve => {
    if (server.exitCode !== null) resolve();
    else server.once("exit", () => resolve());
  });
  await new Promise<void>(resolve => backend.close(() => resolve()));
}
