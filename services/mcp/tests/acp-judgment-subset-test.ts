// ADR-0097: exercise the dedicated judgment endpoint with synthetic credentials.
// Default calls deny before Backend; explicit admission checks a denied call
// and one bounded read through a synthetic Backend receipt.
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { spawn, type ChildProcess } from "node:child_process";
import { createServer, type Server } from "node:http";
import { setTimeout as delay } from "node:timers/promises";
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";
import {
  classifyMcpBearer,
  deriveAcpJudgmentRootSigningKey,
  isAcpJudgmentSigningKeyDistinct,
  verifyAcpJudgmentRootBearer,
  type AcpAgentClaims,
  type AcpJudgmentRootClaims,
} from "../src/acp-auth.js";

const READ_ONLY = [
  "byq_agent_context",
  "byq_backtest_analysis_get",
  "byq_backtest_task_get",
  "byq_research_get",
  "byq_research_stage_input_get",
];
const judgmentKey = "synthetic-adr0097-judgment-signing-key-at-least-32-bytes";
const adapterVectorMaster = "synthetic-judgment-master-with-at-least-32-bytes";
const productKey = "synthetic-product-acp-signing-key-at-least-32-bytes";
const now = Date.now();

const judgmentClaims: AcpJudgmentRootClaims = {
  v: 1,
  aud: "byq-product-acp-judgment-mcp",
  root_run_id: "a".repeat(32),
  runtime_boot_id: "b".repeat(32),
  owner_principal: "alice",
  workspace_id: "workspace_alice",
  actor_principal: "byq-product-agent-judgment-session",
  trace_id: "trace-judgment",
  session_id: "judgment-session",
  dsh_run_id: "generation-judgment",
  native_root_session_id: "00000000-0000-4000-8000-000000000001",
  native_agent_session_id: "00000000-0000-4000-8000-000000000001",
  native_parent_session_id: null,
  origin: "root",
  depth: 0,
  task_id: "task_" + "c".repeat(32),
  call_identity: "byq-judgment-" + "d".repeat(32),
  expires_at: now + 60_000,
};

function canonical(value: Record<string, unknown>): string {
  const sorted: Record<string, unknown> = {};
  for (const key of Object.keys(value).sort()) sorted[key] = value[key];
  return JSON.stringify(sorted);
}

function sign(prefix: string, claims: Record<string, unknown>, key: string): string {
  const payload = Buffer.from(canonical(claims), "utf8");
  const mac = createHmac("sha256", Buffer.from(key, "utf8")).update(payload).digest();
  return `${prefix}.${payload.toString("base64url")}.${mac.toString("base64url")}`;
}

const judgmentRootKey = deriveAcpJudgmentRootSigningKey(judgmentKey, judgmentClaims);
assert.equal(judgmentRootKey, "9d443d02ad0a2a30e89e3c0b997a8617a1ef911cf3d0c8f106e896de922020ea",
  "judgment root key derivation must match the Adapter wire format");
assert.ok(judgmentRootKey);
assert.equal(deriveAcpJudgmentRootSigningKey(adapterVectorMaster, {
  ...judgmentClaims,
  task_id: "task_" + "a".repeat(32),
  call_identity: "byq-judgment-" + "b".repeat(32),
  root_run_id: "c".repeat(32),
  runtime_boot_id: "d".repeat(32),
  owner_principal: "alice",
  workspace_id: "workspace_1",
  session_id: "session_1",
  trace_id: "trace_1",
  dsh_run_id: "byqjudg-" + "e".repeat(32),
}), "5e46d07590d6aa0b71601a29453c008eeb770c28230b2720cb70212fda1025d7",
"MCP derivation must match the Runtime Adapter cross-language vector");
const judgmentToken = sign("byq-acp-judgment-v1", judgmentClaims as unknown as Record<string, unknown>, judgmentRootKey);
const productClaims: AcpAgentClaims = {
  ...judgmentClaims,
  aud: "byq-product-mcp",
  // Product ACP credentials do not carry judgment task/call claims.
  // Keep this object exact to the existing Product v1 shape.
} as AcpAgentClaims;
delete (productClaims as unknown as Record<string, unknown>).task_id;
delete (productClaims as unknown as Record<string, unknown>).call_identity;
const productAgentToken = sign("byq-acp-v1", productClaims as unknown as Record<string, unknown>, productKey);

assert.deepEqual(verifyAcpJudgmentRootBearer(judgmentToken, judgmentKey, now), judgmentClaims);
assert.equal(verifyAcpJudgmentRootBearer(judgmentToken, productKey, now), undefined,
  "judgment token must not verify under the Product ACP signing key");
assert.equal(verifyAcpJudgmentRootBearer(
  sign("byq-acp-judgment-v1", judgmentClaims as unknown as Record<string, unknown>, judgmentKey),
  judgmentKey,
  now,
), undefined, "the MCP master key must not directly sign a judgment token");
for (const crossScopeClaims of [
  { ...judgmentClaims, task_id: "task_" + "e".repeat(32) },
  { ...judgmentClaims, call_identity: "byq-judgment-" + "e".repeat(32) },
  { ...judgmentClaims, root_run_id: "f".repeat(32) },
  { ...judgmentClaims, owner_principal: "mallory" },
]) {
  const crossScopeToken = sign("byq-acp-judgment-v1",
    crossScopeClaims as unknown as Record<string, unknown>, judgmentRootKey);
  assert.equal(verifyAcpJudgmentRootBearer(crossScopeToken, judgmentKey, now), undefined,
    "a root-scoped key cannot mint a judgment token for another task, root, or owner");
}
const otherNativeAgentRunClaims = {
  ...judgmentClaims,
  native_root_session_id: "00000000-0000-4000-8000-000000000002",
  native_agent_session_id: "00000000-0000-4000-8000-000000000002",
};
const otherNativeAgentRunToken = sign("byq-acp-judgment-v1",
  otherNativeAgentRunClaims as unknown as Record<string, unknown>, judgmentRootKey);
assert.deepEqual(verifyAcpJudgmentRootBearer(otherNativeAgentRunToken, judgmentKey, now),
  otherNativeAgentRunClaims,
  "the agreed nine-field MAC scope does not bind the post-startup native AgentRun ID");
assert.equal(deriveAcpJudgmentRootSigningKey(judgmentKey,
  { ...judgmentClaims, task_id: "task_" + "c".repeat(31) } as AcpJudgmentRootClaims), undefined,
  "key derivation must reject malformed task scope");
assert.equal(isAcpJudgmentSigningKeyDistinct(judgmentKey, [productKey, "legacy-bearer"]), true);
assert.equal(isAcpJudgmentSigningKeyDistinct(judgmentKey, [judgmentKey]), false);
assert.equal(classifyMcpBearer(`Bearer ${judgmentToken}`, { legacyToken: judgmentToken }), undefined,
  "reserved judgment token prefix must not fall through to a static Product bearer");

async function reservePort(): Promise<number> {
  const reserve = createServer();
  await new Promise<void>(resolve => reserve.listen(0, "127.0.0.1", resolve));
  const address = reserve.address();
  assert.ok(address && typeof address === "object");
  const port = address.port;
  await new Promise<void>(resolve => reserve.close(() => resolve()));
  return port;
}

async function listen(server: Server): Promise<number> {
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  return address.port;
}

async function waitReady(endpoint: string): Promise<void> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (await fetch(endpoint + "/healthz").then(reply => reply.ok).catch(() => false)) return;
    await delay(50);
  }
  throw new Error(`MCP server did not start: ${endpoint}`);
}

async function listToolNames(port: number, token: string): Promise<string[]> {
  const endpoint = `http://127.0.0.1:${port}`;
  await waitReady(endpoint);
  const client = new Client({ name: "byq-acp-judgment-surface-test", version: "1.0.0" });
  try {
    await client.connect(new StreamableHTTPClientTransport(new URL(endpoint + "/mcp/v1"), {
      authProvider: { token: async () => token },
    }));
    const { tools } = await client.listTools();
    return tools.map(tool => tool.name).sort();
  } finally {
    await client.close();
  }
}

async function post(port: number, token: string, method: string): Promise<Response> {
  return fetch(`http://127.0.0.1:${port}/mcp/v1`, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params: {} }),
  });
}

async function stop(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null) return;
  child.kill("SIGTERM");
  await new Promise<void>(resolve => {
    if (child.exitCode !== null) resolve();
    else child.once("exit", () => resolve());
  });
}

async function exitCodeWithin(child: ChildProcess, timeoutMs: number): Promise<number | null> {
  if (child.exitCode !== null) return child.exitCode;
  return new Promise(resolve => {
    const timer = setTimeout(() => resolve(null), timeoutMs);
    child.once("exit", code => {
      clearTimeout(timer);
      resolve(code);
    });
  });
}

const cleanEnv = { ...process.env };
for (const name of [
  "PORT", "BYQ_MCP_TOKEN", "BYQ_MCP_READ_ONLY_SUBSET", "BYQ_MCP_READ_ONLY_PORT",
  "BYQ_MCP_READ_ONLY_TOKEN", "BYQ_MCP_ACP_DISCOVERY_TOKEN", "BYQ_MCP_ACP_SIGNING_KEY",
  "BYQ_MCP_ACP_JUDGMENT_SUBSET", "BYQ_MCP_ACP_JUDGMENT_PORT",
  "BYQ_MCP_ACP_JUDGMENT_SIGNING_KEY", "BYQ_MCP_BACKEND_PROOF_TOKEN",
  "BYQ_MCP_ACP_JUDGMENT_PROOF_TOKEN", "BYQ_MCP_ACP_JUDGMENT_ADMISSION_ENABLED",
]) delete cleanEnv[name];

const judgmentPort = await reservePort();
const readOnlyPort = await reservePort();
const productPort = await reservePort();
const readOnlyToken = "synthetic-read-only-static-bearer";
const productStaticToken = "synthetic-product-static-bearer";
const discoveryToken = "synthetic-product-discovery-bearer";
const backendProofToken = "synthetic-backend-proof-bearer";

const conflictingCredentialServer = spawn(process.execPath, ["dist/src/server.js"], {
  env: { ...cleanEnv, BYQ_MCP_ACP_JUDGMENT_SUBSET: "1",
    BYQ_MCP_ACP_JUDGMENT_PORT: String(await reservePort()),
    BYQ_MCP_ACP_JUDGMENT_SIGNING_KEY: judgmentKey,
    BYQ_MCP_TOKEN: "must-not-enter-judgment-process" },
  stdio: "ignore",
});
const conflictingCredentialExit = await exitCodeWithin(conflictingCredentialServer, 3000);
if (conflictingCredentialExit === null) await stop(conflictingCredentialServer);
assert.notEqual(conflictingCredentialExit, null,
  "judgment service must refuse a process environment containing Product credentials");
assert.notEqual(conflictingCredentialExit, 0,
  "judgment service must fail closed when a Product credential is configured");

let backendCalls = 0;
let backendMode: "deny" | "admit" = "deny";
const backendRequests: Array<{ path: string | undefined; authorization: string | undefined;
  task: string | undefined; call: string | undefined; observation: string | undefined;
  body: Record<string, unknown> | undefined }> = [];
const backend = createServer(async (request, response) => {
  backendCalls += 1;
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(Buffer.from(chunk));
  const raw = Buffer.concat(chunks).toString("utf8");
  const body = raw ? JSON.parse(raw) as Record<string, unknown> : undefined;
  backendRequests.push({ path: request.url, authorization: request.headers.authorization,
    task: request.headers["x-byq-judgment-task-id"] as string | undefined,
    call: request.headers["x-byq-judgment-call-identity"] as string | undefined,
    observation: request.headers["x-byq-acp-observation-id"] as string | undefined, body });
  if (backendMode === "admit") {
    const send = (value: unknown) => response.writeHead(200, { "content-type": "application/json" })
      .end(JSON.stringify(value));
    if (request.url === "/internal/acp/judgment-tool-ingress-observe") {
      return send({ schema_version: "byq-acp-tool-ingress-receipt.v1",
        mcp_request_id: body?.mcp_request_id, root_run_id: judgmentClaims.root_run_id,
        runtime_boot_id: judgmentClaims.runtime_boot_id,
        native_root_session_id: judgmentClaims.native_root_session_id,
        native_agent_session_id: judgmentClaims.native_agent_session_id,
        native_parent_session_id: null, origin: "root", depth: 0,
        tool_name: body?.tool_name, agent_run_id: "agent_run_" + "e".repeat(32),
        sequence: 11, event_sha256: "a".repeat(64) });
    }
    if (request.url === `/v1/research/tasks/${judgmentClaims.task_id}/stage-input`) {
      return send({ schema_version: "research-stage-input.v1", task_id: judgmentClaims.task_id,
        stage: "strategy_draft", plan_version: 1, task_version: 1,
        proposal_kinds: [], allowed_tools: [], evidence: [] });
    }
    if (request.url === "/internal/acp/judgment-tool-ingress-settle") {
      return send({ schema_version: "byq-acp-tool-ingress-settle-receipt.v1",
        mcp_request_id: body?.mcp_request_id, root_run_id: judgmentClaims.root_run_id,
        runtime_boot_id: judgmentClaims.runtime_boot_id,
        native_agent_session_id: judgmentClaims.native_agent_session_id,
        tool_name: body?.tool_name, sequence: body?.sequence,
        event_sha256: body?.event_sha256, outcome: body?.outcome,
        settlement_sha256: "b".repeat(64) });
    }
  }
  response.writeHead(404).end();
});
const backendPort = await listen(backend);

const judgmentServer = spawn(process.execPath, ["dist/src/server.js"], {
  env: { ...cleanEnv, BYQ_BACKEND_URL: `http://127.0.0.1:${backendPort}`,
    BYQ_MCP_ACP_JUDGMENT_SUBSET: "1", BYQ_MCP_ACP_JUDGMENT_PORT: String(judgmentPort),
    BYQ_MCP_ACP_JUDGMENT_SIGNING_KEY: judgmentKey },
  stdio: "ignore",
});
const readOnlyServer = spawn(process.execPath, ["dist/src/server.js"], {
  env: { ...cleanEnv, BYQ_BACKEND_URL: `http://127.0.0.1:${backendPort}`,
    BYQ_MCP_READ_ONLY_SUBSET: "1", BYQ_MCP_READ_ONLY_PORT: String(readOnlyPort),
    BYQ_MCP_READ_ONLY_TOKEN: readOnlyToken },
  stdio: "ignore",
});
const productServer = spawn(process.execPath, ["dist/src/server.js"], {
  env: { ...cleanEnv, BYQ_BACKEND_URL: `http://127.0.0.1:${backendPort}`,
    PORT: String(productPort), BYQ_MCP_TOKEN: productStaticToken,
    BYQ_MCP_ACP_DISCOVERY_TOKEN: discoveryToken,
    BYQ_MCP_ACP_SIGNING_KEY: productKey,
    BYQ_MCP_BACKEND_PROOF_TOKEN: backendProofToken },
  stdio: "ignore",
});

try {
  const [judgmentTools, readOnlyTools, productTools] = await Promise.all([
    listToolNames(judgmentPort, judgmentToken),
    listToolNames(readOnlyPort, readOnlyToken),
    listToolNames(productPort, productStaticToken),
  ]);
  assert.deepEqual(judgmentTools, READ_ONLY, "judgment endpoint must register exactly the five bounded reads");
  assert.deepEqual(readOnlyTools, READ_ONLY, "legacy read-only subset behavior must remain intact");
  assert.ok(productTools.length > READ_ONLY.length, "default Product MCP surface must remain broader");

  // Static/legacy/discovery/Product credentials are never classified on this endpoint.
  for (const token of [productStaticToken, readOnlyToken, discoveryToken, backendProofToken, productAgentToken]) {
    assert.equal((await post(judgmentPort, token, "tools/list")).status, 401,
      "judgment endpoint accepted a non-judgment credential");
  }
  // The judgment credential is audience/key isolated from both existing servers.
  assert.equal((await post(productPort, judgmentToken, "tools/list")).status, 401,
    "Product endpoint accepted the judgment credential");
  assert.equal((await post(readOnlyPort, judgmentToken, "tools/list")).status, 401,
    "legacy read-only endpoint accepted the judgment credential");

  // Valid HMACs with a wrong audience, child lineage, or missing/forged task/call
  // claims fail before the MCP handler is constructed.
  const invalidClaims: Record<string, unknown>[] = [
    { ...judgmentClaims, aud: "byq-product-mcp" },
    { ...judgmentClaims, origin: "subagent", depth: 1,
      native_agent_session_id: "00000000-0000-4000-8000-000000000002",
      native_parent_session_id: judgmentClaims.native_root_session_id },
    { ...judgmentClaims, task_id: "task_invalid" },
    { ...judgmentClaims, call_identity: "forged-call" },
  ];
  const missingTask = { ...judgmentClaims } as Record<string, unknown>;
  delete missingTask.task_id;
  const missingCall = { ...judgmentClaims } as Record<string, unknown>;
  delete missingCall.call_identity;
  invalidClaims.push(missingTask, missingCall);
  for (const claims of invalidClaims) {
    const token = sign("byq-acp-judgment-v1", claims, judgmentRootKey);
    assert.equal((await post(judgmentPort, token, "tools/list")).status, 401,
      "invalid judgment claims must be rejected before MCP dispatch");
  }
  const productRootKey = deriveAcpJudgmentRootSigningKey(productKey, judgmentClaims);
  assert.ok(productRootKey);
  const wrongKeyToken = sign("byq-acp-judgment-v1",
    judgmentClaims as unknown as Record<string, unknown>, productRootKey);
  assert.equal((await post(judgmentPort, wrongKeyToken, "tools/list")).status, 401,
    "Product signing key cannot mint judgment credentials");

  const judgmentClient = new Client({ name: "byq-acp-judgment-call-test", version: "1.0.0" });
  try {
    await judgmentClient.connect(new StreamableHTTPClientTransport(
      new URL(`http://127.0.0.1:${judgmentPort}/mcp/v1`), {
        authProvider: { token: async () => judgmentToken },
      },
    ));
    const admitted = await judgmentClient.callTool({ name: "byq_research_stage_input_get", arguments: {
      task_id: judgmentClaims.task_id,
    } });
    const forged = await judgmentClient.callTool({ name: "byq_research_stage_input_get", arguments: {
      task_id: "task_" + "e".repeat(32),
    } });
    for (const result of [admitted, forged]) {
      assert.equal(result.isError, true, "judgment tools/call must fail closed without Backend admission");
      const output = result.content.find((item): item is { type: "text"; text: string } => item.type === "text");
      assert.ok(output && output.text.includes("acp_judgment_backend_admission_unavailable"));
    }
  } finally {
    await judgmentClient.close();
  }
  assert.equal(backendCalls, 0, "no judgment request reached a business or admission Backend handler");

  const admissionPort = await reservePort();
  const judgmentProof = "synthetic-dedicated-judgment-backend-proof-token";
  const admissionServer = spawn(process.execPath, ["dist/src/server.js"], {
    env: { ...cleanEnv, BYQ_BACKEND_URL: `http://127.0.0.1:${backendPort}`,
      BYQ_MCP_ACP_JUDGMENT_SUBSET: "1", BYQ_MCP_ACP_JUDGMENT_PORT: String(admissionPort),
      BYQ_MCP_ACP_JUDGMENT_SIGNING_KEY: judgmentKey,
      BYQ_MCP_ACP_JUDGMENT_PROOF_TOKEN: judgmentProof,
      BYQ_MCP_ACP_JUDGMENT_ADMISSION_ENABLED: "1" },
    stdio: "ignore",
  });
  try {
    await waitReady(`http://127.0.0.1:${admissionPort}`);
    const client = new Client({ name: "byq-acp-judgment-admission-test", version: "1.0.0" });
    try {
      await client.connect(new StreamableHTTPClientTransport(
        new URL(`http://127.0.0.1:${admissionPort}/mcp/v1`), {
          authProvider: { token: async () => judgmentToken },
        }));
      const rejected = await client.callTool({ name: "byq_research_stage_input_get",
        arguments: { task_id: judgmentClaims.task_id } });
      assert.equal(rejected.isError, true);
      backendMode = "admit";
      const otherAgentRunClient = new Client({
        name: "byq-acp-judgment-other-agent-run-test", version: "1.0.0",
      });
      try {
        await otherAgentRunClient.connect(new StreamableHTTPClientTransport(
          new URL(`http://127.0.0.1:${admissionPort}/mcp/v1`), {
            authProvider: { token: async () => otherNativeAgentRunToken },
          }));
        const rejectedOtherAgentRun = await otherAgentRunClient.callTool({
          name: "byq_research_stage_input_get", arguments: { task_id: judgmentClaims.task_id },
        });
        assert.equal(rejectedOtherAgentRun.isError, true,
          "Backend receipt for a different native AgentRun must block handler dispatch");
        assert.equal(backendRequests[2]?.body?.native_root_session_id,
          otherNativeAgentRunClaims.native_root_session_id,
          "MCP must present the token's native AgentRun claim for Backend binding");
        assert.equal(backendRequests.some(request => request.path
          === `/v1/research/tasks/${judgmentClaims.task_id}/stage-input`), false,
        "the mismatched Backend native AgentRun receipt must stop before business read");
        // This is a synthetic receipt matcher test; live Backend registration and
        // AgentRun admission remain a separate acceptance gate (NOT_RUN here).
      } finally {
        await otherAgentRunClient.close();
      }
      const admittedRead = await client.callTool({ name: "byq_research_stage_input_get",
        arguments: { task_id: judgmentClaims.task_id } });
      assert.equal(admittedRead.isError, false, "valid admitted read must reach the bounded handler");
    } finally {
      await client.close();
    }
  } finally {
    await stop(admissionServer);
  }
  assert.deepEqual(backendRequests.map(request => request.path), [
    "/internal/acp/judgment-tool-ingress-observe",
    "/internal/acp/judgment-tool-ingress-abort",
    "/internal/acp/judgment-tool-ingress-observe",
    "/internal/acp/judgment-tool-ingress-abort",
    "/internal/acp/judgment-tool-ingress-observe",
    `/v1/research/tasks/${judgmentClaims.task_id}/stage-input`,
    "/internal/acp/judgment-tool-ingress-settle",
  ], "rejected admission must never enter the business read handler");
  for (const request of backendRequests.filter(request => request.path?.startsWith("/internal/acp/"))) {
    assert.equal(request.authorization, `Bearer ${judgmentProof}`);
    assert.equal(request.task, judgmentClaims.task_id);
    assert.equal(request.call, judgmentClaims.call_identity);
  }
  assert.equal(backendRequests[5]?.observation, backendRequests[4]?.body?.mcp_request_id);
  assert.equal(backendRequests[6]?.body?.outcome, "settled");

  console.log(JSON.stringify({
    ok: true,
    judgment_tools: judgmentTools,
    legacy_read_only_unchanged: true,
    product_surface_unchanged: true,
    cross_audience_and_credential_rejection: true,
    default_judgment_tool_calls_denied_before_backend: true,
    opt_in_synthetic_bounded_read_settled: true,
    cross_agent_run_rejected_by_backend_receipt_binding: true,
    live_backend_agent_run_admission: "NOT_RUN",
  }));
} finally {
  await Promise.all([stop(judgmentServer), stop(readOnlyServer), stop(productServer)]);
  await new Promise<void>((resolve, reject) => backend.close(error => error ? reject(error) : resolve()));
}
