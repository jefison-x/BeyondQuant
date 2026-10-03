import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { setTimeout as delay } from "node:timers/promises";
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";
import { loadWebEvidencePolicy } from "../src/web-evidence-provenance.js";

// Runs the actual BYQ server factory. The Backend is deliberately synthetic;
// authoritative persistence/ownership is tested separately against PostgreSQL.
const root = "a".repeat(32);
const runtimeBootId = "c".repeat(32);
const requests: Array<{ path: string; body: Record<string, unknown> }> = [];
let schemaCalls = 0;
const researchContext = { schema_version: "research-task-context.v1", status: "available", has_more: false,
  tasks: [{ task_id: "task_" + "c".repeat(32), title: "原会话研究", objective_excerpt: "不使用其他会话的最新任务",
    objective_truncated: false, status: "planned", version: 1, stage: null, next_action: null, blocked_reason: null }] };
const backend = createServer(async (req, res) => {
  if (req.method === "GET") {
    assert.ok(["/v1/agent/data-demand-notifications", "/v1/agent/research-context"].includes(req.url ?? ""));
    assert.equal(req.headers["x-byq-runtime-boot-id"], runtimeBootId);
    assert.equal(req.headers["x-byq-root-run-id"], undefined); // private header is limited to qualified admitted actions
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify(req.url === "/v1/agent/research-context" ? researchContext : { notifications: [] }));
    return;
  }
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(Buffer.from(chunk));
  const body = JSON.parse(Buffer.concat(chunks).toString());
  assert.equal(req.headers["x-byq-root-run-id"],
    req.url === "/v1/research/web-evidence-records" ? undefined : root);
  assert.equal(req.headers["x-byq-actor-principal"], "byq-product-agent-session-wire");
  assert.equal(req.headers["x-byq-dsh-run-id"], "generation-wire");
  assert.equal(req.headers["x-byq-runtime-boot-id"], runtimeBootId);
  requests.push({ path: req.url ?? "", body });
  let status = 201;
  let result: unknown = { artifact: { artifact_id: "synthetic-artifact", status: "validated" } };
  if (req.url === "/internal/domain-validation/schema-rejection") {
    schemaCalls += 1;
    status = schemaCalls === 1 ? 422 : 409;
    result = { detail: { schema_version: "domain-call-admission.v1",
      state: schemaCalls === 1 ? "correctable_failure" : "blocked",
      reason: schemaCalls === 1 ? "domain_validation_failed" : "correction_budget_exhausted" } };
  } else if (["/v1/research/factors/compute", "/v1/research/strategies/versions"].includes(req.url ?? "")) {
    status = 409;
    result = { detail: { schema_version: "domain-call-admission.v1", state: "blocked", reason: "correction_budget_exhausted" } };
  } else if (req.url === "/v1/research/web-evidence-records") {
    const task = body.task as Record<string, unknown>;
    const content = body.content as Record<string, unknown>;
    const sources = content.sources as unknown[];
    const taskId = "task_" + "d".repeat(32);
    result = {
      record_status: "saved",
      idempotency_key: body.idempotency_key,
      source_count: sources.length,
      task: { task_id: taskId, title: task.title, objective: task.objective },
      artifact: { artifact_id: "artifact_" + "d".repeat(32), task_id: taskId,
        kind: "web_research_evidence", content: { sources } },
    };
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
      "x-byq-runtime-boot-id": runtimeBootId,
    } },
  }));
  const listed = await client.listTools();
  const webEvidenceTool = listed.tools.find(tool => tool.name === "byq_web_evidence_create");
  const webProperties = webEvidenceTool?.inputSchema?.properties as Record<string, unknown> | undefined;
  const contentSchema = webProperties?.content as { properties?: Record<string, unknown> } | undefined;
  const searchSchema = contentSchema?.properties?.search as { properties?: Record<string, unknown> } | undefined;
  assert.ok(searchSchema?.properties?.queries, "listed web evidence tool must expose the search query schema");
  assert.ok(!Object.hasOwn(searchSchema?.properties ?? {}, "plugin_id"));
  assert.ok(!Object.hasOwn(searchSchema?.properties ?? {}, "plugin_version"));
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
  const factor = await client.callTool({ name: "byq_factor_compute", arguments: {
    task_id: "task-wire", agent_run_id: "run-wire", trace_id: "untrusted", idempotency_key: "factor-wire",
    as_of_date: "20260831", factor: { name: "momentum", version: "1", lookback: 2 },
    securities: [], sessions: [], bars: [], universe_snapshots: [], sources: [],
  } });
  assert.equal(factor.isError, true);
  assert.equal(JSON.parse((factor.content as Array<{ text: string }>)[0].text).backend.admission.stop, true);
  assert.equal(requests.at(-1)?.path, "/v1/research/factors/compute");
  assert.equal(requests.at(-1)?.body.trace_id, "trace-wire");
  assert.equal(requests.at(-1)?.body.agent_run_id, "run-wire");
  const version = await client.callTool({ name: "byq_strategy_version_create", arguments: {
    task_id: "task-wire", agent_run_id: "run-wire", trace_id: "untrusted", idempotency_key: "version-wire",
    draft_artifact_id: "draft-wire",
  } });
  assert.equal(version.isError, true);
  assert.equal(JSON.parse((version.content as Array<{ text: string }>)[0].text).backend.admission.stop, true);
  assert.equal(requests.at(-1)?.path, "/v1/research/strategies/versions");
  assert.equal(requests.at(-1)?.body.trace_id, "trace-wire");
  assert.equal(requests.at(-1)?.body.agent_run_id, "run-wire");

  for (const bootHeader of [undefined, "D".repeat(32)]) {
    const missingOrMalformedBootClient = new Client({ name: "byq-missing-runtime-boot", version: "1.0.0" });
    const headers: Record<string, string> = {
      "x-byq-root-run-id": root, "x-byq-owner-principal": "alice", "x-byq-workspace-id": "workspace-wire",
      "x-byq-session-id": "session-wire", "x-byq-trace-id": "trace-wire",
      "x-byq-dsh-run-id": "generation-wire", "x-byq-actor-principal": "byq-product-agent-session-wire",
    };
    if (bootHeader !== undefined) headers["x-byq-runtime-boot-id"] = bootHeader;
    await missingOrMalformedBootClient.connect(new StreamableHTTPClientTransport(
      new URL(endpoint + "/mcp/v1"), {
        authProvider: { token: async () => "synthetic-wire-token" },
        requestInit: { headers },
      }));
    const callsBeforeRejectedWrite: number = requests.length;
    const rejectedBootWrite = await missingOrMalformedBootClient.callTool({
      name: "byq_strategy_validate",
      arguments: { ...args, idempotency_key: bootHeader ?? "boot-id-missing" },
    });
    assert.equal(rejectedBootWrite.isError, true);
    assert.equal(requests.length, callsBeforeRejectedWrite,
      "missing or malformed boot identity must stop a mutation before Backend");
    await missingOrMalformedBootClient.close();
  }
  const actorSpoofClient = new Client({ name: "byq-human-actor-spoof", version: "1.0.0" });
  await actorSpoofClient.connect(new StreamableHTTPClientTransport(new URL(endpoint + "/mcp/v1"), {
    authProvider: { token: async () => "synthetic-wire-token" },
    requestInit: { headers: {
      "x-byq-root-run-id": root, "x-byq-owner-principal": "alice", "x-byq-workspace-id": "workspace-wire",
      "x-byq-session-id": "session-wire", "x-byq-trace-id": "trace-wire",
      "x-byq-dsh-run-id": "generation-wire", "x-byq-actor-principal": "alice",
      "x-byq-runtime-boot-id": runtimeBootId,
    } },
  }));
  const callsBeforeSpoofedAuthorization = requests.length;
  const rejectedSpoofedAuthorization = await actorSpoofClient.callTool({ name: "byq_agent_authorize", arguments: {
    run_id: "agent_run_" + "a".repeat(32), action: "byq_market_daily",
  } });
  assert.equal(rejectedSpoofedAuthorization.isError, true);
  assert.equal(requests.length, callsBeforeSpoofedAuthorization,
    "Product MCP must reject a human actor before forwarding Agent authorization to Backend");
  await actorSpoofClient.close();

  const evidenceArgs = {
    task: { title: "Wire provenance", objective: "Store evidence with deployment-bound producer identity." },
    content: {
      schema_version: "web-research-evidence.v1",
      research_as_of: "2026-08-31T12:00:00+08:00",
      market_context: { as_of_date: "20260831", trading_session: null,
        persisted_data_cutoff: null, calendar_verified: false },
      search: { queries: [{ text: "wire fixture", language: "en", purpose: "test producer binding" }],
        stopped_reason: "EVIDENCE_SUFFICIENT" },
      sources: [], claims: [], limitations: ["Synthetic wire fixture."],
      usage_policy: { research_only: true, deterministic_input: false, authoritative_market_data: false },
    },
    lineage: [], idempotency_key: "wire-web-evidence-producer",
  };
  const evidenceRequestCount = () => requests.filter(item => item.path === "/v1/research/web-evidence-records").length;
  const beforeProducerRejections = evidenceRequestCount();
  for (const producerVersion of [loadWebEvidencePolicy().active_producer.plugin_version, "9.9.9"]) {
    const rejectedProducer = await client.callTool({ name: "byq_web_evidence_create", arguments: {
      ...evidenceArgs,
      content: { ...evidenceArgs.content, search: { ...evidenceArgs.content.search,
        plugin_id: "web-search", plugin_version: producerVersion } },
    } }).catch(() => ({ isError: true }));
    assert.equal(rejectedProducer.isError, true,
      "matching or forged producer fields must fail the strict listed MCP input schema");
    assert.equal(evidenceRequestCount(), beforeProducerRejections,
      "caller-supplied producer identity must be rejected before Backend");
  }
  const trustedEvidence = await client.callTool({ name: "byq_web_evidence_create", arguments: evidenceArgs });
  assert.equal(trustedEvidence.isError, false);
  const trustedEvidenceRequest = requests.filter(item => item.path === "/v1/research/web-evidence-records").at(-1);
  assert.ok(trustedEvidenceRequest);
  const trustedSearch = (trustedEvidenceRequest.body.content as Record<string, unknown>).search as Record<string, unknown>;
  assert.equal(trustedSearch.plugin_id, "web-search");
  assert.equal(trustedSearch.plugin_version, loadWebEvidencePolicy().active_producer.plugin_version);
  assert.equal(trustedEvidenceRequest.body.idempotency_key, evidenceArgs.idempotency_key);
  console.log("domain-server-wire: boot identity forwarding, actor binding, and fail-closed mutations PASS");
} finally {
  await client.close();
  server.kill("SIGTERM");
  await new Promise<void>(resolve => {
    if (server.exitCode !== null) resolve();
    else server.once("exit", () => resolve());
  });
  await new Promise<void>(resolve => backend.close(() => resolve()));
}
