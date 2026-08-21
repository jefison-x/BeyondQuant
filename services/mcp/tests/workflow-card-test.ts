import assert from "node:assert/strict";

import { proposeWorkflowCard } from "../src/workflow-card.js";


const strategy = proposeWorkflowCard({
  kind: "strategy_draft",
  title: "策略草稿",
  summary: "验证动量假设",
  name: "20 日动量",
  validation_status: "draft",
});
assert.equal(strategy.isError, false);
assert.deepEqual(JSON.parse(strategy.content[0].text), {
  service: "beyondquant-mcp",
  status: "ok",
  candidate: {
    kind: "agent.card.strategy_draft",
    payload: {
      title: "策略草稿",
      summary: "验证动量假设",
      name: "20 日动量",
      validation_status: "draft",
    },
  },
});

const stocks = proposeWorkflowCard({
  kind: "stock_candidates",
  title: "高股息候选",
  items: [{ symbol: "600000.SH", name: "浦发银行", reason: "候选" }],
});
assert.match(stocks.content[0].text, /600000\.SH/);

assert.throws(
  () => proposeWorkflowCard({
    kind: "stock_candidates",
    title: "重复候选",
    items: [{ symbol: "000001.SZ" }, { symbol: "000001.SZ" }],
  }),
  /candidate symbols must be unique/,
);
assert.throws(
  () => proposeWorkflowCard({
    kind: "optimization",
    title: "危险载荷",
    objective: "改进",
    changes: [{ area: "参数", after: "1", reason: "测试" }],
    authorization: "forbidden",
  }),
);

console.log("Workflow card MCP projection PASS: strict proposal kinds, bounds, and unknown-field rejection");
