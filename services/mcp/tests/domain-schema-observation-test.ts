import assert from "node:assert/strict";
import { createServer } from "node:http";
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";
import { toNodeHandler } from "@modelcontextprotocol/node";
import { createMcpHandler, McpServer } from "@modelcontextprotocol/server";
import { domainValidationSchemas } from "../src/domain-validation-schema.js";
import { observeDomainSchemaFailures, type SchemaFailure } from "../src/domain-schema-observation.js";
import { safeDomainAdmission } from "../src/domain-admission.js";

const observations: SchemaFailure[] = [];
let executions = 0;
const official = createMcpHandler(() => {
  const server = new McpServer({ name: "byq-schema-qualification", version: "1.0.0" });
  const run = async () => {
    executions += 1;
    return { content: [{ type: "text" as const, text: "synthetic validation only" }] };
  };
  server.registerTool("byq_strategy_validate", { inputSchema: domainValidationSchemas.byq_strategy_validate }, run);
  server.registerTool("byq_ml_strategy_create", { inputSchema: domainValidationSchemas.byq_ml_strategy_create }, run);
  return server;
});
const handler = toNodeHandler(observeDomainSchemaFailures(official, async (failure, request) => {
  assert.equal(request.headers.get("x-byq-root-run-id"), "a".repeat(32));
  observations.push(failure);
  if (observations.length > 2) return safeDomainAdmission({ detail: {
    schema_version: "domain-call-admission.v1", state: "blocked", reason: "correction_budget_exhausted",
  } });
}));
const http = createServer((req, res) => { void handler(req, res); });
await new Promise<void>(resolve => http.listen(0, "127.0.0.1", resolve));
const address = http.address();
assert.ok(address && typeof address === "object");
const client = new Client({ name: "byq-synthetic-probe", version: "1.0.0" });
const transport = new StreamableHTTPClientTransport(new URL(`http://127.0.0.1:${address.port}/mcp`), {
  requestInit: { headers: { "x-byq-root-run-id": "a".repeat(32) } },
});
try {
  await client.connect(transport);
  for (const action of Object.keys(domainValidationSchemas)) {
    const args = { task_id: "task-one", agent_run_id: "run-one", idempotency_key: "key-one",
      trace_id: "trace-one", strategy: { name: "沪深300", nested: [1, 1.5, true, null] } };
    // The unmodified SDK must still reject the exact invalid request. Observing
    // a schema failure must not run a domain callback or fake a successful tool.
    const reply = await client.callTool({ name: action, arguments: args }).catch(error => ({ error }));
    assert.ok("error" in reply || reply.isError === true);
    assert.deepEqual(observations.at(-1), { action, arguments: args });
    assert.equal(executions, 0);
  }
  const valid = { task_id: "task-one", agent_run_id: "run-one", idempotency_key: "key-two",
    trace_id: "trace-one", strategy: { strategy_id: "synthetic", name: "合成", category: "custom", script: "invalid Python" } };
  const reply = await client.callTool({ name: "byq_strategy_validate", arguments: valid });
  assert.notEqual(reply.isError, true);
  assert.equal(observations.length, 2);
  assert.equal(executions, 1); // schema acceptance is not Python validation
  const stopped = await client.callTool({ name: "byq_strategy_validate", arguments: { task_id: "task-one" } });
  assert.equal(stopped.isError, true);
  const content = stopped.content as Array<{ type: string; text: string }>;
  assert.equal(JSON.parse(content[0].text).backend.admission.stop, true);
  assert.match(content[1].text, /(?:Invalid|validation|invalid)/);
  assert.equal(executions, 1); // stop decoration cannot invoke the SDK callback
  console.log("domain-schema-observation: official SDK rejection preserved for both tools");
} finally {
  await client.close();
  await new Promise<void>((resolve, reject) => http.close(error => error ? reject(error) : resolve()));
}
