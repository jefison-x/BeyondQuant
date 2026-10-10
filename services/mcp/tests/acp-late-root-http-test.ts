import assert from "node:assert/strict";
import { spawn, type ChildProcess } from "node:child_process";
import { createServer } from "node:http";
import { setTimeout as delay } from "node:timers/promises";
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";
import { createHmac } from "node:crypto";

type Fixture = {
  schema_version: "byq-acp-late-root-fixture.v1";
  claims: {
    root_run_id: string;
    runtime_boot_id: string;
    owner_principal: string;
    workspace_id: string;
    actor_principal: string;
    trace_id: string;
    session_id: string;
    dsh_run_id: string;
  };
  old_root_run_id: string;
  new_root_run_id: string;
  native_root_session_id: string;
  old_agent_run_id: string;
  new_agent_run_id: string;
  old_ingress_count: number;
  new_ingress_count: number;
};

function canonicalObject(value: Record<string, unknown>): string {
  const sorted: Record<string, unknown> = {};
  for (const key of Object.keys(value).sort()) sorted[key] = value[key];
  return JSON.stringify(sorted);
}

function acpBearer(claims: Record<string, unknown>, signingKey: string): string {
  const payload = Buffer.from(canonicalObject(claims), "utf8");
  const signature = createHmac("sha256", Buffer.from(signingKey, "utf8")).update(payload).digest();
  return `byq-acp-v1.${payload.toString("base64url")}.${signature.toString("base64url")}`;
}

function readFixture(): Fixture {
  const raw = process.env.BYQ_MCP_TEST_FIXTURE_JSON;
  assert.ok(raw && raw.length < 16_384, "a bounded disposable synthetic fixture is required");
  const value = JSON.parse(raw) as Fixture;
  assert.equal(value.schema_version, "byq-acp-late-root-fixture.v1");
  assert.notEqual(value.old_root_run_id, value.new_root_run_id);
  assert.notEqual(value.old_agent_run_id, value.new_agent_run_id);
  assert.equal(value.claims.root_run_id, value.old_root_run_id);
  assert.equal(value.claims.actor_principal, `byq-product-agent-${value.claims.session_id}`);
  assert.equal(value.old_ingress_count, 1);
  assert.equal(value.new_ingress_count, 0);
  return value;
}

async function reserveLoopbackPort(): Promise<number> {
  const probe = createServer();
  await new Promise<void>((resolve, reject) => {
    probe.once("error", reject);
    probe.listen(0, "127.0.0.1", () => resolve());
  });
  const address = probe.address();
  assert.ok(address && typeof address === "object");
  await new Promise<void>((resolve, reject) => probe.close(error => error ? reject(error) : resolve()));
  return address.port;
}

async function waitForMcp(child: ChildProcess, endpoint: string): Promise<void> {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    if (child.exitCode !== null) throw new Error("MCP process exited before readiness");
    try {
      const response = await fetch(new URL("/healthz", endpoint), {
        signal: AbortSignal.timeout(1_000),
      });
      if (response.ok) return;
    } catch {
      // The server may still be starting.
    }
    await delay(100);
  }
  throw new Error("MCP readiness deadline elapsed");
}

async function stopMcp(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null || child.killed) return;
  child.kill("SIGTERM");
  const exited = await Promise.race([
    new Promise<boolean>(resolve => child.once("exit", () => resolve(true))),
    delay(2_000).then(() => false),
  ]);
  if (!exited && child.exitCode === null) child.kill("SIGKILL");
}

async function main(): Promise<void> {
  const fixture = readFixture();
  const signingKey = process.env.BYQ_MCP_ACP_SIGNING_KEY ?? "";
  assert.ok(Buffer.byteLength(signingKey, "utf8") >= 32, "synthetic ACP test signer is required");
  assert.equal(process.env.BYQ_BACKEND_URL, "http://backend:8000");
  assert.ok(process.env.BYQ_MCP_BACKEND_PROOF_TOKEN, "synthetic Backend proof is required");

  const claims = {
    v: 1,
    aud: "byq-product-mcp",
    ...fixture.claims,
    native_root_session_id: fixture.native_root_session_id,
    native_agent_session_id: fixture.native_root_session_id,
    native_parent_session_id: null,
    origin: "root",
    depth: 0,
    expires_at: Date.now() + 10 * 60_000,
  };
  const bearer = acpBearer(claims, signingKey);
  const port = await reserveLoopbackPort();
  const endpoint = `http://127.0.0.1:${port}/mcp/v1`;
  const mcpProcess = spawn(process.execPath, ["dist/src/server.js"], {
    env: { ...process.env, PORT: String(port) },
    stdio: "ignore",
  });
  const client = new Client({ name: "acp-late-root-http-test", version: "1.0.0" });

  try {
    await waitForMcp(mcpProcess, endpoint);
    await client.connect(new StreamableHTTPClientTransport(new URL(endpoint), {
      authProvider: { token: async () => bearer },
    }));
    const listed = await client.listTools();
    assert.ok(listed.tools.some(tool => tool.name === "byq_agent_context"));

    // One side-effect-free tool call carries the old root's valid synthetic
    // HMAC identity through the real MCP HTTP server to the real Backend.
    const result = await client.callTool({ name: "byq_agent_context", arguments: {} });
    assert.equal(result.isError, true, "closed old root must fail before the tool callback");
    const text = result.content.filter(item => item.type === "text")
      .map(item => item.type === "text" ? item.text : "").join("\n");
    assert.match(text, /acp_ingress_observation_unavailable/);

    console.log(JSON.stringify({
      schema_version: "byq-acp-late-root-mcp-client-result.v1",
      status: "pass",
      synthetic_hmac: true,
      tool_call_rejected: true,
      expected_error: true,
      model_calls: 0,
    }));
  } finally {
    await client.close().catch(() => undefined);
    await stopMcp(mcpProcess);
  }
}

main().catch(() => {
  // Do not emit environment, credentials, fixture identities, payloads or
  // provider details into test output.
  console.log(JSON.stringify({
    schema_version: "byq-acp-late-root-mcp-client-result.v1",
    status: "fail",
    synthetic_hmac: true,
    tool_call_rejected: false,
    expected_error: false,
    model_calls: 0,
  }));
  process.exitCode = 1;
});
