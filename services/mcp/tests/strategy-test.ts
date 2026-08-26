import assert from "node:assert/strict";

import {
  fetchByqStrategyApprove,
  fetchByqStrategyDraftDelete,
  fetchByqStrategyDraftSave,
  fetchByqStrategyExport,
  fetchByqStrategyValidate,
  fetchByqStrategyVersionCreate,
  strategyValidationInputSchema,
} from "../src/strategy.js";

const taskId = "task_0123456789abcdef0123456789abcdef";
const artifactId = "artifact_0123456789abcdef0123456789abcdef";
const request = {
  task_id: taskId,
  trace_id: "byq-trace-strategy-mcp",
  idempotency_key: "strategy-mcp-1",
};
const validStrategy = {
  strategy_id: "MomentumStrategy",
  name: "Momentum",
  category: "momentum",
  data_requirements: { benchmark: "000300.SH", daily_basic: ["pe_ttm", "pb"] },
  script: "class CustomStrategy:\n    def generate_signals(self, data, parameters):\n        return {}",
};
assert.equal(strategyValidationInputSchema.safeParse({ ...request, strategy: validStrategy }).success, true);
assert.equal(strategyValidationInputSchema.safeParse({
  ...request,
  strategy: { ...validStrategy, data_requirements: { daily_basic: ["not_a_byq_field"] } },
}).success, false);
assert.equal(strategyValidationInputSchema.safeParse({
  ...request,
  strategy: { ...validStrategy, untrusted_extension: true },
}).success, false);

const validated = await fetchByqStrategyValidate(
  "http://backend:8000",
  { ...request, strategy: validStrategy },
  async (url, init) => {
    assert.equal(url, "http://backend:8000/v1/research/strategies/validate");
    assert.equal(init?.method, "POST");
    assert.doesNotMatch(String(init?.body), /password|secret|token/i);
    assert.match(String(init?.body), /generate_signals/);
    assert.match(String(init?.body), /data_requirements/);
    return new Response(JSON.stringify({ validation: { success: true }, artifact: { artifact_id: artifactId } }), { status: 201 });
  },
);
assert.equal(validated.isError, false);
assert.match(validated.content[0].text, /"success":true/);

const draftSaved = await fetchByqStrategyDraftSave(
  "http://backend:8000",
  { ...request, strategy: validStrategy },
  async (url, init) => {
    assert.equal(url, "http://backend:8000/v1/research/strategies/drafts");
    assert.equal(init?.method, "POST");
    assert.doesNotMatch(String(init?.body), /password|secret|token/i);
    return new Response(JSON.stringify({ artifact: { artifact_id: artifactId, kind: "strategy_draft", status: "draft" }, validation: { success: true } }), { status: 201 });
  },
);
assert.equal(draftSaved.isError, false);
assert.match(draftSaved.content[0].text, /strategy_draft/);

const draftDeleted = await fetchByqStrategyDraftDelete(
  "http://backend:8000",
  artifactId,
  async (url, init) => {
    assert.equal(url, `http://backend:8000/v1/research/strategies/drafts/${artifactId}`);
    assert.equal(init?.method, "DELETE");
    return new Response(JSON.stringify({ artifact: { artifact_id: artifactId, kind: "strategy_draft", status: "superseded" } }), { status: 200 });
  },
);
assert.equal(draftDeleted.isError, false);
assert.match(draftDeleted.content[0].text, /superseded/);

const version = await fetchByqStrategyVersionCreate(
  "http://backend:8000",
  { ...request, draft_artifact_id: artifactId },
  async (url, init) => {
    assert.equal(url, "http://backend:8000/v1/research/strategies/versions");
    assert.equal(init?.method, "POST");
    return new Response(JSON.stringify({ artifact: { kind: "strategy_version", status: "validated" } }), { status: 201 });
  },
);
assert.equal(version.isError, false);

const approved = await fetchByqStrategyApprove(
  "http://backend:8000",
  { ...request, strategy_version_artifact_id: artifactId, reviewer_principal: "human-owner", decision: "approved" },
  async (url, init) => {
    assert.equal(url, "http://backend:8000/v1/research/strategies/approvals");
    assert.equal(init?.method, "POST");
    return new Response(JSON.stringify({ approval: { execution_authorized: true, execution_outcome: "not_started" } }), { status: 201 });
  },
);
assert.equal(approved.isError, false);
assert.match(approved.content[0].text, /not_started/);

const exported = await fetchByqStrategyExport(
  "http://backend:8000",
  artifactId,
  async (url, init) => {
    assert.equal(url, `http://backend:8000/v1/research/strategies/versions/${artifactId}/export`);
    assert.equal(init?.method, "GET");
    return new Response(JSON.stringify({ export: { version_id: "a".repeat(64) } }), { status: 200 });
  },
);
assert.equal(exported.isError, false);
assert.match(exported.content[0].text, /version_id/);

const invalid = await fetchByqStrategyValidate(
  "http://backend:8000",
  request,
  async () => new Response(JSON.stringify({ detail: "strategy failed BYQ static validation: CustomStrategy must implement generate_signals or generate_target_weights" }), { status: 422 }),
);
assert.equal(invalid.isError, true);
assert.match(invalid.content[0].text, /strategy_request_invalid/);
assert.match(invalid.content[0].text, /CustomStrategy must implement generate_signals/);
assert.match(invalid.content[0].text, /"repair_limit":1/);

const sensitiveInvalid = await fetchByqStrategyValidate(
  "http://backend:8000",
  request,
  async () => new Response(JSON.stringify({ detail: "validator path /home/service/private.py token=do-not-expose" }), { status: 422 }),
);
assert.equal(sensitiveInvalid.isError, true);
assert.doesNotMatch(sensitiveInvalid.content[0].text, /private\.py|do-not-expose/);
assert.doesNotMatch(sensitiveInvalid.content[0].text, /"validation"/);

console.log("Strategy MCP translation PASS: draft save/delete, validation, version, approval, export and safe error mapping");
