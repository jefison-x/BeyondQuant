import assert from "node:assert/strict";

import {
  fetchByqMarketDaily,
  fetchByqMarketFundamentals,
  fetchByqMarketValuation,
} from "../src/market-data.js";

const success = await fetchByqMarketDaily(
  "http://backend:8000",
  { ts_code: "000001.SZ", start_date: "20240102", end_date: "20240103" },
  async (url, init) => {
    assert.equal(url, "http://backend:8000/v1/data/research/daily");
    assert.equal(init?.method, "POST");
    assert.deepEqual(JSON.parse(String(init?.body)), {
      ts_code: "000001.SZ", start_date: "20240102", end_date: "20240103",
    });
    assert.ok(init?.signal);
    assert.doesNotMatch(url, /token/i);
    return new Response(
      JSON.stringify({
        data: [
          {
            ts_code: "000001.SZ",
            trade_date: "20240103",
            close: 10.1,
          },
        ],
        provenance: {
          provider: "tushare",
          source: "persisted_byq",
          endpoint: "durable_daily",
          latest_trade_date: "20240103",
          live_provider_called: false,
          row_count: 1,
        },
        coverage: { usable: true, requested_sessions: ["20240102", "20240103"], missing: [] },
      }),
      { status: 200 },
    );
  },
);
assert.equal(success.isError, false);
assert.match(success.content[0].text, /persisted_byq/);
assert.match(success.content[0].text, /live_provider_called/);

const unavailable = await fetchByqMarketDaily(
  "http://backend:8000",
  { trade_date: "20240103" },
  async () => new Response(JSON.stringify({ detail: "provider token must not cross MCP" }), { status: 503 }),
);
assert.equal(unavailable.isError, true);
assert.match(unavailable.content[0].text, /research_data_unavailable/);
assert.doesNotMatch(unavailable.content[0].text, /provider token/);

const valuation = await fetchByqMarketValuation(
  "http://backend:8000",
  { symbols: ["000001.SZ"], trade_date: "20260825", fields: ["pe_ttm", "pb"] },
  async (url, init) => {
    assert.equal(url, "http://backend:8000/v1/data/research/valuation");
    assert.equal(init?.method, "POST");
    assert.deepEqual(JSON.parse(String(init?.body)), {
      symbols: ["000001.SZ"], trade_date: "20260825", fields: ["pe_ttm", "pb"],
    });
    return new Response(JSON.stringify({
      schema_version: "market-valuation-research.v1",
      trade_date: "20260825",
      rows: [{ symbol: "000001.SZ", values: { pe_ttm: 6.5, pb: 0.7 } }],
      coverage: { usable: true, missing_symbols: [] },
    }), { status: 200 });
  },
);
assert.equal(valuation.isError, false);
assert.match(valuation.content[0].text, /market-valuation-research\.v1/);

const fundamentals = await fetchByqMarketFundamentals(
  "http://backend:8000",
  { symbols: ["000001.SZ"], as_of_date: "20260825", fields: ["roe"] },
  async (url, init) => {
    assert.equal(url, "http://backend:8000/v1/data/research/fundamentals");
    assert.deepEqual(JSON.parse(String(init?.body)), {
      symbols: ["000001.SZ"], as_of_date: "20260825", fields: ["roe"],
    });
    return new Response(JSON.stringify({
      schema_version: "market-fundamentals-research.v1",
      as_of_date: "20260825",
      rows: [{
        symbol: "000001.SZ", report_period: "20250331",
        announcement_date: "20250430", effective_date: "20250501", values: { roe: 8 },
      }],
      coverage: { usable: true, missing: [] },
    }), { status: 200 });
  },
);
assert.equal(fundamentals.isError, false);
assert.match(fundamentals.content[0].text, /announcement_date/);

const safeFailure = await fetchByqMarketFundamentals(
  "http://backend:8000",
  { symbols: ["000001.SZ"], as_of_date: "20260825", fields: ["roe"] },
  async () => new Response(JSON.stringify({ detail: "secret=/tmp/provider-token" }), { status: 422 }),
);
assert.equal(safeFailure.isError, true);
assert.match(safeFailure.content[0].text, /research_request_invalid/);
assert.doesNotMatch(safeFailure.content[0].text, /provider-token|\/tmp/);

console.log("Market data MCP translation PASS: durable daily/valuation/fundamentals, safe failures");
