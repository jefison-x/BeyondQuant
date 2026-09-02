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
  requestInit: {
    headers: {
      "x-byq-workspace-id": "workspace_mcp_contract",
      "x-byq-owner-principal": "user:mcp-contract",
      "x-byq-actor-principal": "agent:mcp-contract",
      "x-byq-trace-id": "trace_mcp_contract",
      "x-byq-session-id": "session_mcp_contract",
      "x-byq-dsh-run-id": "dsh_mcp_contract",
    },
  },
});

try {
  await client.connect(transport);
  const listed = await client.listTools();
  assert.ok(listed.tools.some((tool) => tool.name === "byq_health"));
  assert.ok(listed.tools.some((tool) => tool.name === "byq_product_help_query"));
  assert.ok(listed.tools.some((tool) => tool.name === "byq_market_daily"));
  assert.ok(listed.tools.some((tool) => tool.name === "byq_market_session_context"));
  assert.ok(listed.tools.some((tool) => tool.name === "byq_market_valuation"));
  assert.ok(listed.tools.some((tool) => tool.name === "byq_market_fundamentals"));
  assert.ok(listed.tools.some((tool) => tool.name === "byq_data_demand_create"));
  assert.ok(listed.tools.some((tool) => tool.name === "byq_data_demand_get"));
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
  for (const retired of ["byq_backtest_submit", "byq_backtest_run", "byq_backtest_cancel"]) {
    assert.ok(!listed.tools.some((tool) => tool.name === retired), `${retired} must not be exposed`);
  }
  for (const name of ["byq_pool_list", "byq_pool_get", "byq_pool_create", "byq_pool_snapshot_replace", "byq_pool_history", "byq_pool_lifecycle", "byq_paper_account_list", "byq_paper_account_get", "byq_paper_order_get", "byq_paper_snapshot_list"]) {
    assert.ok(listed.tools.some((tool) => tool.name === name), `${name} is missing`);
  }
  for (const name of [
    "byq_backtest_task_prepare",
    "byq_backtest_task_create",
    "byq_backtest_task_get",
    "byq_backtest_analysis_get",
    "byq_backtest_task_execute",
    "byq_backtest_task_cancel",
  ]) {
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
    "byq_web_evidence_create",
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

  const boundedJobId = "backtest_ffffffffffffffffffffffffffffffff";
  for (let pageCall = 0; pageCall < 6; pageCall += 1) {
    const attempted = await client.callTool({
      name: "byq_backtest_analysis_get",
      arguments: { job_id: boundedJobId, section: "daily_returns", limit: 1, offset: pageCall },
    });
    assert.equal(attempted.isError, true, "Backend rejection remains a real tool error before budget exhaustion");
  }
  const bounded = await client.callTool({
    name: "byq_backtest_analysis_get",
    arguments: { job_id: boundedJobId, section: "equity_curve", limit: 1, offset: 0 },
  });
  assert.notEqual(bounded.isError, true, "budget exhaustion must remain a normal tool result");
  const boundedText = bounded.content.find((block) => block.type === "text");
  if (!boundedText || !("text" in boundedText)) {
    throw new Error("bounded backtest analysis did not return a text result");
  }
  assert.deepEqual(JSON.parse(boundedText.text), {
    service: "beyondquant-mcp",
    status: "bounded",
    analysis_page_budget: {
      status: "exhausted",
      call_limit: 6,
      remaining_calls: 0,
      backend_accessed: false,
      must_answer_from_collected_evidence: true,
      code: "analysis_page_budget_exceeded",
      retryable: false,
    },
  });
  console.log("MCP contract PASS: initialize, tools, health and normal bounded-analysis completion");
} finally {
  await client.close();
}
