import assert from "node:assert/strict";

import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";

const endpoint = process.env.MCP_URL ?? "http://127.0.0.1:8300/mcp/v1";
const token = process.env.BYQ_MCP_TOKEN;

if (!token) {
  throw new Error("BYQ_MCP_TOKEN is required for the MCP contract test");
}

const client = new Client({ name: "byq-mcp-contract-test", version: "0.1.0" });
const transport = new StreamableHTTPClientTransport(new URL(endpoint), {
  authProvider: { token: async () => token },
});

try {
  await client.connect(transport);
  const listed = await client.listTools();
  assert.ok(listed.tools.some((tool) => tool.name === "byq_health"));
  assert.ok(listed.tools.some((tool) => tool.name === "byq_market_daily"));
  for (const name of [
    "byq_research_task_create",
    "byq_research_get",
    "byq_research_transition",
    "byq_experiment_create",
    "byq_artifact_create",
  ]) {
    assert.ok(listed.tools.some((tool) => tool.name === name), `${name} is missing`);
  }

  const called = await client.callTool({ name: "byq_health", arguments: {} });
  const textBlock = called.content.find((block) => block.type === "text");
  if (!textBlock || !("text" in textBlock)) {
    throw new Error("byq_health did not return a text result");
  }
  const payload = JSON.parse(textBlock.text) as {
    service: string;
    status: string;
    backend: { service: string; status: string; version: string };
  };

  assert.deepEqual(payload, {
    service: "beyondquant-mcp",
    status: "ok",
    backend: {
      service: "byq-backend",
      status: "ok",
      version: "0.1.0",
    },
  });
  console.log("MCP contract PASS: initialize -> tools/list -> byq_health");
} finally {
  await client.close();
}
