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
  server.registerTool("byq_factor_compute", { inputSchema: domainValidationSchemas.byq_factor_compute }, run);
  return server;
});
const handler = toNodeHandler(observeDomainSchemaFailures(official, async (failure, request) => {
  assert.equal(request.headers.get("x-byq-root-run-id"), "a".repeat(32));
  observations.push(failure);
  if (observations.length > Object.keys(domainValidationSchemas).length) return safeDomainAdmission({ detail: {
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
  assert.equal(observations.length, Object.keys(domainValidationSchemas).length);
  assert.equal(executions, 1); // schema acceptance is not Python validation
  const stopped = await client.callTool({ name: "byq_strategy_validate", arguments: { task_id: "task-one" } });
  assert.equal(stopped.isError, true);
  const content = stopped.content as Array<{ type: string; text: string }>;
  assert.equal(JSON.parse(content[0].text).backend.admission.stop, true);
  assert.match(content[1].text, /(?:Invalid|validation|invalid)/);
  assert.equal(executions, 1); // stop decoration cannot invoke the SDK callback
  console.log("domain-schema-observation: official SDK rejection preserved for each qualified tool");
} finally {
  await client.close();
  await new Promise<void>((resolve, reject) => http.close(error => error ? reject(error) : resolve()));
}

let oversizedExecutions = 0;
const boundedGate = observeDomainSchemaFailures({ async fetch() {
  oversizedExecutions++;
  return Response.json({executed:true});
}}, async () => undefined);
const oversized = new Request('http://localhost/mcp', {method:'POST',
  body: JSON.stringify({jsonrpc:'2.0',id:1,method:'tools/call',params:{
    name:'byq_strategy_validate',arguments:{script:'x'.repeat(513*1024)},
  }})});
assert.equal((await boundedGate.fetch(oversized)).status, 400);
assert.equal(oversizedExecutions, 0, 'oversized unobserved request must not reach tool execution');

for (const body of ['{', new Uint8Array([0xff]), JSON.stringify({jsonrpc:'2.0',id:2,method:'tools/call',
  params:{name:'byq_factor_compute',arguments:{data:'x'.repeat(4*1024*1024)}}})]) {
  const rejected = await boundedGate.fetch(new Request('http://localhost/mcp',{method:'POST',body}));
  assert.equal(rejected.status,400);
}
assert.equal(oversizedExecutions,0);
const factorEnvelope = new Request('http://localhost/mcp',{method:'POST',body:JSON.stringify({
  jsonrpc:'2.0',id:3,method:'tools/call',params:{name:'byq_factor_compute',arguments:{data:'x'.repeat(1024*1024)}},
})});
assert.equal((await boundedGate.fetch(factorEnvelope)).status,200);
assert.equal(oversizedExecutions,1,'the existing larger factor transport envelope remains supported');
let streamCancelled = false;
const incomplete = new Request('http://localhost/mcp',{method:'POST',duplex:'half',body:new ReadableStream({
  start(controller) { controller.enqueue(new TextEncoder().encode('{"jsonrpc":')); },
  cancel() { streamCancelled = true; },
})} as RequestInit & {duplex:'half'});
const started = Date.now();
assert.equal((await boundedGate.fetch(incomplete)).status,400);
assert.ok(Date.now()-started >= 4500 && Date.now()-started < 6500);
await new Promise(resolve=>setTimeout(resolve,0));
assert.ok(streamCancelled,'rejected slow body must release both stream branches');
assert.equal(oversizedExecutions,1);
console.log('MCP body bounds PASS: malformed, oversized and stalled bodies cannot execute tools');
