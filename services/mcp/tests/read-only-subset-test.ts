// ADR-0085 P4: the isolated READ-ONLY MCP surface exposes exactly the five
// bounded read tools over the REAL MCP protocol (tools/list), and the default
// Product surface is unchanged. This is the non-exposure proof for the bounded
// judgment composition; permission denial is not a substitute.
//
// The test spawns two real servers on separate ephemeral ports with separate
// credentials and connects with the official MCP client. It never imports the
// server module (which would start an unrelated listener) and it fails if the
// server cannot start or if tools/list does not answer, so a trailing exit 0
// cannot mask a broken surface.
import assert from "node:assert/strict";
import { spawn, type ChildProcess } from "node:child_process";
import { createServer } from "node:http";
import { setTimeout as delay } from "node:timers/promises";
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";

const READ_ONLY = [
  "byq_agent_context",
  "byq_backtest_analysis_get",
  "byq_backtest_task_get",
  "byq_research_get",
  "byq_research_stage_input_get",
];
const FORBIDDEN = [
  "byq_strategy_version_create",
  "byq_strategy_approve",
  "byq_backtest_task_create",
  "byq_backtest_task_execute",
  "byq_research_transition",
  "byq_research_task_create",
  "byq_paper_account_create",
  "byq_agent_approval_decide",
  "byq_ml_training_create",
  "byq_web_evidence_create",
];

async function reservePort(): Promise<number> {
  const reserve = createServer();
  await new Promise<void>(resolve => reserve.listen(0, "127.0.0.1", resolve));
  const address = reserve.address();
  assert.ok(address && typeof address === "object");
  const port = address.port;
  await new Promise<void>(resolve => reserve.close(() => resolve()));
  return port;
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
  const client = new Client({ name: "byq-read-only-subset", version: "1.0.0" });
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

async function stop(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null) return;
  child.kill("SIGTERM");
  await new Promise<void>(resolve => {
    if (child.exitCode !== null) resolve();
    else child.once("exit", () => resolve());
  });
}

const cleanEnv = { ...process.env };
for (const name of ["PORT", "BYQ_MCP_TOKEN", "BYQ_MCP_READ_ONLY_SUBSET",
  "BYQ_MCP_READ_ONLY_PORT", "BYQ_MCP_READ_ONLY_TOKEN"]) {
  delete cleanEnv[name];
}

const readOnlyPort = await reservePort();
const readOnlyToken = "byq-read-only-subset-token";
const defaultPort = await reservePort();
const defaultToken = "byq-product-surface-token";

const readOnlyServer = spawn(process.execPath, ["dist/src/server.js"], {
  env: { ...cleanEnv, BYQ_MCP_READ_ONLY_SUBSET: "1",
    BYQ_MCP_READ_ONLY_PORT: String(readOnlyPort), BYQ_MCP_READ_ONLY_TOKEN: readOnlyToken },
  stdio: "ignore",
});
const defaultServer = spawn(process.execPath, ["dist/src/server.js"], {
  env: { ...cleanEnv, PORT: String(defaultPort), BYQ_MCP_TOKEN: defaultToken },
  stdio: "ignore",
});

try {
  const subset = await listToolNames(readOnlyPort, readOnlyToken);
  const full = await listToolNames(defaultPort, defaultToken);

  // Real MCP tools/list on the isolated instance exposes EXACTLY five tools.
  assert.deepEqual(subset, READ_ONLY, `read-only subset mismatch: ${JSON.stringify(subset)}`);
  for (const forbidden of FORBIDDEN) {
    assert.ok(!subset.includes(forbidden), `read-only subset exposed ${forbidden}`);
  }

  // The default Product surface is unchanged: strictly larger, still contains
  // the read tools, and still exposes the write tools.
  assert.ok(full.length > READ_ONLY.length, "default surface must expose more than the read subset");
  for (const name of READ_ONLY) assert.ok(full.includes(name), `default surface missing ${name}`);
  assert.ok(full.includes("byq_strategy_version_create"), "default surface lost a write tool");
  assert.ok(full.includes("byq_backtest_task_execute"), "default surface lost a write tool");

  // The isolated instance must not share the Product credential: the Product
  // token is rejected by the read-only instance and vice versa.
  const probe = (port: number, token: string) => fetch(`http://127.0.0.1:${port}/mcp/v1`, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list", params: {} }),
  });
  assert.equal((await probe(readOnlyPort, defaultToken)).status, 401,
    "read-only instance accepted the Product token");
  assert.equal((await probe(defaultPort, readOnlyToken)).status, 401,
    "Product instance accepted the read-only token");

  console.log(JSON.stringify({
    ok: true, full: full.length, read_only: subset,
    product_token_rejected_by_read_only: true,
    read_only_token_rejected_by_product: true,
  }));
} finally {
  await stop(readOnlyServer);
  await stop(defaultServer);
}
