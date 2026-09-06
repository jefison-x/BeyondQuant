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
      "x-byq-workspace-id": process.env.BYQ_MCP_CONTRACT_WORKSPACE ?? "workspace_mcp_contract",
      "x-byq-owner-principal": process.env.BYQ_MCP_CONTRACT_OWNER ?? "user:mcp-contract",
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
  for (const name of ["byq_feedback_options", "byq_feedback_list", "byq_feedback_get", "byq_feedback_create_draft", "byq_feedback_update_draft", "byq_feedback_preview", "byq_feedback_submit"]) {
    assert.ok(listed.tools.some((tool) => tool.name === name), `${name} is missing`);
  }
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
  const webEvidenceTool = listed.tools.find((tool) => tool.name === "byq_web_evidence_create");
  const webProperties = webEvidenceTool?.inputSchema?.properties as Record<string, unknown> | undefined;
  const contentSchema = webProperties?.content as { properties?: Record<string, unknown> } | undefined;
  const searchSchema = contentSchema?.properties?.search as { properties?: Record<string, unknown>; required?: string[] } | undefined;
  assert.ok(searchSchema?.properties?.queries, "web evidence search queries schema is missing");
  assert.ok(!searchSchema?.required?.includes("plugin_id"), "model must not need to construct a producer ID");
  assert.ok(!searchSchema?.required?.includes("plugin_version"), "model must not need to construct a producer version");

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

  // Real MCP -> Backend -> PostgreSQL save, with no model-supplied version.
  const evidenceArgs = {
    task: { title: "U2 provenance", objective: "Persist bounded evidence through the trusted MCP boundary." },
    content: {
      schema_version: "web-research-evidence.v1",
      research_as_of: "2026-08-28T12:00:00+08:00",
      market_context: {
        as_of_date: "20260828", trading_session: null,
        persisted_data_cutoff: null, calendar_verified: false,
      },
      search: {
        queries: [{ text: "provenance contract fixture", language: "en", purpose: "Verify evidence storage" }],
        stopped_reason: "EVIDENCE_SUFFICIENT",
      },
      sources: [{
        url: "https://www.csrc.gov.cn/example", title: "Contract fixture", publisher: "Regulator",
        source_tier: "PRIMARY", published_at: "2026-08-27T09:00:00+08:00",
        retrieved_at: "2026-08-28T11:30:00+08:00", temporal_status: "WITHIN_AS_OF",
        query_indexes: [0], summary: "Fixture evidence for storage validation.",
      }],
      claims: [{ statement: "Fixture predates the research cutoff.", claim_type: "FACT", state: "SUPPORTED", source_indexes: [0] }],
      limitations: ["Synthetic fixture; no external search or market-data authority."],
      usage_policy: { research_only: true, deterministic_input: false, authoritative_market_data: false },
    },
    lineage: [], idempotency_key: "u2-mcp-provenance-contract", // gitleaks:allow -- synthetic idempotency fixture, not a credential
  };
  const saved = await client.callTool({ name: "byq_web_evidence_create", arguments: evidenceArgs });
  assert.notEqual(saved.isError, true, JSON.stringify(saved));
  const savedText = saved.content.find((block) => block.type === "text");
  assert.ok(savedText && "text" in savedText);
  const record = JSON.parse(savedText.text);
  assert.equal(record.record_status, "saved");
  const artifactId = record.audit_resource.resource_id;
  const read = await client.callTool({
    name: "byq_research_get", arguments: { entity_type: "artifact", entity_id: artifactId },
  });
  assert.notEqual(read.isError, true, JSON.stringify(read));
  const readText = read.content.find((block) => block.type === "text");
  assert.ok(readText && "text" in readText);
  const stored = JSON.parse(readText.text);
  assert.equal(stored.content.search.plugin_id, "web-search");
  assert.equal(stored.content.search.plugin_version, "0.1.1-rc.1");
  assert.ok(stored.content_sha256);
  const repeated = await client.callTool({ name: "byq_web_evidence_create", arguments: evidenceArgs });
  assert.notEqual(repeated.isError, true);
  const repeatedText = repeated.content.find((block) => block.type === "text");
  assert.ok(repeatedText && "text" in repeatedText);
  assert.equal(JSON.parse(repeatedText.text).audit_resource.resource_id, artifactId);
  const legacy = await client.callTool({
    name: "byq_web_evidence_create",
    arguments: {
      ...evidenceArgs,
      content: { ...evidenceArgs.content, search: { ...evidenceArgs.content.search, plugin_id: "web-search", plugin_version: "0.1.1-rc.1" } },
    },
  });
  assert.notEqual(legacy.isError, true, "matching legacy commands must remain compatible");
  const forged = await client.callTool({
    name: "byq_web_evidence_create",
    arguments: {
      ...evidenceArgs,
      content: { ...evidenceArgs.content, search: { ...evidenceArgs.content.search, plugin_id: "web-search", plugin_version: "9.9.9" } },
    },
  });
  assert.equal(forged.isError, true, "legacy fields cannot select a producer version");
  console.log("Web evidence MCP live save PASS: trusted version, persisted content/hash, idempotency and legacy compatibility");

  const invalidAuditRun = await client.callTool({
    name: "byq_agent_audit_get",
    arguments: { run_id: "byq-session-not-an-agent-run" },
  });
  assert.equal(
    invalidAuditRun.isError,
    true,
    "runtime session IDs must be rejected at the MCP schema boundary",
  );

  const rawBacktestSeries = await client.callTool({
    name: "byq_backtest_analysis_get",
    arguments: {
      job_id: "backtest_ffffffffffffffffffffffffffffffff",
      section: "daily_returns",
      limit: 20,
      offset: 0,
    },
  });
  assert.equal(
    rawBacktestSeries.isError,
    true,
    "raw daily/equity series must stay outside the Agent analysis surface",
  );

  const boundedJobId = "backtest_ffffffffffffffffffffffffffffffff";
  for (let pageCall = 0; pageCall < 6; pageCall += 1) {
    const attempted = await client.callTool({
      name: "byq_backtest_analysis_get",
      arguments: { job_id: boundedJobId, section: "summary", limit: 1, offset: 0 },
    });
    assert.equal(attempted.isError, true, "Backend rejection remains a real tool error before budget exhaustion");
  }
  const bounded = await client.callTool({
    name: "byq_backtest_analysis_get",
    arguments: { job_id: boundedJobId, section: "logs", limit: 1, offset: 0 },
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
