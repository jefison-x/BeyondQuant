import assert from "node:assert/strict";
import { createHash, createHmac } from "node:crypto";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { setTimeout as delay } from "node:timers/promises";
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";

const signingKey = "integration-acp-signing-key-with-at-least-32-bytes"; // gitleaks:allow — fixed synthetic test key
const legacyToken = "synthetic-legacy-mcp-token";
const discoveryToken = "synthetic-acp-discovery-token";
const backendProof = "synthetic-backend-proof-token";
const claims = {
  v: 1,
  aud: "byq-product-mcp",
  root_run_id: "a".repeat(32),
  runtime_boot_id: "b".repeat(32),
  owner_principal: "alice",
  workspace_id: "workspace_alice",
  actor_principal: "byq-product-agent-session-root",
  trace_id: "trace-root",
  session_id: "session-root",
  dsh_run_id: "generation-root",
  native_root_session_id: "00000000-0000-4000-8000-000000000001",
  native_agent_session_id: "00000000-0000-4000-8000-000000000001",
  native_parent_session_id: null,
  origin: "root",
  depth: 0,
  expires_at: Date.now() + 10 * 60_000,
};

function acpBearer(): string {
  const sorted: Record<string, unknown> = {};
  for (const key of Object.keys(claims).sort()) sorted[key] = (claims as Record<string, unknown>)[key];
  const payload = Buffer.from(JSON.stringify(sorted), "utf8");
  const signature = createHmac("sha256", Buffer.from(signingKey, "utf8")).update(payload).digest();
  return `byq-acp-v1.${payload.toString("base64url")}.${signature.toString("base64url")}`;
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${canonical(record[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function sha256(value: unknown): string {
  return createHash("sha256").update(canonical(value), "ascii").digest("hex");
}

const runId = "agent_run_" + "c".repeat(32);
const bindReceipt = {
  schema_version: "byq-acp-agent-bind-receipt.v1",
  root_run_id: claims.root_run_id,
  runtime_boot_id: claims.runtime_boot_id,
  native_agent_session_id: claims.native_agent_session_id,
  native_parent_session_id: null,
  agent_run_id: runId,
  parent_run_id: null,
  origin: "root",
  depth: 0,
  status: "bound",
  binding_sha256: "d".repeat(64),
};
const requests: Array<{ path: string; headers: Headers; body?: Record<string, unknown> }> = [];
let observationMode: "valid" | "invalid" = "valid";
let ingressMode: "valid" | "invalid" = "valid";
let bindingStatus: "pending" | "bound" = "bound";
let domainMode: "success" | "reject422" | "conflict409" | "timeout" = "success";
let settlementMode: "valid" | "invalid" = "valid";
let authorizationDenialMode: "valid" | "missing" | "ok" = "valid";
let rootBound = false;
let ingressSequence = 0;
const settlements: Array<Record<string, unknown>> = [];
const observedIngress = new Map<string, { receipt: Record<string, unknown>; arguments: Record<string, unknown> }>();
const backend = createServer(async (req, res) => {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(Buffer.from(chunk));
  const raw = Buffer.concat(chunks).toString("utf8");
  const body = raw ? JSON.parse(raw) as Record<string, unknown> : undefined;
  const entry = { path: req.url ?? "", headers: new Headers(req.headers as Record<string, string>), body };
  requests.push(entry);
  const send = (status: number, value: unknown) => {
    res.writeHead(status, { "content-type": "application/json" });
    res.end(JSON.stringify(value));
  };

  if (req.url === "/internal/acp/tool-ingress-observe") {
    assert.equal(req.method, "POST");
    assert.equal(entry.headers.get("authorization"), `Bearer ${backendProof}`);
    assert.equal(entry.headers.get("x-byq-owner-principal"), claims.owner_principal);
    assert.equal(entry.headers.get("x-byq-workspace-id"), claims.workspace_id);
    assert.equal(entry.headers.get("x-byq-actor-principal"), claims.actor_principal);
    assert.equal(entry.headers.get("x-byq-trace-id"), claims.trace_id);
    assert.equal(entry.headers.get("x-byq-session-id"), claims.session_id);
    assert.equal(entry.headers.get("x-byq-dsh-run-id"), claims.dsh_run_id);
    assert.equal(entry.headers.get("x-byq-runtime-boot-id"), claims.runtime_boot_id);
    assert.equal(entry.headers.get("x-byq-root-run-id"), claims.root_run_id);
    assert.equal(body?.schema_version, "byq-acp-tool-ingress-observe.v1");
    assert.equal(body?.root_run_id, claims.root_run_id);
    assert.equal(body?.runtime_boot_id, claims.runtime_boot_id);
    assert.equal(body?.native_root_session_id, claims.native_root_session_id);
    assert.equal(body?.native_agent_session_id, claims.native_agent_session_id);
    assert.equal(body?.native_parent_session_id, null);
    assert.equal(body?.origin, "root");
    assert.equal(body?.depth, 0);
    assert.match(String(body?.mcp_request_id), /^[0-9a-f]{32}$/);
    assert.equal(typeof body?.tool_name, "string");
    assert.ok(body?.arguments && typeof body.arguments === "object");
    const bootstrap = ["byq_health", "byq_agent_roles", "byq_agent_context"].includes(String(body?.tool_name));
    const receipt = { schema_version: "byq-acp-tool-ingress-receipt.v1",
      mcp_request_id: ingressMode === "invalid" ? "f".repeat(32) : body?.mcp_request_id,
      root_run_id: claims.root_run_id, runtime_boot_id: claims.runtime_boot_id,
      native_root_session_id: claims.native_root_session_id,
      native_agent_session_id: claims.native_agent_session_id, native_parent_session_id: null,
      origin: "root", depth: 0, tool_name: body?.tool_name,
      agent_run_id: rootBound ? runId : (bootstrap ? null : runId),
      sequence: ++ingressSequence, event_sha256: "a".repeat(64) };
    observedIngress.set(String(body?.mcp_request_id), {
      receipt, arguments: body?.arguments as Record<string, unknown>,
    });
    send(200, receipt);
    return;
  }

  if (req.url === "/internal/acp/agent-authorize") {
    assert.equal(req.method, "POST");
    assert.equal(entry.headers.get("authorization"), `Bearer ${backendProof}`);
    assert.equal(entry.headers.get("x-byq-owner-principal"), claims.owner_principal);
    assert.equal(entry.headers.get("x-byq-root-run-id"), claims.root_run_id);
    assert.equal(entry.headers.get("x-byq-runtime-boot-id"), claims.runtime_boot_id);
    assert.equal(entry.headers.get("x-byq-acp-native-agent-session-id"), claims.native_agent_session_id);
    assert.equal(entry.headers.get("x-byq-acp-native-root-session-id"), claims.native_root_session_id);
    assert.equal(entry.headers.get("x-byq-acp-origin"), "root");
    assert.equal(entry.headers.get("x-byq-acp-depth"), "0");
    assert.deepEqual(body && Object.keys(body).sort(), ["arguments", "mcp_request_id", "schema_version"]);
    assert.equal(body?.schema_version, "byq-acp-agent-authorize.v1");
    const observed = observedIngress.get(String(body?.mcp_request_id));
    assert.ok(observed, "private authorization must refer to a previously persisted ingress");
    assert.equal(observed.receipt.tool_name, "byq_agent_authorize");
    assert.equal(observed.receipt.agent_run_id,
      (body?.arguments as Record<string, unknown>).run_id,
      "the authorization AgentRun must be the AgentRun bound to this native Agent ingress");
    assert.deepEqual(body?.arguments, observed.arguments,
      "Backend authorization input must match the exact observed arguments");
    const authorization = { authorized: authorizationDenialMode === "ok",
      decision: authorizationDenialMode === "ok" ? "allowed" : "denied",
      run_id: runId, role_id: "market_researcher",
      action: (body?.arguments as Record<string, unknown>).action };
    if (authorizationDenialMode === "missing") {
      send(200, { status: "denied", authorization });
      return;
    }
    if (authorizationDenialMode === "ok") {
      send(200, { status: "ok", authorization });
      return;
    }
    const refusalBase = { schema_version: "byq-acp-authorization-denial-receipt.v1",
      mcp_request_id: body?.mcp_request_id, root_run_id: observed.receipt.root_run_id,
      runtime_boot_id: observed.receipt.runtime_boot_id,
      native_agent_session_id: observed.receipt.native_agent_session_id,
      agent_run_id: observed.receipt.agent_run_id, tool_name: "byq_agent_authorize",
      arguments_sha256: sha256(observed.arguments), event_sha256: observed.receipt.event_sha256,
      reason: "role_tool_not_allowed", outcome: "denied", audit_id: "agent_audit_" + "8".repeat(32) };
    const refusalReceipt = { ...refusalBase, receipt_sha256: sha256(refusalBase) };
    send(200, { status: "denied", authorization, refusal_receipt: refusalReceipt });
    return;
  }

  if (req.url === "/internal/acp/tool-ingress-abort") {
    assert.equal(req.method, "POST");
    assert.equal(entry.headers.get("authorization"), `Bearer ${backendProof}`);
    assert.equal(body?.schema_version, "byq-acp-tool-ingress-abort.v1");
    assert.equal(body?.root_run_id, claims.root_run_id);
    assert.equal(body?.runtime_boot_id, claims.runtime_boot_id);
    assert.equal(body?.native_agent_session_id, claims.native_agent_session_id);
    assert.match(String(body?.mcp_request_id), /^[0-9a-f]{32}$/);
    send(200, { schema_version: "byq-acp-tool-ingress-abort-receipt.v1",
      mcp_request_id: body?.mcp_request_id, root_run_id: claims.root_run_id,
      runtime_boot_id: claims.runtime_boot_id,
      native_root_session_id: claims.native_root_session_id,
      native_agent_session_id: claims.native_agent_session_id,
      native_parent_session_id: null, origin: "root", depth: 0,
      tool_name: body?.tool_name, arguments_sha256: "a".repeat(64),
      sequence: ++ingressSequence, event_sha256: "b".repeat(64),
      outcome: "aborted_before_dispatch", abort_sha256: "c".repeat(64) });
    return;
  }

  if (req.url === "/internal/acp/tool-ingress-settle") {
    assert.equal(req.method, "POST");
    assert.equal(entry.headers.get("authorization"), `Bearer ${backendProof}`);
    assert.equal(body?.schema_version, "byq-acp-tool-ingress-settle.v1");
    assert.equal(body?.root_run_id, claims.root_run_id);
    assert.equal(body?.runtime_boot_id, claims.runtime_boot_id);
    assert.equal(body?.native_root_session_id, claims.native_root_session_id);
    assert.equal(body?.native_agent_session_id, claims.native_agent_session_id);
    assert.equal(body?.native_parent_session_id, null);
    assert.equal(body?.origin, "root");
    assert.equal(body?.depth, 0);
    assert.match(String(body?.mcp_request_id), /^[0-9a-f]{32}$/);
    assert.ok(Number.isSafeInteger(body?.sequence) && Number(body?.sequence) > 0);
    assert.match(String(body?.event_sha256), /^[0-9a-f]{64}$/);
    assert.ok(["settled", "unknown", "denied"].includes(String(body?.outcome)));
    if (body?.outcome === "denied") {
      assert.ok(body.refusal_receipt && typeof body.refusal_receipt === "object",
        "denied settlement requires the private exact Backend refusal receipt");
      const refusalReceipt = body.refusal_receipt as Record<string, unknown>;
      assert.equal(refusalReceipt.mcp_request_id, body.mcp_request_id);
      assert.equal(refusalReceipt.event_sha256, body.event_sha256);
    } else {
      assert.equal(body?.refusal_receipt, undefined,
        "existing settled and unknown requests retain their previous closed shape");
    }
    settlements.push(body!);
    const commonReceipt = { schema_version: "byq-acp-tool-ingress-settle-receipt.v1",
      mcp_request_id: body?.mcp_request_id, root_run_id: claims.root_run_id,
      runtime_boot_id: claims.runtime_boot_id, native_agent_session_id: claims.native_agent_session_id,
      tool_name: body?.tool_name, sequence: body?.sequence,
      event_sha256: settlementMode === "invalid" ? "f".repeat(64) : body?.event_sha256,
      outcome: body?.outcome };
    if (body?.outcome === "denied") {
      const refusalReceipt = body.refusal_receipt as Record<string, unknown>;
      const refusalReceiptSha = String(refusalReceipt.receipt_sha256);
      const settlementFields = { mcp_request_id: body.mcp_request_id, root_run_id: body.root_run_id,
        runtime_boot_id: body.runtime_boot_id, native_agent_session_id: body.native_agent_session_id,
        tool_name: body.tool_name, sequence: body.sequence, event_sha256: body.event_sha256,
        outcome: "denied", refusal_receipt_sha256: refusalReceiptSha };
      send(200, { ...commonReceipt, refusal_receipt_sha256: refusalReceiptSha,
        settlement_sha256: sha256(settlementFields) });
    } else {
      send(200, { ...commonReceipt, settlement_sha256: "9".repeat(64) });
    }
    return;
  }

  if (req.url === "/internal/acp/domain-call-observe") {
    assert.equal(entry.headers.get("authorization"), `Bearer ${backendProof}`);
    assert.equal(entry.headers.get("x-byq-owner-principal"), claims.owner_principal);
    assert.equal(entry.headers.get("x-byq-workspace-id"), claims.workspace_id);
    assert.equal(entry.headers.get("x-byq-actor-principal"), claims.actor_principal);
    assert.equal(entry.headers.get("x-byq-trace-id"), claims.trace_id);
    assert.equal(entry.headers.get("x-byq-session-id"), claims.session_id);
    assert.equal(entry.headers.get("x-byq-dsh-run-id"), claims.dsh_run_id);
    assert.equal(entry.headers.get("x-byq-runtime-boot-id"), claims.runtime_boot_id);
    assert.equal(entry.headers.get("x-byq-root-run-id"), claims.root_run_id);
    assert.equal(body?.schema_version, "byq-acp-domain-call-observe.v1");
    assert.equal(body?.native_agent_session_id, claims.native_agent_session_id);
    if (observationMode === "invalid") {
      send(200, { schema_version: "byq-acp-domain-call-observation-receipt.v1",
        mcp_request_id: "f".repeat(32), root_run_id: claims.root_run_id,
        sequence: 1, event_sha256: "e".repeat(64) });
      return;
    }
    send(200, { schema_version: "byq-acp-domain-call-observation-receipt.v1",
      mcp_request_id: body?.mcp_request_id, root_run_id: claims.root_run_id,
      sequence: 1, event_sha256: "e".repeat(64) });
    return;
  }

  if (req.url === "/v1/agents/runs" && req.method === "POST") {
    assert.equal(entry.headers.get("authorization"), `Bearer ${backendProof}`);
    assert.equal(entry.headers.get("x-byq-acp-native-agent-session-id"), claims.native_agent_session_id);
    assert.equal(entry.headers.get("x-byq-acp-native-root-session-id"), claims.native_root_session_id);
    assert.equal(entry.headers.get("x-byq-acp-native-parent-session-id"), "");
    assert.equal(entry.headers.get("x-byq-acp-origin"), "root");
    assert.equal(entry.headers.get("x-byq-acp-depth"), "0");
    assert.equal(entry.headers.get("x-byq-owner-principal"), claims.owner_principal,
      "signed claims replace all spoofed caller headers");
    assert.equal(entry.headers.get("x-byq-root-run-id"), claims.root_run_id);
    assert.equal(body?.parent_run_id, undefined);
    send(201, { run: { run_id: runId, parent_run_id: null, status: "active" } });
    return;
  }
  if (req.url?.startsWith("/v1/agents/runs/registration-receipt?")) {
    assert.equal(req.method, "GET");
    assert.equal(entry.headers.get("authorization"), `Bearer ${backendProof}`);
    send(200, { run: { run_id: runId, parent_run_id: null, status: "active" } });
    return;
  }
  if (req.url === "/internal/acp/agent-bind") {
    assert.equal(entry.headers.get("authorization"), `Bearer ${backendProof}`);
    assert.deepEqual(body, { schema_version: "byq-acp-agent-bind.v1", root_run_id: claims.root_run_id,
      runtime_boot_id: claims.runtime_boot_id, native_root_session_id: claims.native_root_session_id,
      native_agent_session_id: claims.native_agent_session_id, native_parent_session_id: null,
      origin: "root", depth: 0, agent_run_id: runId, parent_run_id: null });
    rootBound = true;
    send(200, bindReceipt);
    return;
  }
  if (req.url?.startsWith("/internal/acp/agent-binding?")) {
    assert.equal(req.method, "GET");
    assert.equal(entry.headers.get("authorization"), `Bearer ${backendProof}`);
    send(200, { schema_version: "byq-acp-agent-binding-status.v1", root_run_id: claims.root_run_id,
      runtime_boot_id: claims.runtime_boot_id, native_agent_session_id: claims.native_agent_session_id,
      status: bindingStatus, ...(bindingStatus === "bound" ? { receipt: bindReceipt } : {}) });
    return;
  }
  if (req.method === "GET" && req.url === "/v1/agent/data-demand-notifications") {
    assert.equal(entry.headers.get("x-byq-root-run-id"), claims.root_run_id);
    send(200, { notifications: [] });
    return;
  }
  if (req.method === "GET" && req.url === "/v1/agent/research-context") {
    assert.equal(entry.headers.get("x-byq-root-run-id"), claims.root_run_id);
    send(200, { schema_version: "research-task-context.v1", status: "available", has_more: false, tasks: [] });
    return;
  }
  if (req.url === "/v1/research/strategies/validate") {
    if (domainMode === "reject422") {
      send(422, { detail: { schema_version: "domain-call-admission.v1", state: "correctable_failure",
        reason: "domain_validation_failed", validation: { schema_version: "strategy-validation-problem.v1",
          field: "strategy.script", code: "invalid_strategy", repair_limit: 1 } } });
      return;
    }
    if (domainMode === "conflict409") {
      send(409, { detail: "request conflicts with an existing mutable result" });
      return;
    }
    if (domainMode === "timeout") {
      await delay(8_500);
      send(200, { artifact: { artifact_id: "artifact_" + "f".repeat(32), status: "validated" } });
      return;
    }
    send(200, { artifact: { artifact_id: "artifact_" + "e".repeat(32), status: "validated" } });
    return;
  }
  send(404, { detail: "not found" });
});
await new Promise<void>(resolve => backend.listen(0, "127.0.0.1", resolve));
const backendAddress = backend.address();
assert.ok(backendAddress && typeof backendAddress === "object");
const portReserve = createServer();
await new Promise<void>(resolve => portReserve.listen(0, "127.0.0.1", resolve));
const serviceAddress = portReserve.address();
assert.ok(serviceAddress && typeof serviceAddress === "object");
await new Promise<void>(resolve => portReserve.close(() => resolve()));
const mcp = spawn(process.execPath, ["dist/src/server.js"], { env: { ...process.env,
  PORT: String(serviceAddress.port),
  BYQ_MCP_TOKEN: legacyToken,
  BYQ_MCP_ACP_DISCOVERY_TOKEN: discoveryToken,
  BYQ_MCP_ACP_SIGNING_KEY: signingKey,
  BYQ_MCP_BACKEND_PROOF_TOKEN: backendProof,
  BYQ_BACKEND_URL: `http://127.0.0.1:${backendAddress.port}`,
}, stdio: "ignore" });
const endpoint = `http://127.0.0.1:${serviceAddress.port}/mcp/v1`;
const auth = (token: string) => ({ token: async () => token });
const client = (token: string, headers: Record<string, string> = {}) => {
  const value = new Client({ name: "acp-ingress-test", version: "1.0.0" });
  return { value, connect: () => value.connect(new StreamableHTTPClientTransport(new URL(endpoint), {
    authProvider: auth(token), requestInit: { headers },
  })) };
};
const discovery = client(discoveryToken, {
  "x-byq-continuation-reservation": "continuation_" + "f".repeat(32),
  "x-byq-root-run-id": "f".repeat(32),
});
const acp = client(acpBearer(), {
  "x-byq-owner-principal": "mallory", "x-byq-workspace-id": "workspace_attacker",
  "x-byq-actor-principal": "mallory", "x-byq-trace-id": "fake-trace",
  "x-byq-session-id": "fake-session", "x-byq-dsh-run-id": "fake-generation",
  "x-byq-runtime-boot-id": "f".repeat(32), "x-byq-root-run-id": "f".repeat(32),
  "x-byq-acp-observation-id": "f".repeat(32),
});
const clients = [discovery.value, acp.value];
try {
  let ready = false;
  for (let attempt = 0; attempt < 50; attempt += 1) {
    ready = await fetch(`http://127.0.0.1:${serviceAddress.port}/healthz`).then(response => response.ok).catch(() => false);
    if (ready) break;
    await delay(50);
  }
  assert.ok(ready, "MCP service must be ready with isolated discovery and signed Agent credentials");

  await discovery.connect();
  const listed = await discovery.value.listTools();
  assert.ok(listed.tools.some(tool => tool.name === "byq_strategy_validate"));
  const beforeDiscoveryCall = requests.length;
  await discovery.value.callTool({ name: "byq_strategy_validate", arguments: {
    task_id: "task-wire", agent_run_id: "run-wire", idempotency_key: "discovery-denied",
    trace_id: "trace-wire", strategy: { strategy_id: "synthetic", name: "Synthetic", category: "custom", script: "pass" },
  } }).catch(() => undefined);
  assert.equal(requests.length, beforeDiscoveryCall,
    "discovery bearer must be rejected before any continuation or protected tool handler");

  await acp.connect();
  const acpTools = await acp.value.listTools();
  assert.ok(acpTools.tools.some(tool => tool.name === "byq_agent_run_start"));
  const beforeBootstrap = requests.length;
  const bootstrap = await acp.value.callTool({ name: "byq_agent_context", arguments: {} });
  assert.equal(bootstrap.isError, false);
  const bootstrapIngress = requests.find(request => request.path === "/internal/acp/tool-ingress-observe"
    && request.body?.tool_name === "byq_agent_context");
  const bootstrapForward = requests.find(request => request.path === "/v1/agent/data-demand-notifications");
  assert.ok(bootstrapIngress && bootstrapForward);
  assert.ok(requests.indexOf(bootstrapIngress) >= beforeBootstrap
    && requests.indexOf(bootstrapIngress) < requests.indexOf(bootstrapForward),
    "pre-bind bootstrap calls require durable null-AgentRun ingress before Backend forwarding");
  assert.equal(bootstrapIngress.body?.tool_name, "byq_agent_context");
  assert.equal(settlements.find(entry => entry.mcp_request_id === bootstrapIngress.body?.mcp_request_id)?.outcome,
    "settled");
  const started = await acp.value.callTool({ name: "byq_agent_run_start", arguments: {
    role_id: "quant_orchestrator", idempotency_key: "acp-root-registration",
  } });
  assert.equal(started.isError, false);
  const registrationIndex = requests.findIndex(request => request.path === "/v1/agents/runs");
  const bindIndex = requests.findIndex(request => request.path === "/internal/acp/agent-bind");
  assert.ok(registrationIndex >= 0 && bindIndex > registrationIndex,
    "native binding follows the existing Backend registration receipt and precedes success to the caller");
  assert.equal(requests.filter(request => request.path === "/internal/acp/tool-ingress-observe"
    && request.body?.tool_name === "byq_agent_run_start").length, 0,
  "AgentRun start uses pending-to-bound registration instead of generic tool ingress");

  const deniedAuthorizationArgs = { run_id: runId, action: "byq_ml_training_create" };
  const deniedAuthorization = await acp.value.callTool({ name: "byq_agent_authorize",
    arguments: deniedAuthorizationArgs });
  assert.equal(deniedAuthorization.isError, true,
    "a proved role refusal remains a model-visible authorization error");
  const deniedAuthorizationText = deniedAuthorization.content.find(item => item.type === "text");
  assert.ok(deniedAuthorizationText && deniedAuthorizationText.type === "text");
  const deniedAuthorizationPayload = JSON.parse(deniedAuthorizationText.text) as Record<string, unknown>;
  assert.deepEqual(deniedAuthorizationPayload.backend,
    { status: "agent_forbidden", http_status: 403 },
    "the existing public tool error shape is preserved");
  assert.equal(JSON.stringify(deniedAuthorizationPayload).includes("refusal_receipt"), false,
    "the private proof is never exposed to the model");
  const deniedPrivateRequest = requests.slice().reverse().find(request =>
    request.path === "/internal/acp/agent-authorize");
  assert.ok(deniedPrivateRequest?.body);
  const deniedRequestId = String(deniedPrivateRequest.body.mcp_request_id);
  const deniedIngressIndex = requests.findIndex(request => request.path === "/internal/acp/tool-ingress-observe"
    && request.body?.mcp_request_id === deniedRequestId);
  const deniedPrivateIndex = requests.findIndex(request => request.path === "/internal/acp/agent-authorize"
    && request.body?.mcp_request_id === deniedRequestId);
  assert.ok(deniedIngressIndex >= 0 && deniedPrivateIndex > deniedIngressIndex,
    "the trusted authorization endpoint runs only after the exact ingress was observed");
  assert.equal(requests.filter(request => request.path === "/v1/agents/authorize").length, 0,
    "ordinary ACP authorization never falls back to the public endpoint");
  assert.equal(settlements.find(entry => entry.mcp_request_id === deniedRequestId)?.outcome, "denied",
    "a valid receipt is followed by the exact negative Backend settlement ACK");

  authorizationDenialMode = "ok";
  const allowedAuthorizationArgs = { run_id: runId, action: "byq_research_get" };
  const allowedAuthorization = await acp.value.callTool({ name: "byq_agent_authorize",
    arguments: allowedAuthorizationArgs });
  assert.equal(allowedAuthorization.isError, false,
    "a normal authorization query remains a successful MCP result");
  const allowedAuthorizationText = allowedAuthorization.content.find(item => item.type === "text");
  assert.ok(allowedAuthorizationText && allowedAuthorizationText.type === "text");
  const allowedAuthorizationPayload = JSON.parse(allowedAuthorizationText.text) as Record<string, unknown>;
  assert.equal(allowedAuthorizationPayload.status, "ok");
  assert.deepEqual(allowedAuthorizationPayload.authorization, { authorized: true,
    decision: "allowed", run_id: runId, role_id: "market_researcher", action: "byq_research_get" });
  const allowedIngress = requests.slice().reverse().find(request =>
    request.path === "/internal/acp/tool-ingress-observe"
      && (request.body?.arguments as Record<string, unknown> | undefined)?.action === "byq_research_get");
  assert.ok(allowedIngress?.body);
  assert.equal(settlements.find(entry => entry.mcp_request_id === allowedIngress.body?.mcp_request_id)?.outcome,
    "settled", "the existing successful authorization query keeps its normal settled state");

  authorizationDenialMode = "missing";
  const unprovedAuthorization = await acp.value.callTool({ name: "byq_agent_authorize",
    arguments: { ...deniedAuthorizationArgs, action: "byq_backtest_task_execute" } });
  assert.equal(unprovedAuthorization.isError, true);
  const unprovedText = unprovedAuthorization.content.find(item => item.type === "text");
  assert.ok(unprovedText && unprovedText.type === "text");
  assert.equal((JSON.parse(unprovedText.text) as { backend?: { status?: unknown } }).backend?.status,
    "acp_authorization_outcome_unknown",
    "a 200 denial without its exact durable refusal receipt remains unknown");
  const unprovedIngress = requests.slice().reverse().find(request =>
    request.path === "/internal/acp/tool-ingress-observe"
      && (request.body?.arguments as Record<string, unknown> | undefined)?.action === "byq_backtest_task_execute");
  assert.ok(unprovedIngress?.body);
  assert.equal(settlements.find(entry => entry.mcp_request_id === unprovedIngress.body?.mcp_request_id)?.outcome,
    "unknown", "missing refusal evidence cannot be promoted to a known denial");
  authorizationDenialMode = "valid";

  const genericCountBeforeLocalCall = requests.filter(request => request.path === "/internal/acp/tool-ingress-observe").length;
  const localCard = await acp.value.callTool({ name: "byq_workflow_card_propose", arguments: {
    kind: "strategy_draft", title: "草稿", summary: "本地投影", name: "momentum", validation_status: "draft",
  } });
  assert.equal(localCard.isError, false, "local-only Product tools remain available to signed ACP Agents");
  assert.equal(requests.filter(request => request.path === "/internal/acp/tool-ingress-observe").length,
    genericCountBeforeLocalCall, "local-only callbacks do not create Backend ingress records");

  const readOnlyRejection = await acp.value.callTool({ name: "byq_agent_roles", arguments: {} });
  assert.equal(readOnlyRejection.isError, true, "the synthetic Backend returns a definite read-only 404");
  const readOnlyIngress = requests.slice().reverse().find(request => request.path === "/internal/acp/tool-ingress-observe"
    && request.body?.tool_name === "byq_agent_roles");
  assert.ok(readOnlyIngress);
  assert.equal(settlements.find(entry => entry.mcp_request_id === readOnlyIngress.body?.mcp_request_id)?.outcome,
    "settled", "only the explicit read-only allowlist settles a completed read error");

  const actionArgs = { task_id: "task-wire", agent_run_id: "model-supplied-run",
    idempotency_key: "acp-strategy-validation", trace_id: "untrusted-trace",
    strategy: { strategy_id: "synthetic", name: "Synthetic", category: "custom", script: "pass" } };
  const beforeInvalidArgs = requests.filter(request => request.path === "/internal/acp/domain-call-observe").length;
  const beforeInvalidGenericArgs = requests.filter(request => request.path === "/internal/acp/tool-ingress-observe").length;
  const invalidArgs = await acp.value.callTool({ name: "byq_strategy_validate", arguments: { task_id: "invalid" } }).catch(() => ({ isError: true }));
  assert.equal(invalidArgs.isError, true);
  assert.equal(requests.filter(request => request.path === "/internal/acp/domain-call-observe").length, beforeInvalidArgs,
    "schema-invalid arguments never reach actual handler ingress observation");
  assert.equal(requests.filter(request => request.path === "/internal/acp/tool-ingress-observe").length, beforeInvalidGenericArgs,
    "schema-invalid arguments never reach generic Backend ingress observation");
  const action = await acp.value.callTool({ name: "byq_strategy_validate", arguments: actionArgs });
  assert.equal(action.isError, false);
  const actionIngress = requests.find(request => request.path === "/internal/acp/tool-ingress-observe"
    && request.body?.tool_name === "byq_strategy_validate");
  const observation = requests.find(request => request.path === "/internal/acp/domain-call-observe");
  const claim = requests.find(request => request.path === "/v1/research/strategies/validate");
  assert.ok(actionIngress?.body && observation?.body);
  assert.ok(claim?.body);
  assert.equal(observation.body?.action, "byq_strategy_validate");
  assert.deepEqual(observation.body?.arguments, actionArgs,
    "the observation is made from the SDK-validated call arguments before the domain handler");
  assert.equal(claim.headers.get("x-byq-acp-observation-id"), observation.body?.mcp_request_id,
    "the exact durable observation receipt ID must accompany the Backend claim request");
  assert.equal(claim.headers.get("x-byq-owner-principal"), claims.owner_principal);
  assert.equal(claim.headers.get("x-byq-workspace-id"), claims.workspace_id);
  assert.equal(claim.headers.get("x-byq-root-run-id"), claims.root_run_id);
  assert.equal(claim.headers.get("x-byq-runtime-boot-id"), claims.runtime_boot_id);
  assert.equal(claim.headers.get("x-byq-acp-observation-id") === "f".repeat(32), false,
    "caller-supplied observation identity must be replaced by the receipt");
  const backendCallIndex = requests.indexOf(claim);
  const observationIndex = requests.indexOf(observation);
  const settlementIndex = requests.findIndex(request => request.path === "/internal/acp/tool-ingress-settle"
    && request.body?.mcp_request_id === actionIngress?.body?.mcp_request_id);
  assert.ok(requests.indexOf(actionIngress) < observationIndex && observationIndex < backendCallIndex,
    "generic ingress and specialized observation must precede the domain claim");
  assert.ok(backendCallIndex < settlementIndex,
    "the callback result is returned only after the exact generic ingress is durably settled");
  assert.equal(settlements.find(entry => entry.mcp_request_id === actionIngress?.body?.mcp_request_id)?.outcome,
    "settled");
  assert.equal(claim.body?.trace_id, claims.trace_id, "signed trace identity overrides model input");
  assert.equal(claim.body?.agent_run_id, actionArgs.agent_run_id,
    "MCP preserves the model field for Backend validation without treating it as identity");

  domainMode = "reject422";
  const beforeValidationReject = requests.filter(request => request.path === "/v1/research/strategies/validate").length;
  const rejectedValidation = await acp.value.callTool({ name: "byq_strategy_validate", arguments: {
    ...actionArgs, idempotency_key: "definite-validation-rejection",
  } });
  assert.equal(rejectedValidation.isError, true);
  const validationClaim = requests.slice().reverse().find(request => request.path === "/v1/research/strategies/validate");
  assert.ok(validationClaim);
  assert.equal(requests.filter(request => request.path === "/v1/research/strategies/validate").length,
    beforeValidationReject + 1);
  const validationIngress = requests.slice().reverse().find(request => request.path === "/internal/acp/tool-ingress-observe"
    && request.body?.tool_name === "byq_strategy_validate");
  assert.ok(validationIngress);
  const validationSettlement = settlements.find(entry => entry.mcp_request_id === validationIngress.body?.mcp_request_id);
  assert.equal(validationSettlement?.outcome, "settled",
    "the exact persisted correctable-failure 422 is a known terminal validation outcome");
  domainMode = "success";

  domainMode = "conflict409";
  const beforeConflictClaim = requests.filter(request => request.path === "/v1/research/strategies/validate").length;
  const conflictResult = await acp.value.callTool({ name: "byq_strategy_validate", arguments: {
    ...actionArgs, idempotency_key: "mutable-conflict-remains-unknown",
  } });
  assert.equal(conflictResult.isError, true);
  const conflictClaimCount = requests.filter(request => request.path === "/v1/research/strategies/validate").length;
  assert.equal(conflictClaimCount, beforeConflictClaim + 1);
  const conflictIngress = requests.slice().reverse().find(request => request.path === "/internal/acp/tool-ingress-observe"
    && request.body?.tool_name === "byq_strategy_validate"
    && (request.body?.arguments as Record<string, unknown>)?.idempotency_key === "mutable-conflict-remains-unknown");
  assert.ok(conflictIngress);
  assert.equal(settlements.find(entry => entry.mcp_request_id === conflictIngress.body?.mcp_request_id)?.outcome,
    "unknown", "a mutating 409 without the exact bounded validation receipt stays unknown");
  domainMode = "success";

  domainMode = "timeout";
  const beforeTimeoutClaim = requests.filter(request => request.path === "/v1/research/strategies/validate").length;
  const timeoutResult = await acp.value.callTool({ name: "byq_strategy_validate", arguments: {
    ...actionArgs, idempotency_key: "transport-timeout-unknown",
  } });
  assert.equal(timeoutResult.isError, false,
    "the existing write helper preserves its explicit outcome_unknown result contract");
  const timeoutContent = timeoutResult.content.find(item => item.type === "text");
  assert.ok(timeoutContent && timeoutContent.type === "text");
  assert.equal((JSON.parse(timeoutContent.text) as { status?: unknown }).status, "outcome_unknown");
  const timeoutClaimCount = requests.filter(request => request.path === "/v1/research/strategies/validate").length;
  assert.equal(timeoutClaimCount, beforeTimeoutClaim + 1,
    "a timed out business request is never replayed by the MCP wrapper");
  const timeoutIngress = requests.slice().reverse().find(request => request.path === "/internal/acp/tool-ingress-observe"
    && request.body?.tool_name === "byq_strategy_validate");
  assert.ok(timeoutIngress);
  const timeoutSettlement = settlements.find(entry => entry.mcp_request_id === timeoutIngress.body?.mcp_request_id);
  assert.equal(timeoutSettlement?.outcome, "unknown",
    "transport timeout after a domain write stays unknown and cannot be treated as no effect");
  domainMode = "success";

  settlementMode = "invalid";
  const beforeBadSettlementClaim = requests.filter(request => request.path === "/v1/research/strategies/validate").length;
  const badSettlement = await acp.value.callTool({ name: "byq_strategy_validate", arguments: {
    ...actionArgs, idempotency_key: "malformed-settlement-receipt",
  } });
  assert.equal(badSettlement.isError, true, "malformed settlement receipt fails closed to the caller");
  assert.equal(requests.filter(request => request.path === "/v1/research/strategies/validate").length,
    beforeBadSettlementClaim + 1, "settlement mismatch never causes handler replay");
  assert.match(JSON.stringify(badSettlement), /acp_ingress_settlement_unknown/);
  settlementMode = "valid";

  const bindCount = requests.filter(request => request.path === "/internal/acp/agent-bind").length;
  const receiptOnly = await acp.value.callTool({ name: "byq_agent_run_start", arguments: {
    role_id: "quant_orchestrator", idempotency_key: "acp-root-registration", receipt_only: true,
  } });
  assert.equal(receiptOnly.isError, false);
  assert.equal(requests.filter(request => request.path === "/internal/acp/agent-bind").length, bindCount,
    "receipt-only outcome reconciliation never repeats or finalizes a bind");

  observationMode = "invalid";
  const beforeInvalidObservationClaim = requests.filter(request => request.path === "/v1/research/strategies/validate").length;
  const rejectedObservation = await acp.value.callTool({ name: "byq_strategy_validate", arguments: {
    ...actionArgs, idempotency_key: "invalid-observation-receipt",
  } });
  assert.equal(rejectedObservation.isError, true);
  assert.equal(requests.filter(request => request.path === "/v1/research/strategies/validate").length,
    beforeInvalidObservationClaim, "malformed or mismatched receipt blocks the domain handler");

  ingressMode = "invalid";
  const beforeGenericFailure = requests.filter(request => request.path === "/v1/market/daily").length;
  const rejectedGenericReceipt = await acp.value.callTool({ name: "byq_market_daily", arguments: {} });
  assert.equal(rejectedGenericReceipt.isError, true);
  assert.equal(requests.filter(request => request.path === "/v1/market/daily").length, beforeGenericFailure,
    "malformed generic receipt blocks an ordinary Backend-facing tool before its handler");
  const badIngress = requests.slice().reverse().find(request => request.path === "/internal/acp/tool-ingress-observe"
    && request.body?.tool_name === "byq_market_daily");
  const abort = requests.slice().reverse().find(request => request.path === "/internal/acp/tool-ingress-abort"
    && request.body?.tool_name === "byq_market_daily");
  assert.ok(badIngress && abort);
  assert.equal(abort.body?.mcp_request_id, badIngress.body?.mcp_request_id,
    "lost or invalid observe receipt is aborted using the exact original request ID before handler entry");
  assert.deepEqual(abort.body?.arguments, badIngress.body?.arguments);
  ingressMode = "valid";

  bindingStatus = "pending";
  const pendingReconcile = await acp.value.callTool({ name: "byq_agent_run_start", arguments: {
    role_id: "quant_orchestrator", idempotency_key: "acp-root-registration", receipt_only: true,
  } });
  assert.equal(pendingReconcile.isError, true, "pending bind outcome remains fail-closed");
  assert.equal(requests.filter(request => request.path === "/internal/acp/agent-bind").length, bindCount,
    "pending receipt-only reconciliation does not auto-bind");

  const invalid = client("byq-acp-v1.not-a-valid-signed-identity");
  const beforeInvalidIdentity = requests.length;
  let invalidRejected = false;
  try { await invalid.connect(); } catch { invalidRejected = true; }
  assert.ok(invalidRejected, "invalid per-Agent identity must fail at ingress before tool dispatch");
  assert.equal(requests.length, beforeInvalidIdentity, "invalid Agent identity must not reach Backend");
  await invalid.value.close().catch(() => undefined);

  const legacy = client(legacyToken, {
    "x-byq-owner-principal": "alice", "x-byq-workspace-id": "workspace_alice",
    "x-byq-actor-principal": "byq-product-agent-session-root", "x-byq-trace-id": "trace-root",
    "x-byq-session-id": "session-root", "x-byq-dsh-run-id": "generation-root",
    "x-byq-runtime-boot-id": claims.runtime_boot_id, "x-byq-root-run-id": claims.root_run_id,
  });
  await legacy.connect();
  const beforeLegacy = requests.length;
  const legacyResult = await legacy.value.callTool({ name: "byq_strategy_validate", arguments: {
    ...actionArgs, idempotency_key: "legacy-rollback-path",
  } });
  assert.equal(legacyResult.isError, false, "legacy carrier remains available for exact rollback compatibility");
  const legacyClaim = requests.slice(beforeLegacy).find(request => request.path === "/v1/research/strategies/validate");
  assert.ok(legacyClaim);
  assert.equal(legacyClaim.headers.get("x-byq-acp-observation-id"), null,
    "legacy carrier remains distinct and does not borrow ACP global fallback identity");

  console.log("ACP MCP ingress: discovery-only, signed Agent context, generic and specialized durable observation, two-phase settlement and exact bind reconciliation PASS");
} finally {
  for (const client of clients) await client.close().catch(() => undefined);
  mcp.kill("SIGTERM");
  await new Promise<void>(resolve => {
    if (mcp.exitCode !== null) resolve();
    else mcp.once("exit", () => resolve());
  });
  await new Promise<void>(resolve => backend.close(() => resolve()));
}
