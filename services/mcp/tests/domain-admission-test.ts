import assert from "node:assert/strict";
import { evidenceBoundedFetcher, safeDomainAdmission } from "../src/domain-admission.js";

const pending = { detail: { schema_version: "domain-call-admission.v1", state: "blocked", reason: "call_evidence_pending" } };
assert.equal(safeDomainAdmission({ detail: { ...pending.detail, request_sha256: "private" } }), undefined);
assert.equal(safeDomainAdmission({ detail: { ...pending.detail, reason: "arbitrary" } }), undefined);
assert.equal(safeDomainAdmission(pending)?.stop, true);
assert.equal(safeDomainAdmission({ detail: { ...pending.detail, state: "correctable_failure", reason: "domain_validation_failed" } })?.stop, false);
let calls = 0;
const root = "a".repeat(32);
const fetcher = evidenceBoundedFetcher(async (_input, init) => {
  calls += 1;
  assert.equal(new Headers(init?.headers).get("x-byq-root-run-id"), root);
  assert.equal(init?.body, "unchanged original payload");
  return calls === 1 ? Response.json(pending, { status: 425 }) : Response.json({ artifact: "synthetic" }, { status: 201 });
}, root);
const result = await fetcher("http://synthetic/validate", { method: "POST", body: "unchanged original payload" });
assert.equal(result.status, 201);
assert.equal(calls, 2);
for (const status of [409, 500, 503, 422, 425]) {
  let attempts = 0;
  const send = evidenceBoundedFetcher(async () => {
    attempts += 1;
    return Response.json({ detail: "not an exact pre-execution receipt" }, { status });
  }, root);
  await send("http://synthetic/validate");
  assert.equal(attempts, 1);
}
let timeouts = 0;
await assert.rejects(evidenceBoundedFetcher(async () => {
  timeouts += 1;
  throw new Error("synthetic ambiguous timeout");
}, root)("http://synthetic/validate"));
assert.equal(timeouts, 1);
console.log("domain-admission: exact pending proof only; no ambiguous write retry");
