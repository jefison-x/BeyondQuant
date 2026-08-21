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
  assert.ok(listed.tools.some((tool) => tool.name === "byq_factor_compute"));
  assert.ok(listed.tools.some((tool) => tool.name === "byq_workflow_card_propose"));
  for (const name of [
    "byq_strategy_validate",
    "byq_strategy_version_create",
    "byq_strategy_approve",
    "byq_strategy_export",
  ]) {
    assert.ok(listed.tools.some((tool) => tool.name === name), `${name} is missing`);
  }
  for (const name of ["byq_pool_list", "byq_pool_get", "byq_pool_create", "byq_pool_snapshot_replace", "byq_pool_history", "byq_pool_lifecycle", "byq_paper_account_list", "byq_paper_account_get", "byq_paper_order_get", "byq_paper_snapshot_list"]) {
    assert.ok(listed.tools.some((tool) => tool.name === name), `${name} is missing`);
  }
  for (const name of [
    "byq_agent_context",
    "byq_agent_roles",
    "byq_agent_run_start",
    "byq_agent_authorize",
    "byq_agent_audit",
    "byq_agent_audit_get",
    "byq_agent_approval_request",
    "byq_agent_approval_get",
    "byq_agent_approval_decide",
  ]) {
    assert.ok(listed.tools.some((tool) => tool.name === name), `${name} is missing`);
  }
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
