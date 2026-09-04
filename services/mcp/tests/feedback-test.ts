import assert from "node:assert/strict";
import { fetchByqFeedbackCreate, fetchByqFeedbackPreview, fetchByqFeedbackSubmit } from "../src/feedback.js";

const calls: Array<{ url: string; init?: RequestInit }> = [];
const fakeFetch = async (url: string, init?: RequestInit) => {
  calls.push({ url, init });
  return new Response(JSON.stringify(url.endsWith("/preview") ? { schema_version: "feedback-publication-preview.v1", preview_hash: "a".repeat(64) } : { feedback: { feedback_id: "feedback_" + "a".repeat(32) } }), { status: 200, headers: { "content-type": "application/json" } });
};
const content = { schema_version: "product-feedback.v1", category: "bug", component: "xiaoba", severity: "normal", title: "小巴反馈测试", description: "描述", reproduction_steps: [], expected_behavior: "", actual_behavior: "", diagnostics: {}, idempotency_key: "create-1" };
assert.equal((await fetchByqFeedbackCreate("http://backend", content, fakeFetch)).isError, false);
assert.equal((await fetchByqFeedbackPreview("http://backend", "feedback_" + "a".repeat(32), 1, fakeFetch)).isError, false);
assert.equal((await fetchByqFeedbackSubmit("http://backend", "feedback_" + "a".repeat(32), { expected_version: 1, preview_hash: "a".repeat(64), disclosure_confirmed: true, agent_approval_id: "agent_approval_" + "c".repeat(32), idempotency_key: "submit-1" }, fakeFetch)).isError, false);
assert.match(String(calls[2].init?.body), /"disclosure_confirmed":true/);
assert.match(String(calls[2].init?.body), /"agent_approval_id":"agent_approval_/);
const denied = await fetchByqFeedbackSubmit("http://backend", "feedback_" + "a".repeat(32), {}, async () => new Response(JSON.stringify({ detail: "denied" }), { status: 403 }));
assert.equal(denied.isError, true);
assert.equal(JSON.parse(denied.content[0].text).backend.status, "feedback_forbidden");
console.log("Feedback MCP contract PASS: owner-only create, preview and approval-bound submit");
