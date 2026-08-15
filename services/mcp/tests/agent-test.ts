import assert from "node:assert/strict";

import {
  fetchByqAgentAudit,
  fetchByqAgentAuthorize,
  fetchByqAgentRunStart,
} from "../src/agent.js";

const context = {
  owner_principal: "alice",
  actor_principal: "alice",
  trace_id: "trace-agent-mcp-1",
  session_id: "session-agent-mcp-1",
  dsh_run_id: "dsh-run-agent-mcp-1",
};

const start = await fetchByqAgentRunStart(
  "http://backend:8000",
  { role_id: "market_researcher", idempotency_key: "agent-mcp-1" },
  context,
  async (url, init) => {
    assert.equal(url, "http://backend:8000/v1/agents/runs");
    assert.equal(init?.headers && (init.headers as Record<string, string>)["x-byq-owner-principal"], "alice");
    assert.equal((init?.headers as Record<string, string>)["x-byq-session-id"], "session-agent-mcp-1");
    assert.doesNotMatch(String(init?.body), /password|secret|token/i);
    return new Response(JSON.stringify({ run: { run_id: "agent_run_0123456789abcdef0123456789abcdef" } }), { status: 201 });
  },
);
assert.equal(start.isError, false);

const authorized = await fetchByqAgentAuthorize(
  "http://backend:8000",
  { run_id: "agent_run_0123456789abcdef0123456789abcdef", action: "byq_market_daily" },
  context,
  async (_url, init) => {
    assert.equal((init?.headers as Record<string, string>)["x-byq-actor-principal"], "alice");
    return new Response(JSON.stringify({ authorization: { decision: "allowed" } }), { status: 200 });
  },
);
assert.equal(authorized.isError, false);

const safeError = await fetchByqAgentAudit(
  "http://backend:8000",
  { run_id: "agent_run_0123456789abcdef0123456789abcdef", action: "byq_market_daily", outcome: "failed", detail: { reason: "bounded" } },
  context,
  async () => new Response(JSON.stringify({ detail: "owner mismatch /var/lib/byq/domain" }), { status: 401 }),
);
assert.equal(safeError.isError, true);
assert.match(safeError.content[0].text, /agent_unauthorized/);
assert.doesNotMatch(safeError.content[0].text, /var\/lib/);

console.log("Agent MCP translation PASS: trusted context headers, authorization, and safe errors");
