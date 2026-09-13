import { createHash } from "node:crypto";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { bindActiveWebEvidenceProducer, loadWebEvidencePolicy } from "../src/web-evidence-provenance.js";

import {
  fetchByqArtifactCreate,
  fetchByqResearchLookup,
  fetchByqResearchTaskCreate,
  fetchByqResearchTransition,
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
    if (url.endsWith('/submission-watches')) return new Response(JSON.stringify({
      schema_version:'research-receipt-watch.v1',watch_id:'researchwatch_'+'a'.repeat(32),
      entity_type:'research_task',task_id:null,idempotency_key:'mcp-task-1',status:'awaiting_receipt',
      entity_id:null,attempts:1,max_attempts:8,registration_created:true,
    }),{status:201});
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

const checkpoint = {
  schema_version: "research-progress.v1" as const, stage: "blocked", next_action: "review_report",
  blocked_reason: "等待研究证据", linked_objects: [], completion_evidence: [],
};
const checkpointResult = await fetchByqResearchTransition("http://backend:8000", {
  entity_type: "research_task", entity_id: "task_0123456789abcdef0123456789abcdef",
  target_status: "running", idempotency_key: "checkpoint-original-key", progress: checkpoint,
}, async (url, init) => {
  assert.match(url, /tasks\/task_0123456789abcdef0123456789abcdef\/transitions$/);
  assert.deepEqual(JSON.parse(String(init?.body)), {
    target_status: "running", idempotency_key: "checkpoint-original-key", progress: checkpoint,
  });
  return new Response(JSON.stringify({ status: "running", progress: checkpoint }), { status: 200 });
});
assert.equal(checkpointResult.isError, false);
assert.match(checkpointResult.content[0].text, /research-progress.v1/);

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

function webReceipt(key: string, title: string, objective: string, sourceCount = 2) {
  const taskId = 'task_' + 'a'.repeat(32);
  return { record_status: 'saved', idempotency_key:key, source_count: sourceCount,
    task: { task_id: taskId, title, objective },
    artifact: { artifact_id: 'artifact_0123456789abcdef0123456789abcdef', task_id: taskId,
      kind: 'web_research_evidence',
      content: { sources: Array.from({length: sourceCount}, () => ({source_id:'source_internal'})) } },
  };
}

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
      JSON.stringify(webReceipt('mcp-web-evidence-1', '网页研究记录', '保存本轮公开网页研究证据。')),
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
    return new Response(JSON.stringify(webReceipt('mcp-web-evidence-producer', 'producer', 'bind trusted provenance', 0)), { status: 201 });
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


for (const entity_type of ["research_task", "experiment", "artifact"] as const) {
  for (const status of ["confirmed", "outcome_unknown"] as const) {
    let calls = 0;
    const lookup = { entity_type, idempotency_key: "original/key &中文",
      ...(entity_type === "research_task" ? {} : { task_id: "task_original" }) };
    const response = await fetchByqResearchLookup("http://backend:8000", lookup, async (url, init) => {
      calls++;
      const target = new URL(url);
      assert.equal(target.pathname, "/v1/research/submissions/reconcile");
      assert.equal(target.searchParams.get("idempotency_key"), lookup.idempotency_key);
      assert.equal(target.searchParams.get("task_id"), lookup.task_id ?? null);
      assert.equal(init?.method, "GET");
      assert.equal(init?.body, undefined);
      return new Response(JSON.stringify({ schema_version: "research-submission-reconciliation.v1",
        entity_type, idempotency_key: lookup.idempotency_key, status,
        ...(status === "confirmed" ? { entity: { [{ research_task: "task_id", experiment: "experiment_id", artifact: "artifact_id" }[entity_type]]: "original_id", ...(lookup.task_id ? { task_id: lookup.task_id } : {}), status: "planned" } } : {}),
      }), { status: 200 });
    });
    assert.equal(calls, 1);
    assert.equal(response.isError, false);
    assert.equal(JSON.parse(response.content[0].text).status, status);
    if (status === "outcome_unknown") assert.equal(JSON.parse(response.content[0].text).retryable, false);
  }
}
for (const request of [
  { entity_type: "research_task" as const },
  { entity_type: "research_task" as const, entity_id: "task_a", idempotency_key: "key" },
  { entity_type: "research_task" as const, idempotency_key: "key", task_id: "task_a" },
  { entity_type: "artifact" as const, idempotency_key: "key" },
  { entity_type: "artifact" as const, entity_id: "artifact_a", task_id: "task_a" },
]) {
  const response = await fetchByqResearchLookup("http://backend:8000", request, async () => {
    assert.fail("invalid selectors must not call Backend");
  });
  assert.equal(response.isError, true);
}
for (const failure of ["transport", "invalid", "wrong_key", "missing_id"] as const) {
  let calls = 0;
  const response = await fetchByqResearchLookup("http://backend:8000", {
    entity_type: "research_task", idempotency_key: "key",
  }, async () => {
    calls++;
    if (failure === "transport") throw new Error("synthetic transport failure");
    return new Response(JSON.stringify(failure === "invalid" ? {} : {
      schema_version: "research-submission-reconciliation.v1", status: "confirmed", entity_type: "research_task",
      idempotency_key: failure === "wrong_key" ? "other" : "key", entity: {},
    }), { status: 200 });
  });
  assert.equal(calls, 1);
  assert.equal(response.isError, true);
  assert.doesNotMatch(response.content[0].text, /synthetic transport failure/);
}
const legacyRead = await fetchByqResearchLookup("http://backend:8000", {
  entity_type: "artifact", entity_id: "artifact_original",
}, async (url, init) => {
  assert.equal(url, "http://backend:8000/v1/research/artifacts/artifact_original");
  assert.equal(init?.method, "GET");
  return new Response(JSON.stringify({ artifact_id: "artifact_original" }), { status: 200 });
});
assert.equal(legacyRead.isError, false);


for (const target_status of ['in_progress', 'active', 'blocked']) {
  const invalid = await fetchByqResearchTransition('http://backend', {
    entity_type: 'research_task', entity_id: 'task_a', target_status, idempotency_key: 'original',
  }, async () => { throw new Error('invalid status must not reach Backend'); });
  assert.equal(invalid.isError, true);
  const body = JSON.parse(invalid.content[0].text);
  assert.equal(body.backend.status, 'research_request_invalid');
  assert.ok(body.backend.validation.allowed_values.includes('running'));
  assert.match(body.backend.validation.message, /progress.stage/);
}
const redundantLookup = await fetchByqResearchLookup('http://backend', {
  entity_type: 'artifact', entity_id: 'artifact_a', task_id: 'task_a',
}, async () => { throw new Error('invalid lookup must not reach Backend'); });
assert.equal(redundantLookup.isError, true);
assert.match(JSON.parse(redundantLookup.content[0].text).backend.validation.message, /entity_id.*task_id/);

for (const entity_type of ["experiment", "artifact"] as const) {
  for (const task_id of [undefined, "task_other", null, 42]) {
    let calls = 0;
    const response = await fetchByqResearchLookup("http://backend:8000", {
      entity_type, idempotency_key: "original-key", task_id: "task_original",
    }, async (_url, init) => {
      calls++;
      assert.equal(init?.method, "GET");
      return new Response(JSON.stringify({
        schema_version: "research-submission-reconciliation.v1", status: "confirmed",
        entity_type, idempotency_key: "original-key",
        entity: { [entity_type + "_id"]: entity_type + "_original", task_id },
      }));
    });
    assert.equal(calls, 1);
    assert.equal(response.isError, true, `${entity_type}: reject mismatched parent ${task_id}`);
    assert.equal(JSON.parse(response.content[0].text).backend.status, "invalid_response");
  }
}
console.log("Research receipt parent binding PASS: missing, wrong and malformed task identities rejected");

// A successful HTTP envelope is not evidence that the original record was saved.
for (const invalidReceipt of [{}, { record_status: 'saved', source_count: 0 },
  { record_status: 'not_saved', source_count: 2, artifact: { artifact_id: 'artifact_' + 'a'.repeat(32) } }]) {
  const receipt = await fetchByqWebEvidenceCreate('http://backend:8000', {
    task: { title: 'receipt', objective: 'Validate committed identity' },
    content: { schema_version: 'web-research-evidence.v1' }, lineage: [],
    idempotency_key: 'web-original-receipt',
  }, async () => new Response(JSON.stringify(invalidReceipt), { status: 201 }));
  const body = JSON.parse(receipt.content[0].text);
  assert.equal(body.status, 'outcome_unknown');
  assert.equal(body.idempotency_key, 'web-original-receipt');
  const digest = createHash('sha256').update('web-original-receipt').digest('hex').slice(0, 32);
  assert.deepEqual(body.reconciliation.arguments, {
    entity_type: 'research_task', idempotency_key: `web-record-task:${digest}`,
  });
  assert.equal(body.reconciliation.then.idempotency_key, `web-record-artifact:${digest}`);
  assert.equal(body.reconciliation.then.task_id_source, 'confirmed_original_task_id');
  assert.doesNotMatch(receipt.content[0].text, /研究记录已保存/);
}

for (const corrupt of [
  (row: ReturnType<typeof webReceipt>) => { row.task.task_id = 'task_' + 'b'.repeat(32); },
  (row: ReturnType<typeof webReceipt>) => { row.idempotency_key = 'other-key'; },
  (row: ReturnType<typeof webReceipt>) => { row.task.objective = 'unrelated goal'; },
  (row: ReturnType<typeof webReceipt>) => { row.artifact.task_id = 'task_' + 'f'.repeat(32); },
  (row: ReturnType<typeof webReceipt>) => { row.artifact.kind = 'strategy_version'; },
  (row: ReturnType<typeof webReceipt>) => { row.artifact.artifact_id = 'bad-id'; },
  (row: ReturnType<typeof webReceipt>) => { row.source_count = 3; },
]) {
  const row = webReceipt('web-original-receipt', 'receipt', 'Validate committed identity');
  corrupt(row);
  const receipt = await fetchByqWebEvidenceCreate('http://backend:8000', {
    task: { title: 'receipt', objective: 'Validate committed identity' },
    content: { schema_version: 'web-research-evidence.v1' }, lineage: [],
    idempotency_key: 'web-original-receipt',
  }, async () => new Response(JSON.stringify(row), { status: 201 }));
  assert.equal(JSON.parse(receipt.content[0].text).status, 'outcome_unknown');
}
console.log('Web evidence receipt PASS: original key, goal, object lineage and source count');

const paddedKey = await fetchByqWebEvidenceCreate('http://backend:8000', {
  task: { title: ' receipt ', objective: ' Validate committed identity ' },
  content: { schema_version: 'web-research-evidence.v1' }, lineage: [],
  idempotency_key: ' web-original-receipt ',
}, async () => new Response(JSON.stringify(webReceipt('web-original-receipt', 'receipt', 'Validate committed identity')), {status:201}));
assert.equal(JSON.parse(paddedKey.content[0].text).status, 'ok');
