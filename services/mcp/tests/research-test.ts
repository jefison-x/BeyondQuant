import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { bindActiveWebEvidenceProducer, loadWebEvidencePolicy } from "../src/web-evidence-provenance.js";

import {
  fetchByqArtifactCreate,
  fetchByqResearchTaskCreate,
  fetchByqWebEvidenceCreate,
} from "../src/research.js";

const task = await fetchByqResearchTaskCreate(
  "http://backend:8000",
  {
    owner_principal: "product-user",
    title: "Fixture task",
    objective: "Check the MCP boundary.",
    trace_id: "byq-trace-mcp-1",
    idempotency_key: "mcp-task-1",
  },
  async (url, init) => {
    assert.equal(url, "http://backend:8000/v1/research/tasks");
    assert.equal(init?.method, "POST");
    assert.doesNotMatch(String(init?.body), /sqlite|password|secret|token/i);
    return new Response(
      JSON.stringify({
        task_id: "task_0123456789abcdef0123456789abcdef",
        owner_principal: "product-user",
        title: "Fixture task",
        objective: "Check the MCP boundary.",
        status: "planned",
        trace_id: "byq-trace-mcp-1",
        created_at: "2026-08-15T00:00:00+00:00",
        updated_at: "2026-08-15T00:00:00+00:00",
        version: 1,
      }),
      { status: 201 },
    );
  },
);
assert.equal(task.isError, false);
assert.match(task.content[0].text, /task_0123456789abcdef/);
assert.doesNotMatch(task.content[0].text, /request_hash|sqlite/);

const conflict = await fetchByqArtifactCreate(
  "http://backend:8000",
  {
    task_id: "task_0123456789abcdef0123456789abcdef",
    kind: "evidence",
    content: { result: "fixture" },
    lineage: [],
    trace_id: "byq-trace-mcp-1",
    idempotency_key: "mcp-artifact-1",
  },
  async () => new Response(JSON.stringify({ detail: "SQL path /var/lib/byq/domain" }), { status: 409 }),
);
assert.equal(conflict.isError, true);
assert.match(conflict.content[0].text, /research_conflict/);
assert.doesNotMatch(conflict.content[0].text, /SQL path|var\/lib/);

const webEvidence = await fetchByqWebEvidenceCreate(
  "http://backend:8000",
  {
    task: { title: "网页研究记录", objective: "保存本轮公开网页研究证据。" },
    content: { schema_version: "web-research-evidence.v1" },
    lineage: [],
    idempotency_key: "mcp-web-evidence-1",
  },
  async (url, init) => {
    assert.equal(url, "http://backend:8000/v1/research/web-evidence-records");
    assert.equal(init?.method, "POST");
    assert.doesNotMatch(String(init?.body), /credential|password|secret|token/i);
    return new Response(
      JSON.stringify({
        record_status: "saved",
        source_count: 2,
        artifact: {
          artifact_id: "artifact_0123456789abcdef0123456789abcdef",
          kind: "web_research_evidence",
          content: { schema_version: "web-research-evidence.v1", sources: [{ source_id: "source_internal" }] },
        },
      }),
      { status: 201 },
    );
  },
);
assert.equal(webEvidence.isError, false);
assert.match(webEvidence.content[0].text, /研究记录已保存/);
assert.match(webEvidence.content[0].text, /"source_count":2/);
assert.match(webEvidence.content[0].text, /artifact_0123456789abcdef/);
assert.doesNotMatch(webEvidence.content[0].text, /schema_version|source_internal|web_research_evidence/);

let trustedBody: Record<string, unknown> | undefined;
const trustedProducer = await fetchByqWebEvidenceCreate(
  "http://backend:8000",
  {
    task: { title: "producer", objective: "bind trusted provenance" },
    content: {
      schema_version: "web-research-evidence.v1",
      search: { queries: [], stopped_reason: "NO_RESULTS" },
    },
    lineage: [],
    idempotency_key: "mcp-web-evidence-producer",
  },
  async (_url, init) => {
    trustedBody = JSON.parse(String(init?.body));
    return new Response(JSON.stringify({ record_status: "saved", source_count: 0 }), { status: 201 });
  },
);
assert.equal(trustedProducer.isError, false);
const trustedSearch = (trustedBody?.content as Record<string, unknown>).search as Record<string, unknown>;
assert.equal(trustedSearch.plugin_id, "web-search");
assert.equal(trustedSearch.plugin_version, process.env.BYQ_EXPECTED_WEB_EVIDENCE_PRODUCER ?? "0.1.1-rc.1");

let forgedRequestReachedBackend = false;
const forgedProducer = await fetchByqWebEvidenceCreate(
  "http://backend:8000",
  {
    task: { title: "producer", objective: "reject forged provenance" },
    content: {
      schema_version: "web-research-evidence.v1",
      search: { plugin_id: "web-search", plugin_version: "9.9.9", queries: [], stopped_reason: "NO_RESULTS" },
    },
    lineage: [],
    idempotency_key: "mcp-web-evidence-forged-producer",
  },
  async () => {
    forgedRequestReachedBackend = true;
    return new Response("{}", { status: 201 });
  },
);
assert.equal(forgedProducer.isError, true);
assert.equal(forgedRequestReachedBackend, false);
assert.match(forgedProducer.content[0].text, /PRODUCER_PROVENANCE/);

const invalidWebEvidence = await fetchByqWebEvidenceCreate(
  "http://backend:8000",
  {
    task: { title: "网页研究记录", objective: "保存本轮公开网页研究证据。" },
    content: { schema_version: "web-research-evidence.v1" },
    lineage: [],
    idempotency_key: "mcp-web-evidence-invalid",
  },
  async () => new Response(
    JSON.stringify({ detail: "temporal_status does not match attacker-secret-value" }),
    { status: 422 },
  ),
);
assert.equal(invalidWebEvidence.isError, true);
assert.match(invalidWebEvidence.content[0].text, /TEMPORAL_STATUS/);
assert.match(invalidWebEvidence.content[0].text, /研究记录暂未保存/);
assert.doesNotMatch(invalidWebEvidence.content[0].text, /attacker-secret-value|does not match/);

console.log("Research MCP translation PASS: normalized mutation and safe conflict");


const policyDirectory = mkdtempSync(resolve(tmpdir(), "byq-provenance-test-"));
const previousPolicyPath = process.env.BYQ_WEB_EVIDENCE_PROVENANCE_POLICY;
const defaultPolicy = loadWebEvidencePolicy();
try {
  const policyFile = resolve(policyDirectory, "policy.json");
  process.env.BYQ_WEB_EVIDENCE_PROVENANCE_POLICY = policyFile;
  for (const field of ["release_id", "attestation_sha256"] as const) {
    const invalid = structuredClone(defaultPolicy);
    invalid.active_producer[field] = field === "release_id" ? "unrelated-release" : "sha256:" + "0".repeat(64);
    writeFileSync(policyFile, JSON.stringify(invalid));
    assert.throws(() => loadWebEvidencePolicy(), /producer set/);
  }
  const candidate = JSON.parse(readFileSync(resolve(
    process.cwd() === "/app" ? "/app" : "../../config/dsh/generated",
    "dsh-0.1.2rc1.web-evidence-provenance.json",
  ), "utf8"));
  writeFileSync(policyFile, JSON.stringify(candidate));
  const bound = bindActiveWebEvidenceProducer({ search: { queries: [] } });
  assert.equal((bound.search as Record<string, unknown>).plugin_version, "0.1.2-rc.1");
  // Even a recognized old version cannot impersonate this candidate instance.
  assert.throws(() => bindActiveWebEvidenceProducer({
    search: { plugin_id: "web-search", plugin_version: "0.1.1-rc.1" },
  }), /trusted deployment/);
  candidate.mode = "qualified";
  candidate.active_producer = candidate.recognized_producers[0];
  writeFileSync(policyFile, JSON.stringify(candidate));
  assert.throws(() => loadWebEvidencePolicy(), /unqualified/);
} finally {
  if (previousPolicyPath === undefined) delete process.env.BYQ_WEB_EVIDENCE_PROVENANCE_POLICY;
  else process.env.BYQ_WEB_EVIDENCE_PROVENANCE_POLICY = previousPolicyPath;
  rmSync(policyDirectory, { recursive: true, force: true });
}
console.log("Web provenance policy PASS: complete identity, candidate isolation and active producer binding");
