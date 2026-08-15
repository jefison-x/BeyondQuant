import assert from "node:assert/strict";

import { fetchByqMarketDaily } from "../src/market-data.js";

const success = await fetchByqMarketDaily(
  "http://backend:8000",
  { ts_code: "000001.SZ", start_date: "20240102", end_date: "20240103" },
  async (url, init) => {
    assert.match(url, /ts_code=000001\.SZ/);
    assert.match(url, /start_date=20240102/);
    assert.match(url, /end_date=20240103/);
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
          endpoint: "daily",
          request_fingerprint: "redacted-fixture",
          retrieved_at: "2026-08-15T00:00:00+00:00",
          cache_hit: false,
          row_count: 1,
        },
      }),
      { status: 200 },
    );
  },
);
assert.equal(success.isError, false);
assert.match(success.content[0].text, /redacted-fixture/);

const unavailable = await fetchByqMarketDaily(
  "http://backend:8000",
  { trade_date: "20240103" },
  async () => new Response(JSON.stringify({ detail: "provider token must not cross MCP" }), { status: 503 }),
);
assert.equal(unavailable.isError, true);
assert.match(unavailable.content[0].text, /data_provider_unavailable/);
assert.doesNotMatch(unavailable.content[0].text, /provider token/);

console.log("Market data MCP translation PASS: normalized result and safe provider failure");
