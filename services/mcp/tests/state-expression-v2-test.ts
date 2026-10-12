// State-expression V2 boundary regression (v2 repair).
//
// Runs the ACTUAL registered MCP handlers (byq_backtest_task_get and
// byq_research_get plus one denied write) over the real MCP protocol against a
// synthetic loopback Backend, and asserts the serialized content[0].text. It
// uses an explicit synthetic child environment (no inherited private
// production env), a finite total deadline, bounded protocol waits and
// TERM->KILL cleanup. It never contacts a real Backend, Database, model or Job.
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { spawn, type ChildProcess } from "node:child_process";
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { setTimeout as delay } from "node:timers/promises";
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";

const testArguments = process.argv.slice(2);
if (testArguments.length > 1 || testArguments.some(argument => argument !== "--collector-fault")) {
  throw new Error(`unsupported state-expression test arguments: ${testArguments.join(" ")}`);
}
const collectorFaultMode = testArguments[0] === "--collector-fault";
const collectorFaultError = new Error("synthetic collector callback fault");
const collectorFaultStack = collectorFaultError.stack;
const collectorFaultSnapshot = Object.freeze({ name: collectorFaultError.name,
  message: collectorFaultError.message, stack: collectorFaultStack });

const token = "synthetic-state-expression-v2-token";
const backendProof = "synthetic-state-expression-v2-backend-proof";
const signingKey = "synthetic-state-expression-v2-signing-key-32b";
const reservation = "continuation_" + "1".repeat(32);
const root = "a".repeat(32);
const runtimeBootId = "c".repeat(32);
const acpRunId = "agent_run_" + "e".repeat(32);
const signalJobId = "signaljob_" + "b".repeat(32);
const backtestTaskId = "backtesttask_" + "b".repeat(32);
const otherBacktestTaskId = "backtesttask_" + "e".repeat(32);
const researchTaskId = "task_" + "d".repeat(32);
const otherResearchTaskId = "task_" + "9".repeat(32);
const experimentId = "experiment_" + "d".repeat(32);
const artifactId = "artifact_" + "d".repeat(32);
const artifactContentSha256 = "f".repeat(64);
const watchId = "researchwatch_" + "f".repeat(32);
const originalKey = "original/key &中文";
const backendExecutionNote = "BACKEND_EXECUTION_NOTE_MUST_NOT_PASS";
const backendContinuationNote = "BACKEND_CONTINUATION_NOTE_MUST_NOT_PASS";
const expectedResearchExecutionNote = "Business task status and handoff describe current state, not permission. This query grants no execution permission; follow the current trusted Root instruction and obtain required authorization before any allowed action.";
const expectedResearchWaitingJobNote = "Task is waiting on an existing Domain Job. This query does not advance or resume it.";

const claims = {
  v: 1, aud: "byq-product-mcp",
  root_run_id: root, runtime_boot_id: runtimeBootId,
  owner_principal: "alice", workspace_id: "workspace-v2",
  actor_principal: "byq-product-agent-session-acp",
  trace_id: "trace-acp", session_id: "session-acp", dsh_run_id: "generation-acp",
  native_root_session_id: "00000000-0000-4000-8000-00000000000a",
  native_agent_session_id: "00000000-0000-4000-8000-00000000000a",
  native_parent_session_id: null,
  origin: "root", depth: 0, expires_at: Date.now() + 10 * 60_000,
};
function acpBearer(): string {
  const sorted: Record<string, unknown> = {};
  for (const key of Object.keys(claims).sort()) sorted[key] = (claims as Record<string, unknown>)[key];
  const payload = Buffer.from(JSON.stringify(sorted), "utf8");
  const signature = createHmac("sha256", Buffer.from(signingKey, "utf8")).update(payload).digest();
  return `byq-acp-v1.${payload.toString("base64url")}.${signature.toString("base64url")}`;
}

const DEADLINE_MS = 60_000;
const REQUEST_TIMEOUT_MS = 8_000;
const CLEANUP_TIMEOUT_MS = 2_000;
let backtestPhase = "ready_to_execute";
let backtestBlockers: Array<{ code: string; message: string }> = [];
let backtestId = backtestTaskId;
let backtestBodyOverride: "array" | "empty" | null = null;
let backtestReconcile: Record<string, unknown> | null = null;
let researchStatus = "planned";
let researchId = researchTaskId;
let researchHandoff: Record<string, unknown> | null = {
  schema_version: "research-task-handoff.v1", task_id: researchTaskId, state: "waiting_job", reason: null };
let researchBodyOverride: "array" | "empty" | null = null;
let researchReconcile: Record<string, unknown> | null = null;

type Entry = { method: string; path: string; search: string; headers: Headers; body?: Record<string, unknown> };
const requestLog: Entry[] = [];
const unexpected: string[] = [];
let acpSequence = 0;

const fixtureFailureController = new AbortController();
let firstFixtureError: Error | undefined;
let firstFixtureErrorSnapshot: Readonly<{ name: string; message: string; stack: string | undefined }> | undefined;
let resolveFixtureFailure!: (error: Error) => void;
const fixtureFailureSignal = new Promise<Error>(resolve => { resolveFixtureFailure = resolve; });

function rejectFixtureResponse(response: ServerResponse): void {
  if (response.destroyed || response.writableEnded) return;
  try {
    if (!response.headersSent) {
      response.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
      response.end("synthetic fixture failed");
    } else {
      response.destroy();
    }
  } catch {
    response.destroy();
  }
}

function latchFixtureFailure(error: unknown, response?: ServerResponse): Error {
  if (firstFixtureError === undefined) {
    const firstError = error instanceof Error ? error : new Error(String(error));
    firstFixtureError = firstError;
    firstFixtureErrorSnapshot = Object.freeze({ name: firstError.name,
      message: firstError.message, stack: firstError.stack });
    fixtureFailureController.abort(new Error("state-expression-v2 fixture failure abort"));
    resolveFixtureFailure(firstError);
  }
  if (response) rejectFixtureResponse(response);
  return firstFixtureError;
}

function assertFixtureHealthy(): void {
  if (firstFixtureError) throw firstFixtureError;
}

async function handleBackendRequest(req: IncomingMessage, res: ServerResponse): Promise<void> {
  if (firstFixtureError) {
    rejectFixtureResponse(res);
    return;
  }
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(Buffer.from(chunk));
  const raw = Buffer.concat(chunks).toString("utf8");
  const body = raw ? JSON.parse(raw) as Record<string, unknown> : undefined;
  const requestUrl = new URL(req.url ?? "/", "http://localhost");
  const path = requestUrl.pathname;
  if (firstFixtureError) {
    rejectFixtureResponse(res);
    return;
  }
  if (collectorFaultMode && req.method === "GET" && path === "/__collector_fault") {
    throw collectorFaultError;
  }
  const headers = new Headers(req.headers as Record<string, string>);
  requestLog.push({ method: req.method ?? "", path, search: requestUrl.search, headers, body });
  const send = (status: number, value: unknown) => {
    if (firstFixtureError) {
      rejectFixtureResponse(res);
      return;
    }
    res.writeHead(status, { "content-type": "application/json" });
    res.end(JSON.stringify(value));
  };
  const proof = () => assert.equal(headers.get("authorization"), `Bearer ${backendProof}`);
  const continuationScope = () => {
    assert.equal(headers.get("authorization"), null, "trusted continuation fetch has no ACP proof bearer");
    for (const [name, value] of [
      ["x-byq-workspace-id", claims.workspace_id],
      ["x-byq-owner-principal", claims.owner_principal],
      ["x-byq-actor-principal", claims.actor_principal],
      ["x-byq-trace-id", claims.trace_id],
      ["x-byq-session-id", claims.session_id],
      ["x-byq-dsh-run-id", claims.dsh_run_id],
      ["x-byq-runtime-boot-id", claims.runtime_boot_id],
      ["x-byq-root-run-id", claims.root_run_id],
    ]) assert.equal(headers.get(name), value, `trusted continuation identity header ${name}`);
  };

  if (path === "/internal/acp/tool-ingress-observe") {
    assert.equal(req.method, "POST"); proof();
    assert.equal(headers.get("x-byq-root-run-id"), root);
    const receipt = { schema_version: "byq-acp-tool-ingress-receipt.v1",
      mcp_request_id: body?.mcp_request_id, root_run_id: claims.root_run_id,
      runtime_boot_id: claims.runtime_boot_id, native_root_session_id: claims.native_root_session_id,
      native_agent_session_id: claims.native_agent_session_id, native_parent_session_id: null,
      origin: "root", depth: 0, tool_name: body?.tool_name, agent_run_id: acpRunId,
      sequence: ++acpSequence, event_sha256: "a".repeat(64) };
    send(200, receipt);
    return;
  }
  if (path === "/internal/acp/tool-ingress-settle") {
    assert.equal(req.method, "POST"); proof();
    send(200, { schema_version: "byq-acp-tool-ingress-settle-receipt.v1",
      mcp_request_id: body?.mcp_request_id, root_run_id: claims.root_run_id,
      runtime_boot_id: claims.runtime_boot_id, native_agent_session_id: claims.native_agent_session_id,
      tool_name: body?.tool_name, sequence: body?.sequence, event_sha256: body?.event_sha256,
      outcome: body?.outcome, settlement_sha256: "9".repeat(64) });
    return;
  }
  const continuation = path.match(/^\/internal\/task-continuation\/(continuation_[0-9a-f]{32})\/authorize-tool$/);
  if (continuation) {
    assert.equal(req.method, "POST"); continuationScope();
    assert.equal(continuation[1], reservation);
    assert.equal(body?.root_run_id, root);
    const callArguments = body?.arguments;
    if (body?.tool === "byq_research_get") {
      assert.ok(callArguments !== null && typeof callArguments === "object" && !Array.isArray(callArguments));
      assert.deepEqual(body, { tool: "byq_research_get",
        arguments: { entity_type: "research_task", entity_id: (callArguments as Record<string, unknown>).entity_id },
        root_run_id: root });
      assert.equal((callArguments as Record<string, unknown>).entity_type, "research_task");
      assert.ok([researchTaskId, otherResearchTaskId].includes(String((callArguments as Record<string, unknown>).entity_id)));
    } else if (body?.tool === "byq_backtest_task_get") {
      assert.deepEqual(body, { tool: "byq_backtest_task_get",
        arguments: { backtest_task_id: backtestTaskId }, root_run_id: root });
    } else if (body?.tool === "byq_research_transition") {
      assert.deepEqual(body, { tool: "byq_research_transition",
        arguments: { entity_type: "research_task", entity_id: researchTaskId,
          target_status: "running", idempotency_key: "acp-denied-write" }, root_run_id: root });
    } else {
      assert.fail(`unexpected continuation tool ${String(body?.tool)}`);
    }
    const admitted = body?.tool === "byq_research_get"
      && callArguments !== null && typeof callArguments === "object" && !Array.isArray(callArguments)
      && (callArguments as Record<string, unknown>).entity_type === "research_task"
      && (callArguments as Record<string, unknown>).entity_id === researchTaskId;
    send(200, { schema_version: "continuation-action-admission.v1",
      admitted, reservation_id: reservation });
    return;
  }
  if (path === `/v1/research/backtest-tasks/${otherBacktestTaskId}` && req.method === "GET") {
    return send(404, { detail: "not found" });
  }
  if (path === `/v1/research/backtest-tasks/${backtestTaskId}` && req.method === "GET") {
    if (backtestBodyOverride === "array") return send(200, []);
    if (backtestBodyOverride === "empty") return send(200, {});
    return send(200, { task: { schema_version: "backtest-task.v1", backtest_task_id: backtestId,
      phase: backtestPhase, next_action: "execute",
      actions: { can_create: false, can_execute: true, can_cancel: true },
      references: { research_task_id: researchTaskId, signal_producer_job_id: signalJobId },
      blockers: backtestBlockers } });
  }
  if (path === "/v1/research/backtest-tasks/reconcile" && req.method === "GET" && backtestReconcile) {
    assert.deepEqual([...requestUrl.searchParams.entries()], [
      ["task_id", researchTaskId], ["idempotency_key", originalKey],
    ], "backtest-task reconciliation accepts only its exact task and request key");
    return send(200, backtestReconcile);
  }
  if (path === `/v1/research/tasks/${researchTaskId}` && req.method === "GET") {
    if (researchBodyOverride === "array") return send(200, []);
    if (researchBodyOverride === "empty") return send(200, {});
    // Simulate hostile Backend-authored note fields on every exact task read.
    return send(200, { task_id: researchId, status: researchStatus,
      execution_note: backendExecutionNote, continuation_note: backendContinuationNote,
      ...(researchHandoff ? { handoff: researchHandoff } : {}) });
  }
  if (path === `/v1/research/experiments/${experimentId}` && req.method === "GET") {
    return send(200, { experiment_id: experimentId, status: "running", task_id: researchTaskId });
  }
  if (path === `/v1/research/artifacts/${artifactId}/reference` && req.method === "GET") {
    return send(200, { artifact_id: artifactId, type: "report",
      owner_principal: claims.owner_principal, workspace_id: claims.workspace_id,
      validation: { status: "validated", content_sha256: artifactContentSha256 } });
  }
  if (path === `/v1/research/artifacts/${artifactId}` && req.method === "GET") {
    return send(200, { artifact_id: artifactId, task_id: researchTaskId, kind: "report",
      status: "validated", content_sha256: artifactContentSha256,
      owner_principal: claims.owner_principal, workspace_id: claims.workspace_id });
  }
  if (path === "/v1/research/submissions/reconcile" && req.method === "GET" && researchReconcile) {
    assert.deepEqual([...requestUrl.searchParams.entries()], [
      ["entity_type", "research_task"], ["idempotency_key", originalKey],
    ], "research-task reconciliation accepts only its exact entity type and request key");
    return send(200, researchReconcile);
  }
  if (path === `/v1/research/submission-watches/${watchId}` && req.method === "GET") {
    return send(200, { schema_version: "research-receipt-watch.v1", entity_type: "research_task",
      watch_id: watchId, status: "awaiting_receipt", attempts: 1, max_attempts: 8,
      idempotency_key: "watch-key", registration_created: true, task_id: null });
  }
  unexpected.push(`${req.method} ${path}`);
  send(404, { detail: "not found" });
}

const backend: Server = createServer((req, res) => {
  req.once("error", error => { latchFixtureFailure(error, res); });
  res.once("error", error => { latchFixtureFailure(error); });
  void handleBackendRequest(req, res).catch(error => { latchFixtureFailure(error, res); });
});
backend.on("error", error => { latchFixtureFailure(error); });

async function bounded<T>(label: string, ms: number, operation: () => Promise<T>): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  const timeout = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} exceeded ${ms}ms`)), ms);
  });
  try {
    return await Promise.race([Promise.resolve().then(operation), timeout]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function listenServer(server: Server, port: number): Promise<void> {
  await bounded("loopback server listen", CLEANUP_TIMEOUT_MS, () => new Promise<void>((resolve, reject) => {
    const onListening = () => { server.off("error", onError); resolve(); };
    const onError = (error: Error) => { server.off("listening", onListening); reject(error); };
    server.once("listening", onListening);
    server.once("error", onError);
    server.listen(port, "127.0.0.1");
  }));
}

async function reservePort(): Promise<number> {
  const reserve = createServer();
  try {
    await listenServer(reserve, 0);
    const address = reserve.address();
    assert.ok(address && typeof address === "object");
    return address.port;
  } finally {
    if (reserve.listening) {
      try { reserve.closeAllConnections(); }
      finally {
        await bounded("reservation server close", CLEANUP_TIMEOUT_MS, () => new Promise<void>((resolve, reject) => {
          reserve.close(error => error ? reject(error) : resolve());
        }));
      }
    }
  }
}
async function waitExit(child: ChildProcess, ms: number): Promise<boolean> {
  if (child.exitCode !== null || child.signalCode !== null) return true;
  return await new Promise(resolve => {
    const timer = setTimeout(() => { child.off("exit", onExit); resolve(false); }, ms);
    const onExit = () => { clearTimeout(timer); resolve(true); };
    child.once("exit", onExit);
  });
}
async function stopChild(child: ChildProcess, termMs = 3000, killMs = 2000): Promise<void> {
  if (child.exitCode !== null || child.signalCode !== null) return;
  try { child.kill("SIGTERM"); } catch { /* continue to the bounded kill check */ }
  if (await waitExit(child, termMs)) return;
  try { child.kill("SIGKILL"); } catch { /* verify exit below */ }
  if (!(await waitExit(child, killMs))) throw new Error("child process did not exit after SIGKILL");
}

let service: ChildProcess | undefined;
let deadlineTimer: NodeJS.Timeout | undefined;
const deadlineController = new AbortController();
let deadlineExpired = false;
let resolveDeadline!: () => void;
const deadlineReached = new Promise<void>(resolve => { resolveDeadline = resolve; });
deadlineTimer = setTimeout(() => {
  deadlineExpired = true;
  const error = new Error("state-expression-v2 total deadline exceeded");
  latchFixtureFailure(error);
  deadlineController.abort(new Error("state-expression-v2 deadline abort"));
  resolveDeadline();
}, DEADLINE_MS);
const clients: Client[] = [];
const legacy = new Client({ name: "byq-state-expression-v2", version: "1.0.0" });
const bare = new Client({ name: "byq-state-expression-v2-bare", version: "1.0.0" });
const mismatch = new Client({ name: "byq-state-expression-v2-mismatch", version: "1.0.0" });
const acp = new Client({ name: "byq-state-expression-v2-acp", version: "1.0.0" });
clients.push(legacy, bare, mismatch, acp);
let run: Promise<void> | undefined;
let failed = false;
let failure: unknown;
let childShutdownStarted = false;
const cleanupErrors: string[] = [];
let toolCallCount = 0;
const requestOptions = () => ({
  timeout: REQUEST_TIMEOUT_MS,
  signal: AbortSignal.any([deadlineController.signal, fixtureFailureController.signal,
    AbortSignal.timeout(REQUEST_TIMEOUT_MS)]),
});
const connectClient = async (client: Client, transport: StreamableHTTPClientTransport) => {
  assertFixtureHealthy();
  const result = await client.connect(transport, requestOptions());
  assertFixtureHealthy();
  return result;
};
const trackedCallTool = async (client: Client, name: string, args: Record<string, unknown>) => {
  assertFixtureHealthy();
  toolCallCount += 1;
  const result = await client.callTool({ name, arguments: args }, requestOptions());
  assertFixtureHealthy();
  return result;
};
const trackedListTools = async () => {
  assertFixtureHealthy();
  const result = await legacy.listTools(undefined, requestOptions());
  assertFixtureHealthy();
  return result;
};
try {
  run = (async () => {
    assertFixtureHealthy();
    await listenServer(backend, 0);
    assertFixtureHealthy();
    const backendAddress = backend.address();
    assert.ok(backendAddress && typeof backendAddress === "object");
    const port = await reservePort();
    assertFixtureHealthy();
    const endpoint = `http://127.0.0.1:${port}`;
    const backendEndpoint = `http://127.0.0.1:${backendAddress.port}`;
    const childEnv: NodeJS.ProcessEnv = {
      PATH: process.env.PATH, LANG: process.env.LANG, NODE_ENV: "test",
      PORT: String(port), BYQ_MCP_TOKEN: token,
      BYQ_MCP_ACP_SIGNING_KEY: signingKey, BYQ_MCP_BACKEND_PROOF_TOKEN: backendProof,
      BYQ_BACKEND_URL: backendEndpoint,
    };
    service = spawn(process.execPath, ["dist/src/server.js"], { env: childEnv, stdio: "ignore" });
    service.once("error", error => { latchFixtureFailure(error); });
    service.once("exit", (code, signal) => {
      if (!childShutdownStarted) latchFixtureFailure(new Error(`MCP child exited unexpectedly code=${code} signal=${signal}`));
    });
    assertFixtureHealthy();

    const headers = {
      "x-byq-root-run-id": root, "x-byq-owner-principal": "alice", "x-byq-workspace-id": "workspace-v2",
      "x-byq-session-id": "session-v2", "x-byq-trace-id": "trace-v2", "x-byq-dsh-run-id": "generation-v2",
      "x-byq-actor-principal": "byq-product-agent-session-v2", "x-byq-runtime-boot-id": runtimeBootId,
    };
    let ready = false;
    for (let attempt = 0; attempt < 100; attempt += 1) {
      assertFixtureHealthy();
      ready = await fetch(endpoint + "/healthz", { signal: requestOptions().signal })
        .then(reply => reply.ok).catch(() => {
          assertFixtureHealthy();
          return false;
        });
      assertFixtureHealthy();
      if (ready) break;
      await delay(50, undefined, { signal: requestOptions().signal });
      assertFixtureHealthy();
    }
    assert.ok(ready, "actual MCP server must start");
    assertFixtureHealthy();
    if (collectorFaultMode) {
      await fetch(backendEndpoint + "/__collector_fault", { signal: requestOptions().signal })
        .catch(error => { throw firstFixtureError ?? error; });
      assertFixtureHealthy();
      throw new Error("collector fault route returned without latching its failure");
    }
    await connectClient(legacy, new StreamableHTTPClientTransport(new URL(endpoint + "/mcp/v1"), {
      authProvider: { token: async () => token }, requestInit: { headers },
    }));
    const call = async (name: string, args: Record<string, unknown>) => {
      const reply = await trackedCallTool(legacy, name, args);
      const content = reply.content as Array<{ type: string; text: string }>;
      const text = content[0]?.text ?? "{}";
      return { isError: reply.isError === true, text, value: JSON.parse(text) as Record<string, any> };
    };
    const business = (method: string, prefix: string) =>
      requestLog.filter(entry => entry.method === method && entry.path.startsWith(prefix));

    // L1 exact backtest task-ID GET: business execute readiness, no grant.
    backtestPhase = "ready_to_execute"; backtestBlockers = []; backtestId = backtestTaskId;
    let before = requestLog.length;
    let reply = await call("byq_backtest_task_get", { backtest_task_id: backtestTaskId });
    assert.equal(reply.isError, false);
    assert.equal(requestLog.length - before, 1, "exact task read must make exactly one Backend call");
    assert.equal(reply.value.task.backtest_task_id, backtestTaskId);
    assert.equal(reply.value.task.next_action, "execute");
    assert.equal(reply.value.task.actions.can_execute, true);
    assert.equal(typeof reply.value.execution_note, "string");
    assert.match(reply.value.execution_note, /grants no execution permission/);
    assert.match(reply.value.continuation_note, /grants no execution permission/);
    assert.ok(!("allowed" in reply.value) && !("current_root_read_only" in reply.value));

    // L2 waiting branch uses only validated facts, never arbitrary blocker prose.
    backtestPhase = "waiting_for_data"; backtestBlockers = [{ code: "market_data_not_ready", message: "MARKER backend detail" }];
    reply = await call("byq_backtest_task_get", { backtest_task_id: backtestTaskId });
    assert.match(reply.value.continuation_note, /waiting for existing market-input/);
    assert.doesNotMatch(reply.value.continuation_note, /MARKER/);

    // L3 completed reports the business result without claiming the whole task.
    backtestPhase = "completed"; backtestBlockers = [];
    reply = await call("byq_backtest_task_get", { backtest_task_id: backtestTaskId });
    assert.match(reply.value.continuation_note, /broader ResearchTask/);

    // L4 approval_required blocker: human approval only, no prose amplification.
    backtestPhase = "prepared"; backtestBlockers = [{ code: "approval_required", message: "MARKER approval prose" }];
    reply = await call("byq_backtest_task_get", { backtest_task_id: backtestTaskId });
    assert.match(reply.value.continuation_note, /An approval is required/);
    assert.doesNotMatch(reply.value.continuation_note, /MARKER/);

    // L5 hostile prototype phase keys never become facts.
    for (const hostile of ["__proto__", "constructor", "toString"]) {
      backtestPhase = hostile; backtestBlockers = [];
      reply = await call("byq_backtest_task_get", { backtest_task_id: backtestTaskId });
      assert.equal(typeof reply.value.continuation_note, "string");
      assert.equal(reply.value.continuation_note, "This query alone is insufficient to determine a safe next step.");
    }

    // L6 malformed array body, L7 missing task object, L8 identity mismatch, L9 not-found.
    backtestBodyOverride = "array";
    reply = await call("byq_backtest_task_get", { backtest_task_id: backtestTaskId });
    assert.equal(reply.isError, true);
    assert.equal(reply.value.backend.status, "invalid_response");
    assert.ok(!("execution_note" in reply.value));
    backtestBodyOverride = "empty";
    reply = await call("byq_backtest_task_get", { backtest_task_id: backtestTaskId });
    assert.equal(reply.value.backend.status, "invalid_response");
    backtestBodyOverride = null; backtestId = otherBacktestTaskId;
    reply = await call("byq_backtest_task_get", { backtest_task_id: backtestTaskId });
    assert.equal(reply.value.backend.status, "invalid_response");
    assert.ok(!("execution_note" in reply.value));
    backtestId = backtestTaskId;
    reply = await call("byq_backtest_task_get", { backtest_task_id: otherBacktestTaskId });
    assert.equal(reply.value.backend.status, "backtest_not_found");
    assert.ok(!("execution_note" in reply.value));

    // L10 research_task exact entity GET with a real handoff fact.
    researchStatus = "planned"; researchId = researchTaskId;
    researchHandoff = { schema_version: "research-task-handoff.v1", task_id: researchTaskId, state: "waiting_job", reason: null };
    before = requestLog.length;
    reply = await call("byq_research_get", { entity_type: "research_task", entity_id: researchTaskId });
    assert.equal(reply.isError, false);
    assert.equal(requestLog.length - before, 1);
    assert.equal(reply.value.task_id, researchTaskId);
    assert.equal(reply.value.execution_note, expectedResearchExecutionNote);
    assert.equal(reply.value.continuation_note, expectedResearchWaitingJobNote);
    assert.ok(!reply.value.continuation_note.includes(backendContinuationNote));
    assert.equal(reply.value.status, "planned", "identity check must not rely on the spread top-level status");

    // L11-L14 legal state/reason pairs.
    for (const [state, reason, expected] of [
      ["needs_reconciliation", "continuation_result_unconfirmed", /unconfirmed/],
      ["needs_reconciliation", "permission_revoked", /revoked/],
      ["needs_permission", "permission_expired", /expired/],
      ["conversation_active", "task_execution_unconfirmed", /unconfirmed/],
    ] as const) {
      researchHandoff = { schema_version: "research-task-handoff.v1", task_id: researchTaskId, state, reason };
      reply = await call("byq_research_get", { entity_type: "research_task", entity_id: researchTaskId });
      assert.match(reply.value.continuation_note, expected, `legal pair ${state}/${reason}`);
      assert.ok(!reply.value.continuation_note.includes(backendContinuationNote),
        `Backend continuation_note must not pass through for ${state}/${reason}`);
    }

    // L15 missing handoff: identity note only.
    researchHandoff = null;
    reply = await call("byq_research_get", { entity_type: "research_task", entity_id: researchTaskId });
    assert.equal(reply.value.execution_note, expectedResearchExecutionNote);
    assert.ok(!("continuation_note" in reply.value));

    // L16 hostile prototype state/reason keys never become facts.
    for (const hostile of ["__proto__", "constructor", "toString"]) {
      researchHandoff = { schema_version: "research-task-handoff.v1", task_id: researchTaskId, state: hostile, reason: null };
      reply = await call("byq_research_get", { entity_type: "research_task", entity_id: researchTaskId });
      assert.ok(!("continuation_note" in reply.value), `hostile state ${hostile}`);
      researchHandoff = { schema_version: "research-task-handoff.v1", task_id: researchTaskId, state: "needs_reconciliation", reason: hostile };
      reply = await call("byq_research_get", { entity_type: "research_task", entity_id: researchTaskId });
      assert.ok(!("continuation_note" in reply.value), `hostile reason ${hostile}`);
    }

    // L17 contradictory / invalid pairs, L18 foreign/missing schema, L19 foreign/missing task ID.
    for (const handoff of [
      { schema_version: "research-task-handoff.v1", task_id: researchTaskId, state: "completed", reason: "permission_revoked" },
      { schema_version: "research-task-handoff.v1", task_id: researchTaskId, state: "future_state", reason: "permission_missing" },
      { schema_version: "research-task-handoff.v1", task_id: researchTaskId, state: "needs_permission", reason: "completion_evidence_missing" },
      { schema_version: "research-task-handoff.v1", task_id: researchTaskId, state: "waiting_job", reason: "task_execution_unconfirmed" },
      { schema_version: "research-task-handoff.v1", task_id: researchTaskId, state: "waiting_job" },
      { task_id: researchTaskId, state: "waiting_job", reason: null },
      { schema_version: "research-task-handoff.v0", task_id: researchTaskId, state: "waiting_job", reason: null },
      { schema_version: "research-task-handoff.v1", task_id: otherResearchTaskId, state: "waiting_job", reason: null },
      { schema_version: "research-task-handoff.v1", state: "waiting_job", reason: null },
    ]) {
      researchHandoff = handoff;
      reply = await call("byq_research_get", { entity_type: "research_task", entity_id: researchTaskId });
      assert.equal(reply.isError, false);
      assert.equal(reply.value.execution_note, expectedResearchExecutionNote);
      assert.ok(!("continuation_note" in reply.value), `illegal handoff ${JSON.stringify(handoff)}`);
    }

    // L20-L22 malformed / missing / mismatched research identity use the existing error path.
    researchHandoff = { schema_version: "research-task-handoff.v1", task_id: researchTaskId, state: "waiting_job", reason: null };
    researchBodyOverride = "array";
    reply = await call("byq_research_get", { entity_type: "research_task", entity_id: researchTaskId });
    assert.equal(reply.isError, true);
    assert.equal(reply.value.backend.status, "invalid_response");
    researchBodyOverride = "empty";
    reply = await call("byq_research_get", { entity_type: "research_task", entity_id: researchTaskId });
    assert.equal(reply.value.backend.status, "invalid_response");
    researchBodyOverride = null; researchId = otherResearchTaskId;
    reply = await call("byq_research_get", { entity_type: "research_task", entity_id: researchTaskId });
    assert.equal(reply.value.backend.status, "invalid_response");
    assert.ok(!("execution_note" in reply.value));
    researchId = researchTaskId;

    // L23 experiment/artifact reads cannot acquire task handoff or notes.
    before = requestLog.length;
    reply = await call("byq_research_get", { entity_type: "experiment", entity_id: experimentId });
    assert.equal(reply.isError, false);
    assert.deepEqual(requestLog.slice(before).map(entry => [entry.method, entry.path, entry.search]), [
      ["GET", `/v1/research/experiments/${experimentId}`, ""],
    ]);
    assert.ok(!("execution_note" in reply.value) && !("continuation_note" in reply.value) && !("handoff" in reply.value));

    before = requestLog.length;
    reply = await call("byq_research_get", { entity_type: "artifact", entity_id: artifactId });
    assert.equal(reply.isError, false);
    assert.equal(reply.value.artifact_id, artifactId);
    assert.equal(reply.value.task_id, researchTaskId);
    assert.equal(reply.value.kind, "report");
    assert.equal(reply.value.status, "validated");
    assert.equal(reply.value.content_sha256, artifactContentSha256);
    assert.equal(reply.value.owner_principal, claims.owner_principal);
    assert.equal(reply.value.workspace_id, claims.workspace_id);
    assert.ok(!("execution_note" in reply.value) && !("continuation_note" in reply.value)
      && !("handoff" in reply.value) && !("task_note" in reply.value) && !("task_notes" in reply.value));
    const artifactReads = requestLog.slice(before);
    assert.deepEqual(artifactReads.map(entry => [entry.method, entry.path, entry.search]), [
      ["GET", `/v1/research/artifacts/${artifactId}/reference`, ""],
      ["GET", `/v1/research/artifacts/${artifactId}`, ""],
    ], "non-signal Artifact must resolve typed reference before exactly one raw read");
    assert.equal(artifactReads.some(entry => entry.method === "POST"), false);
    assert.equal(artifactReads.some(entry => entry.path.includes("/summary")), false);
    assert.equal(artifactReads.some(entry => entry.path.startsWith("/v1/research/signal-snapshots/")), false);

    // L24-L25 research key reconciliation.
    researchReconcile = { schema_version: "research-submission-reconciliation.v1", entity_type: "research_task",
      idempotency_key: originalKey, status: "outcome_unknown" };
    reply = await call("byq_research_get", { entity_type: "research_task", idempotency_key: originalKey });
    assert.equal(reply.value.schema_version, "research-submission-reconciliation.v1");
    assert.equal(reply.value.entity_type, "research_task");
    assert.equal(reply.value.idempotency_key, originalKey);
    assert.equal(reply.value.status, "outcome_unknown");
    assert.equal(reply.value.retryable, false);
    assert.ok(!("execution_note" in reply.value) && !("phase" in reply.value));
    researchReconcile = { schema_version: "research-submission-reconciliation.v1", entity_type: "research_task",
      idempotency_key: originalKey, status: "confirmed", entity: { task_id: researchTaskId } };
    reply = await call("byq_research_get", { entity_type: "research_task", idempotency_key: originalKey });
    assert.equal(reply.value.entity.task_id, researchTaskId);
    assert.ok(!("execution_note" in reply.value));

    // L26-L27 backtest task key reconciliation.
    backtestReconcile = { schema_version: "backtest-task-submission-reconciliation.v1", status: "outcome_unknown",
      task_id: researchTaskId, idempotency_key: originalKey };
    reply = await call("byq_backtest_task_get", { task_id: researchTaskId, idempotency_key: originalKey });
    assert.equal(reply.value.task_id, researchTaskId);
    assert.equal(reply.value.idempotency_key, originalKey);
    assert.equal(reply.value.status, "outcome_unknown");
    assert.equal(reply.value.retryable, false);
    assert.doesNotMatch(reply.value.next_action, /execute it once/i);
    assert.doesNotMatch(reply.value.next_action, /never submitted/i);
    assert.ok(!("execution_note" in reply.value) && !("phase" in reply.value));
    backtestReconcile = { schema_version: "backtest-task-submission-reconciliation.v1", status: "confirmed",
      task_id: researchTaskId, idempotency_key: originalKey,
      receipt: { backtest_task_id: backtestTaskId, signal_producer_job_id: signalJobId, signal_status: "completed" } };
    reply = await call("byq_backtest_task_get", { task_id: researchTaskId, idempotency_key: originalKey });
    assert.equal(reply.value.receipt.backtest_task_id, backtestTaskId);
    assert.match(reply.value.next_action, /grants no execution permission/);
    assert.ok(!("execution_note" in reply.value));

    // L28 watch branch is not a task read and gains no note.
    reply = await call("byq_research_get", { entity_type: "research_task", watch_id: watchId });
    assert.equal(reply.value.watch_id, watchId);
    assert.ok(!("execution_note" in reply.value) && !("continuation_note" in reply.value));

    // L29 registered tool description no longer suggests an unproved execute-once.
    const { tools } = await trackedListTools();
    const description = tools.find(tool => tool.name === "byq_backtest_task_get")?.description ?? "";
    assert.doesNotMatch(description, /execute it once/i);
    assert.doesNotMatch(description, /never submitted/i);
    assert.match(description, /grants no execution permission/);

    // L30-L31 missing/mismatched context keep the existing gate, never reach Backend.
    await connectClient(bare, new StreamableHTTPClientTransport(new URL(endpoint + "/mcp/v1"), {
      authProvider: { token: async () => token } }));
    before = requestLog.length;
    const bareReply = await trackedCallTool(bare, "byq_backtest_task_get", { backtest_task_id: backtestTaskId });
    assert.equal(bareReply.isError, true);
    assert.equal((JSON.parse(((bareReply.content as Array<{ text: string }>)[0]?.text) ?? "{}") as Record<string, any>).backend.status,
      "agent_context_unavailable");
    assert.equal(requestLog.length, before, "missing context must not reach Backend");
    await connectClient(mismatch, new StreamableHTTPClientTransport(new URL(endpoint + "/mcp/v1"), {
      authProvider: { token: async () => token },
      requestInit: { headers: { ...headers, "x-byq-actor-principal": "alice" } } }));
    const mismatchReply = await trackedCallTool(mismatch, "byq_research_get",
      { entity_type: "research_task", entity_id: researchTaskId });
    assert.equal(mismatchReply.isError, true);
    assert.equal((JSON.parse(((mismatchReply.content as Array<{ text: string }>)[0]?.text) ?? "{}") as Record<string, any>).backend.status,
      "agent_context_unavailable");
    assert.equal(requestLog.length, before, "mismatched actor must not reach Backend");

    // A1 trusted signed ACP + continuation reservation: allowed exact read only.
    researchHandoff = { schema_version: "research-task-handoff.v1", task_id: researchTaskId, state: "waiting_job", reason: null };
    await connectClient(acp, new StreamableHTTPClientTransport(new URL(endpoint + "/mcp/v1"), {
      authProvider: { token: async () => acpBearer() },
      requestInit: { headers: { "x-byq-continuation-reservation": reservation } } }));
    const businessBefore = business("GET", `/v1/research/tasks/`).length;
    const acpStart = requestLog.length;
    const acpReply = await trackedCallTool(acp, "byq_research_get",
      { entity_type: "research_task", entity_id: researchTaskId });
    assert.equal(acpReply.isError, false);
    const acpValue = JSON.parse(((acpReply.content as Array<{ text: string }>)[0]?.text) ?? "{}") as Record<string, any>;
    assert.equal(acpValue.task_id, researchTaskId);
    assert.equal(typeof acpValue.execution_note, "string");
    assert.match(acpValue.continuation_note, /waiting on an existing Domain Job/);
    assert.ok(!("allowed" in acpValue) && !("permission" in acpValue));
    assert.equal(business("GET", `/v1/research/tasks/`).length - businessBefore, 1);
    assert.equal(business("POST", `/v1/research/tasks/`).length, 0);
    const acpEntries = requestLog.slice(acpStart);
    const ingress = acpEntries.find(entry => entry.path === "/internal/acp/tool-ingress-observe"
      && entry.body?.tool_name === "byq_research_get");
    const admission = acpEntries.find(entry => entry.path === "/internal/task-continuation/" + reservation + "/authorize-tool");
    const settlement = acpEntries.find(entry => entry.path === "/internal/acp/tool-ingress-settle"
      && entry.body?.tool_name === "byq_research_get");
    assert.ok(ingress, "accepted ACP read must create an ingress receipt");
    assert.ok(settlement, "accepted ACP read must create a settlement receipt");
    assert.deepEqual(admission?.body, { tool: "byq_research_get",
      arguments: { entity_type: "research_task", entity_id: researchTaskId }, root_run_id: root });

    // A2 denied non-authorized read via signed ACP + reservation: blocked before dispatch.
    before = requestLog.length;
    const backtestGetBefore = business("GET", "/v1/research/backtest-tasks/").length;
    const deniedRead = await trackedCallTool(acp, "byq_backtest_task_get", { backtest_task_id: backtestTaskId });
    assert.equal(deniedRead.isError, true);
    assert.equal((JSON.parse(((deniedRead.content as Array<{ text: string }>)[0]?.text) ?? "{}") as Record<string, any>).reason,
      "continuation_action_not_admitted");
    assert.equal(business("GET", "/v1/research/backtest-tasks/").length - backtestGetBefore, 0);
    const deniedEntries = requestLog.slice(before);
    assert.equal(deniedEntries.length, 1, "denied different-tool call must stop at its admission request");
    assert.equal(deniedEntries[0]?.path, "/internal/task-continuation/" + reservation + "/authorize-tool");
    assert.deepEqual(deniedEntries[0]?.body, { tool: "byq_backtest_task_get",
      arguments: { backtest_task_id: backtestTaskId }, root_run_id: root });

    // A same-tool request for another task is rejected before business GET or POST.
    before = requestLog.length;
    const researchTaskGetBefore = business("GET", "/v1/research/tasks/").length;
    const researchTaskPostBefore = business("POST", "/v1/research/tasks/").length;
    const deniedOtherTask = await trackedCallTool(acp, "byq_research_get",
      { entity_type: "research_task", entity_id: otherResearchTaskId });
    assert.equal(deniedOtherTask.isError, true);
    assert.equal((JSON.parse(((deniedOtherTask.content as Array<{ text: string }>)[0]?.text) ?? "{}") as Record<string, any>).reason,
      "continuation_action_not_admitted");
    assert.equal(business("GET", "/v1/research/tasks/").length - researchTaskGetBefore, 0);
    assert.equal(business("POST", "/v1/research/tasks/").length - researchTaskPostBefore, 0);
    const deniedOtherTaskEntries = requestLog.slice(before);
    assert.equal(deniedOtherTaskEntries.length, 1, "same-tool wrong-task call must stop at its admission request");
    assert.equal(deniedOtherTaskEntries[0]?.path, "/internal/task-continuation/" + reservation + "/authorize-tool");
    assert.deepEqual(deniedOtherTaskEntries[0]?.body, { tool: "byq_research_get",
      arguments: { entity_type: "research_task", entity_id: otherResearchTaskId }, root_run_id: root });

    // A3 denied write via signed ACP + reservation: blocked, no business mutation.
    before = requestLog.length;
    const transitionBefore = business("POST", "/v1/research/tasks/").length;
    const deniedWrite = await trackedCallTool(acp, "byq_research_transition",
      { entity_type: "research_task", entity_id: researchTaskId, target_status: "running", idempotency_key: "acp-denied-write" });
    assert.equal(deniedWrite.isError, true);
    assert.equal((JSON.parse(((deniedWrite.content as Array<{ text: string }>)[0]?.text) ?? "{}") as Record<string, any>).reason,
      "continuation_action_not_admitted");
    assert.equal(business("POST", "/v1/research/tasks/").length - transitionBefore, 0);
    const deniedWriteEntries = requestLog.slice(before);
    assert.equal(deniedWriteEntries.length, 1, "denied write must stop at its admission request");
    assert.equal(deniedWriteEntries[0]?.path, "/internal/task-continuation/" + reservation + "/authorize-tool");
    assert.deepEqual(deniedWriteEntries[0]?.body, { tool: "byq_research_transition",
      arguments: { entity_type: "research_task", entity_id: researchTaskId,
        target_status: "running", idempotency_key: "acp-denied-write" }, root_run_id: root });

    assert.deepEqual(unexpected, [], "synthetic Backend must reject unexpected routes/methods");
    assert.equal(toolCallCount, 48, "34 labelled groups expand to 48 actual tools/call requests");
  })();

  const runOutcome = run.then(
    () => firstFixtureError
      ? ({ kind: "failed" as const, error: firstFixtureError })
      : ({ kind: "complete" as const }),
    error => ({ kind: "failed" as const, error: latchFixtureFailure(error) }),
  );
  const outcome = await Promise.race([
    runOutcome,
    fixtureFailureSignal.then(error => ({ kind: "failed" as const, error })),
    deadlineReached.then(() => ({ kind: "deadline" as const })),
  ]);
  if (outcome.kind === "deadline") throw firstFixtureError ?? new Error("state-expression-v2 total deadline exceeded");
  if (outcome.kind === "failed") throw outcome.error;
} catch (error) {
  failed = true;
  failure = latchFixtureFailure(error);
} finally {
  deadlineController.abort(new Error("state-expression-v2 cleanup started"));
  fixtureFailureController.abort(new Error("state-expression-v2 cleanup started"));
  for (const [index, client] of clients.entries()) {
    try {
      await bounded(`MCP client ${index + 1} close`, CLEANUP_TIMEOUT_MS, () => client.close());
    } catch (error) {
      cleanupErrors.push(`MCP client ${index + 1} close: ${String(error)}`);
    }
  }
  if (service) {
    childShutdownStarted = true;
    try {
      await bounded("MCP child TERM/KILL", 5_500, () => stopChild(service!));
    } catch (error) {
      cleanupErrors.push(`MCP child stop: ${String(error)}`);
    }
    if (service.exitCode === null && service.signalCode === null) {
      cleanupErrors.push("MCP child exit was not confirmed after SIGKILL");
    }
  }
  if (backend.listening) {
    try { backend.closeAllConnections(); }
    catch (error) { cleanupErrors.push(`Backend closeAllConnections: ${String(error)}`); }
    try {
      await bounded("Backend close", CLEANUP_TIMEOUT_MS, () => new Promise<void>((resolve, reject) => {
        backend.close(error => error ? reject(error) : resolve());
      }));
    } catch (error) {
      cleanupErrors.push(`Backend close: ${String(error)}`);
    }
  }
  if (run) {
    try {
      await bounded("background run settle", CLEANUP_TIMEOUT_MS,
        () => run!.then(() => undefined, () => undefined));
    } catch (error) {
      cleanupErrors.push(`background run did not settle: ${String(error)}`);
    }
  }
  if (deadlineExpired) cleanupErrors.push("total deadline expired before cleanup completed");
  const childState = service
    ? `pid=${service.pid ?? "none"} exitCode=${service.exitCode} signalCode=${service.signalCode}`
    : "pid=none exitCode=none signalCode=none";
  console.log(`State-expression V2 cleanup: ${childState} closed=${!backend.listening} toolsCalls=${toolCallCount}`
    + ` primary=${firstFixtureErrorSnapshot ? JSON.stringify(firstFixtureErrorSnapshot) : "none"}`
    + ` cleanupErrors=${JSON.stringify(cleanupErrors)}`);
  if (deadlineTimer) clearTimeout(deadlineTimer);
}

if (collectorFaultMode) {
  assert.equal(failed, true, "collector-fault mode must stop through the shared failure path");
  assert.strictEqual(failure, collectorFaultError, "first failure must preserve the original Error object");
  assert.strictEqual(firstFixtureError, collectorFaultError, "callback must latch the original Error object");
  assert.equal(collectorFaultError.stack, collectorFaultStack, "callback must preserve the original Error stack");
  assert.deepEqual(firstFixtureErrorSnapshot, collectorFaultSnapshot,
    "immutable primary snapshot must match the collector sentinel before transport abort");
  assert.ok(firstFixtureErrorSnapshot, "first failure snapshot must exist");
  assert.equal(Object.isFrozen(firstFixtureErrorSnapshot), true, "first failure snapshot must be frozen");
  assert.equal(toolCallCount, 0, "collector-fault mode must make no tools/call request");
  assert.ok(service && (service.exitCode !== null || service.signalCode !== null), "synthetic child exit must be confirmed");
  assert.equal(backend.listening, false, "synthetic Backend must be closed before the marker");
  if (cleanupErrors.length > 0) throw new Error(`bounded cleanup failed after collector fault: ${cleanupErrors.join("; ")}`);
  console.log("EXPECTED_COLLECTOR_FAULT_PASS");
} else {
  if (firstFixtureError && !failed) { failed = true; failure = firstFixtureError; }
  if (failed) throw failure;
  if (cleanupErrors.length > 0) throw new Error(`bounded cleanup failed: ${cleanupErrors.join("; ")}`);
  console.log("State-expression V2 PASS: own-key safe notes, handoff binding, ACP+continuation admission, no replay/blocks");
}
