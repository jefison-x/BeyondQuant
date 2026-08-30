import assert from "node:assert/strict";

import { queryProductHelp } from "../src/product-help.js";


const catalog = {
  schema_version: "product-capability-catalog.v1" as const,
  catalog_version: "test",
  capabilities: [
    {
      capability_id: "machine-learning-research", name: "模型研究", route_id: "/model-research",
      audience: "USER" as const, purpose: "训练 LightGBM", prerequisites: ["冻结股票池"],
      support: ["EXPLAIN", "NAVIGATE"], limitations: ["不支持任意模型"], keywords: ["机器学习"],
    },
    {
      capability_id: "data-center", name: "数据中心", route_id: "/settings/system/data",
      audience: "ADMIN" as const, purpose: "同步行情", prerequisites: ["管理员"],
      support: ["EXPLAIN", "NAVIGATE"], limitations: [], keywords: ["数据同步"],
    },
  ],
};

const user = JSON.parse(queryProductHelp({ query: "机器学习怎么用" }, catalog).content[0].text);
assert.equal(user.matches.length, 1);
assert.equal(user.matches[0].route_id, "/model-research");
assert.equal("agent_tools" in user.matches[0], false);

const hiddenAdmin = JSON.parse(queryProductHelp({ query: "数据同步" }, catalog).content[0].text);
assert.deepEqual(hiddenAdmin.matches, []);
const admin = JSON.parse(queryProductHelp({ query: "数据同步", include_admin: true }, catalog).content[0].text);
assert.equal(admin.matches[0].audience, "ADMIN");

assert.throws(() => queryProductHelp({ query: "" }, catalog));
assert.throws(() => queryProductHelp({ query: "模型", route: "https://evil.example" }, catalog));

console.log("Product help MCP PASS: bounded search, fixed routes, admin filter, no internal tools");
