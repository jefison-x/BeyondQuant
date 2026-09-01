import assert from "node:assert/strict";

import { PageCallBudget, boundedIntegerEnvironment } from "../src/page-budget.js";

let now = 10_000;
const budget = new PageCallBudget(3, 1_000, () => now);
assert.deepEqual(budget.consume("workspace/session/job-a"), {
  allowed: true, limit: 3, remaining: 2,
});
assert.equal(budget.consume("workspace/session/job-a").allowed, true);
assert.equal(budget.consume("workspace/session/job-a").allowed, true);
assert.deepEqual(budget.consume("workspace/session/job-a"), {
  allowed: false, limit: 3, remaining: 0,
});
assert.equal(budget.consume("workspace/session/job-b").allowed, true);

now += 1_001;
assert.deepEqual(budget.consume("workspace/session/job-a"), {
  allowed: true, limit: 3, remaining: 2,
});

process.env.BYQ_TEST_PAGE_LIMIT = "7";
assert.equal(boundedIntegerEnvironment("BYQ_TEST_PAGE_LIMIT", 6, 1, 20), 7);
process.env.BYQ_TEST_PAGE_LIMIT = "0";
assert.throws(
  () => boundedIntegerEnvironment("BYQ_TEST_PAGE_LIMIT", 6, 1, 20),
  /must be an integer/,
);
delete process.env.BYQ_TEST_PAGE_LIMIT;

console.log("Agent pagination call budget PASS: bounded, isolated and expiring");
