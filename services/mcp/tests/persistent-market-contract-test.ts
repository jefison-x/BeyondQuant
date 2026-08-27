import assert from "node:assert/strict";

import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";

const endpoint = process.env.MCP_URL ?? "http://127.0.0.1:8300/mcp/v1";
const token = process.env.BYQ_MCP_TOKEN;
const symbol = process.env.BYQ_REAL_MARKET_SYMBOL;
const startDate = process.env.BYQ_REAL_MARKET_START_DATE;
const endDate = process.env.BYQ_REAL_MARKET_END_DATE;
const expectedLatestClose = process.env.BYQ_REAL_MARKET_EXPECTED_CLOSE;

if (!token || !symbol || !startDate || !endDate) {
  throw new Error("BYQ_MCP_TOKEN and BYQ_REAL_MARKET_* inputs are required");
}

const transport = new StreamableHTTPClientTransport(new URL(endpoint), {
  authProvider: { token: async () => token },
  requestInit: {
    headers: {
      "x-byq-workspace-id": "workspace_phase61_acceptance",
      "x-byq-owner-principal": "user:phase61-acceptance",
      "x-byq-actor-principal": "agent:phase61-acceptance",
      "x-byq-trace-id": "trace_phase61_persisted_market",
      "x-byq-session-id": "session_phase61_persisted_market",
      "x-byq-dsh-run-id": "dsh_phase61_persisted_market",
    },
  },
});
const client = new Client({ name: "byq-persisted-market-contract-test", version: "0.1.0" });

try {
  await client.connect(transport);
  const called = await client.callTool({
    name: "byq_market_daily",
    arguments: { ts_code: symbol, start_date: startDate, end_date: endDate },
  });
  assert.equal(called.isError, false, JSON.stringify(called));
  const block = called.content.find((item) => item.type === "text");
  assert.ok(block && "text" in block, "byq_market_daily must return JSON text");
  const payload = JSON.parse(block.text) as {
    status: string;
    data: Array<{ ts_code: string; trade_date: string; close: number }>;
    provenance: {
      source: string;
      live_provider_called: boolean;
      row_count: number;
      latest_trade_date: string | null;
    };
  };
  assert.equal(payload.status, "ok");
  assert.equal(payload.provenance.source, "persisted_byq");
  assert.equal(payload.provenance.live_provider_called, false);
  assert.ok(payload.data.length > 0, "fixture range must contain persisted bars");
  assert.equal(payload.provenance.row_count, payload.data.length);
  assert.ok(payload.data.every((row) => row.ts_code === symbol));
  assert.ok(payload.data.every((row) => row.trade_date >= startDate && row.trade_date <= endDate));
  if (expectedLatestClose) {
    const latest = payload.data.find((row) => row.trade_date === endDate);
    assert.ok(latest, "expected end-date row is missing");
    assert.equal(latest.close, Number(expectedLatestClose));
  }
  console.log(`MCP persisted market PASS: ${symbol} ${payload.data.length} rows through ${payload.provenance.latest_trade_date}`);
} finally {
  await client.close();
}
