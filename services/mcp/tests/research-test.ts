import { createHash } from "node:crypto";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { bindActiveWebEvidenceProducer, loadWebEvidencePolicy } from "../src/web-evidence-provenance.js";

import {
  fetchByqArtifactCreate,
  fetchByqResearchGet,
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

for (const [index, suppliedVersion] of [trustedSearch.plugin_version, "9.9.9"].entries()) {
  let suppliedProducerReachedBackend = false;
  const rejectedProducer = await fetchByqWebEvidenceCreate(
    "http://backend:8000",
    {
      task: { title: "producer", objective: "reject caller-supplied provenance" },
      content: {
        schema_version: "web-research-evidence.v1",
        search: { plugin_id: "web-search", plugin_version: suppliedVersion, queries: [], stopped_reason: "NO_RESULTS" },
      },
      lineage: [],
      idempotency_key: `mcp-web-evidence-rejected-producer-${index}`,
    },
    async () => {
      suppliedProducerReachedBackend = true;
      return new Response("{}", { status: 201 });
    },
  );
  assert.equal(rejectedProducer.isError, true);
  assert.equal(suppliedProducerReachedBackend, false);
  assert.match(rejectedProducer.content[0].text, /PRODUCER_PROVENANCE/);
}

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
  assert.throws(() => bindActiveWebEvidenceProducer({
    search: { plugin_id: "web-search", plugin_version: "0.1.2-rc.1" },
  }), /trusted deployment/);
  // Even a recognized old version cannot be supplied by the caller.
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
    const artifactId = "artifact_" + "9".repeat(32);
    const artifactHash = "9".repeat(64);
    const response = await fetchByqResearchLookup("http://backend:8000", lookup, async (url, init) => {
      calls++;
      const target = new URL(url);
      assert.equal(init?.method, "GET");
      assert.equal(init?.body, undefined);
      if (target.pathname === `/v1/research/artifacts/${artifactId}/reference`) {
        return new Response(JSON.stringify({ artifact_id: artifactId, type: "web_research_evidence",
          validation: { status: "validated", content_sha256: artifactHash } }), { status: 200 });
      }
      assert.equal(target.pathname, "/v1/research/submissions/reconcile");
      assert.equal(target.searchParams.get("idempotency_key"), lookup.idempotency_key);
      assert.equal(target.searchParams.get("task_id"), lookup.task_id ?? null);
      const entity = entity_type === "artifact"
        ? { artifact_id: artifactId, task_id: "task_original", kind: "web_research_evidence",
            status: "validated", content_sha256: artifactHash, content: { web: true } }
        : { [{ research_task: "task_id", experiment: "experiment_id", artifact: "artifact_id" }[entity_type]]: "original_id",
            ...(lookup.task_id ? { task_id: lookup.task_id } : {}), status: "planned" };
      return new Response(JSON.stringify({ schema_version: "research-submission-reconciliation.v1",
        entity_type, idempotency_key: lookup.idempotency_key, status,
        ...(status === "confirmed" ? { entity } : {}),
      }), { status: 200 });
    });
    assert.equal(calls, entity_type === "artifact" && status === "confirmed" ? 2 : 1);
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
const legacyCalls: string[] = [];
const legacyRead = await fetchByqResearchLookup("http://backend:8000", {
  entity_type: "artifact", entity_id: "artifact_original",
}, async (url, init) => {
  legacyCalls.push(url);
  assert.equal(init?.method, "GET");
  if (url.endsWith("/reference")) {
    return new Response(JSON.stringify({
      artifact_id: "artifact_original", type: "web_research_evidence",
      validation: { status: "validated", content_sha256: "a".repeat(64) },
    }), { status: 200 });
  }
  assert.equal(url, "http://backend:8000/v1/research/artifacts/artifact_original");
  return new Response(JSON.stringify({ artifact_id: "artifact_original", kind: "web_research_evidence",
    content: { search: { plugin_id: "web-search" } } }), { status: 200 });
});
assert.equal(legacyRead.isError, false);
assert.equal(JSON.parse(legacyRead.content[0].text).content.search.plugin_id, "web-search");
assert.deepEqual(legacyCalls, [
  "http://backend:8000/v1/research/artifacts/artifact_original/reference",
  "http://backend:8000/v1/research/artifacts/artifact_original",
]);


for (const target_status of ['in_progress', 'active', 'blocked']) {
  const invalid = await fetchByqResearchTransition('http://backend', {
    entity_type: 'research_task', entity_id: 'task_a', target_status, idempotency_key: 'original',
  }, async () => { throw new Error('invalid status must not reach Backend'); });
  assert.equal(invalid.isError, true);
  const body = JSON.parse(invalid.content[0].text);
  assert.equal(body.backend.status, 'research_request_invalid');
  assert.ok(body.backend.validation.allowed_values.includes('running'));
  assert.match(body.backend.validation.message, /progress.stage/);
  assert.equal(body.backend.validation.repair_limit, undefined);
}
const redundantLookup = await fetchByqResearchLookup('http://backend', {
  entity_type: 'artifact', entity_id: 'artifact_a', task_id: 'task_a',
}, async () => { throw new Error('invalid lookup must not reach Backend'); });
assert.equal(redundantLookup.isError, true);
const redundantLookupBody = JSON.parse(redundantLookup.content[0].text);
assert.match(redundantLookupBody.backend.validation.message, /entity_id.*task_id/);
assert.equal(redundantLookupBody.backend.validation.repair_limit, undefined);

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


// A signal_snapshot may only leave the MCP boundary as a bounded, safe summary.
// The Artifact reference is read first, so the raw artifact row is never even
// requested, and a reference/summary failure never falls back to raw content.
const signalId = "artifact_" + "c".repeat(32);
const signalHash = "d".repeat(64);
const signalSummary = (overrides: Record<string, unknown> = {}) => ({
  schema_version: "signal-snapshot-summary.v1",
  artifact: { artifact_id: signalId, kind: "signal_snapshot", status: "validated",
    content_sha256: signalHash, task_id: "task_signal", experiment_id: null,
    created_at: "2026-01-01T00:00:00+00:00", updated_at: "2026-01-01T00:00:00+00:00",
    version: 1, lineage: [] },
  snapshot: { schema_version: "signal-snapshot-v2", strategy: {}, universe: {},
    date_range: { start_date: "2026-01-01", end_date: "2026-01-31" },
    counts: { bar_count: 100, signal_count: 2, corporate_action_count: 0, benchmark_bar_count: 20 },
    benchmark_summary: null, execution: {}, readiness: {},
    integrity: { content_sha256: signalHash, snapshot_content_sha256: signalHash } },
  diagnostic_samples: { symbol_sample: ["000001.SZ"], bar_sample: [], signal_sample: [], corporate_action_sample: [] },
  ...overrides,
});
const rawSignalRow = {
  artifact_id: signalId, task_id: "task_signal", experiment_id: null, kind: "signal_snapshot",
  status: "validated", content_sha256: signalHash,
  content: { bars_frame: { symbols: ["000001.SZ"] }, signals: [{ symbol: "000001.SZ" }] },
};
const summaryResponse = (summary: unknown, status = 200) =>
  new Response(JSON.stringify({ summary }), { status });
// The reference contract is strictly typed: it always carries a non-empty type
// and validation.status/content_sha256, and never a kind.
const referenceResponse = (
  artifactId: string = signalId, type: string = "signal_snapshot",
  hash: string = signalHash, status: string = "validated",
  overrides: Record<string, unknown> = {},
) => new Response(JSON.stringify({
  artifact_id: artifactId, workspace_id: "ws_signal", type, ref: { kind: "artifact", id: artifactId },
  metadata: {}, owner_principal: "owner_signal", validation: { status, content_sha256: hash },
  lineage: [], created_at: "2026-01-01T00:00:00+00:00", ...overrides,
}), { status: 200 });

{
  const calls: string[] = [];
  const read = await fetchByqResearchGet("http://backend:8000", "artifact", signalId, async (url) => {
    calls.push(url);
    if (url.endsWith(`/artifacts/${signalId}/reference`)) return referenceResponse();
    if (url.endsWith(`/signal-snapshots/${signalId}/summary`)) return summaryResponse(signalSummary());
    throw new Error(`raw signal artifact read attempted: ${url}`);
  });
  assert.equal(read.isError, false);
  assert.equal(calls.length, 2);
  assert.ok(calls[0].endsWith(`/artifacts/${signalId}/reference`));
  assert.ok(calls[1].endsWith(`/signal-snapshots/${signalId}/summary`));
  const body = JSON.parse(read.content[0].text);
  assert.equal(body.artifact_id, signalId);
  assert.equal(body.task_id, "task_signal");
  assert.equal(body.kind, "signal_snapshot");
  assert.equal(body.status, "validated");
  assert.equal(body.content_sha256, signalHash);
  assert.equal(body.summary.schema_version, "signal-snapshot-summary.v1");
  assert.ok(!("content" in body));
  assert.doesNotMatch(read.content[0].text, /bars_frame|"signals"|symbol_index|date_index/);
}
console.log("Signal by-id read PASS: reference discriminator, bounded summary, no raw content");

{
  const calls: string[] = [];
  const lookup = await fetchByqResearchLookup("http://backend:8000", {
    entity_type: "artifact", idempotency_key: "signal-original-key", task_id: "task_signal",
  }, async (url) => {
    calls.push(url);
    if (url.includes("/submissions/reconcile")) return new Response(JSON.stringify({
      schema_version: "research-submission-reconciliation.v1", entity_type: "artifact",
      idempotency_key: "signal-original-key", status: "confirmed", entity: rawSignalRow,
    }), { status: 200 });
    if (url.endsWith(`/artifacts/${signalId}/reference`)) return referenceResponse();
    if (url.endsWith(`/signal-snapshots/${signalId}/summary`)) return summaryResponse(signalSummary());
    throw new Error(`raw signal artifact read attempted: ${url}`);
  });
  assert.equal(lookup.isError, false);
  assert.equal(calls.length, 3);
  const body = JSON.parse(lookup.content[0].text);
  assert.equal(body.status, "confirmed");
  assert.equal(body.entity.artifact_id, signalId);
  assert.equal(body.entity.task_id, "task_signal");
  assert.equal(body.entity.kind, "signal_snapshot");
  assert.equal(body.entity.content_sha256, signalHash);
  assert.equal(body.entity.summary.schema_version, "signal-snapshot-summary.v1");
  assert.ok(!("content" in body.entity));
  assert.doesNotMatch(lookup.content[0].text, /bars_frame|"signals"/);
}

for (const [label, body, expected] of [
  ["json", JSON.stringify({ detail: "unavailable" }), "backtest_unavailable"],
  ["non-json", "unavailable", "invalid_response"],
] as const) {
  const lookup = await fetchByqResearchLookup("http://backend:8000", {
    entity_type: "artifact", idempotency_key: "signal-original-key", task_id: "task_signal",
  }, async (url) => {
    if (url.includes("/submissions/reconcile")) return new Response(JSON.stringify({
      schema_version: "research-submission-reconciliation.v1", entity_type: "artifact",
      idempotency_key: "signal-original-key", status: "confirmed", entity: rawSignalRow,
    }), { status: 200 });
    if (url.endsWith(`/artifacts/${signalId}/reference`)) return referenceResponse();
    return new Response(body, { status: 503 });
  });
  assert.equal(lookup.isError, true, `reconcile ${label} 503`);
  assert.equal(JSON.parse(lookup.content[0].text).backend.status, expected, `reconcile ${label} 503`);
  assert.doesNotMatch(lookup.content[0].text, /bars_frame|"signals"/);
}
console.log("Signal reconcile PASS: typed reference, bounded entity, exact 503 classification, no raw fallback");

for (const [label, summaryOverride] of [
  ["id", { artifact: { ...signalSummary().artifact, artifact_id: "artifact_" + "e".repeat(32) } }],
  ["kind", { artifact: { ...signalSummary().artifact, kind: "web_research_evidence" } }],
  ["hash", { artifact: { ...signalSummary().artifact, content_sha256: "e".repeat(64) } }],
  ["status", { artifact: { ...signalSummary().artifact, status: "draft" } }],
  ["schema", { schema_version: "signal-snapshot-summary.v2" }],
  ["owner", { artifact: { ...signalSummary().artifact, owner_principal: "other_owner" } }],
  ["workspace", { artifact: { ...signalSummary().artifact, workspace_id: "other_ws" } }],
  ["extra-top-level", { extra_top: true }],
] as const) {
  const read = await fetchByqResearchGet("http://backend:8000", "artifact", signalId, async (url) =>
    url.endsWith("/reference") ? referenceResponse() : summaryResponse({ ...signalSummary(), ...summaryOverride }));
  assert.equal(read.isError, true, `summary ${label} mismatch must be rejected`);
  assert.equal(JSON.parse(read.content[0].text).backend.status, "invalid_response", `summary ${label}`);
}
{
  const read = await fetchByqResearchGet("http://backend:8000", "artifact", signalId, async () =>
    referenceResponse("artifact_" + "e".repeat(32)));
  assert.equal(read.isError, true);
  assert.equal(JSON.parse(read.content[0].text).backend.status, "invalid_response");
}
{
  const read = await fetchByqResearchGet("http://backend:8000", "artifact", signalId, async () =>
    referenceResponse(signalId, "signal_snapshot", signalHash, "validated", { type: undefined }));
  assert.equal(read.isError, true);
  assert.equal(JSON.parse(read.content[0].text).backend.status, "invalid_response");
}
{
  // A non-signal reference must not hand back a raw signal_snapshot row.
  const calls: string[] = [];
  const read = await fetchByqResearchGet("http://backend:8000", "artifact", signalId, async (url) => {
    calls.push(url);
    if (url.endsWith("/reference")) return referenceResponse(signalId, "web_research_evidence", signalHash);
    return new Response(JSON.stringify(rawSignalRow), { status: 200 });
  });
  assert.equal(read.isError, true);
  assert.deepEqual(calls, [
    `http://backend:8000/v1/research/artifacts/${signalId}/reference`,
    `http://backend:8000/v1/research/artifacts/${signalId}`,
  ]);
  assert.equal(JSON.parse(read.content[0].text).backend.status, "invalid_response");
  assert.doesNotMatch(read.content[0].text, /bars_frame|"signals"/);
}
for (const status of [403, 404] as const) {
  const read = await fetchByqResearchGet("http://backend:8000", "artifact", signalId, async () =>
    new Response(JSON.stringify({ detail: "denied" }), { status }));
  assert.equal(read.isError, true);
  assert.equal(JSON.parse(read.content[0].text).backend.status,
    status === 403 ? "research_forbidden" : "research_not_found");
}
{
  const read = await fetchByqResearchGet("http://backend:8000", "artifact", signalId, async (url) => {
    if (url.endsWith("/reference")) return referenceResponse();
    return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
  });
  assert.equal(read.isError, true);
  assert.equal(JSON.parse(read.content[0].text).backend.status, "backtest_not_found");
  assert.doesNotMatch(read.content[0].text, /bars_frame|"signals"/);
}
for (const [label, body, expected] of [
  ["json", JSON.stringify({ detail: "unavailable" }), "backtest_unavailable"],
  ["non-json", "unavailable", "invalid_response"],
] as const) {
  const read = await fetchByqResearchGet("http://backend:8000", "artifact", signalId, async (url) =>
    url.endsWith("/reference") ? referenceResponse() : new Response(body, { status: 503 }));
  assert.equal(read.isError, true, `by-id summary ${label} 503`);
  assert.equal(JSON.parse(read.content[0].text).backend.status, expected, `by-id summary ${label} 503`);
  assert.doesNotMatch(read.content[0].text, /bars_frame|"signals"/);
}
{
  const oversized = signalSummary({ diagnostic_samples: {
    symbol_sample: ["x".repeat(70 * 1024)], bar_sample: [], signal_sample: [], corporate_action_sample: [],
  } });
  const read = await fetchByqResearchGet("http://backend:8000", "artifact", signalId, async (url) =>
    url.endsWith("/reference") ? referenceResponse() : summaryResponse(oversized));
  assert.equal(read.isError, true);
  assert.equal(JSON.parse(read.content[0].text).backend.status, "invalid_response");
}
{
  // The summary alone fits inside 64 KiB, but the whole MCP payload (identity,
  // metadata, ref and wrapper) does not: the full payload is what is bounded.
  const baselength = Buffer.byteLength(JSON.stringify(signalSummary()), "utf8");
  const nearLimit = signalSummary({ diagnostic_samples: {
    symbol_sample: ["x".repeat(65536 - baselength - 80)],
    bar_sample: [], signal_sample: [], corporate_action_sample: [],
  } });
  assert.ok(Buffer.byteLength(JSON.stringify(nearLimit), "utf8") <= 65536);
  const read = await fetchByqResearchGet("http://backend:8000", "artifact", signalId, async (url) =>
    url.endsWith("/reference") ? referenceResponse() : summaryResponse(nearLimit));
  assert.equal(read.isError, true);
  assert.equal(JSON.parse(read.content[0].text).backend.status, "invalid_response");
}
{
  const leaked = signalSummary({ snapshot: { ...signalSummary().snapshot, signals: [{ symbol: "raw" }] } });
  const read = await fetchByqResearchGet("http://backend:8000", "artifact", signalId, async (url) =>
    url.endsWith("/reference") ? referenceResponse() : summaryResponse(leaked));
  assert.equal(read.isError, true);
  assert.equal(JSON.parse(read.content[0].text).backend.status, "invalid_response");
}
{
  const leaked = signalSummary({ snapshot: { ...signalSummary().snapshot, content: { bars_frame: {} } } });
  const read = await fetchByqResearchGet("http://backend:8000", "artifact", signalId, async (url) =>
    url.endsWith("/reference") ? referenceResponse() : summaryResponse(leaked));
  assert.equal(read.isError, true);
  assert.equal(JSON.parse(read.content[0].text).backend.status, "invalid_response");
}
{
  const read = await fetchByqResearchGet("http://backend:8000", "artifact", signalId, async (url) =>
    url.endsWith("/reference") ? referenceResponse() : summaryResponse({ ...signalSummary(), content: { raw: true } }));
  assert.equal(read.isError, true);
  assert.equal(JSON.parse(read.content[0].text).backend.status, "invalid_response");
}
console.log("Signal mismatches PASS: id/kind/hash/status/schema/owner/top-level, 403/404/503 and boundary fail closed");

for (const [label, entityOverride] of [
  ["missing-kind", { kind: undefined }],
  ["wrong-kind", { kind: "web_research_evidence" }],
  ["id", { artifact_id: "artifact_" + "e".repeat(32) }],
  ["hash", { content_sha256: "e".repeat(64) }],
  ["status", { status: "draft" }],
  ["task", { task_id: "task_other" }],
] as const) {
  const lookup = await fetchByqResearchLookup("http://backend:8000", {
    entity_type: "artifact", idempotency_key: "signal-original-key", task_id: "task_signal",
  }, async (url) => {
    if (url.includes("/submissions/reconcile")) return new Response(JSON.stringify({
      schema_version: "research-submission-reconciliation.v1", entity_type: "artifact",
      idempotency_key: "signal-original-key", status: "confirmed",
      entity: { ...rawSignalRow, ...entityOverride },
    }), { status: 200 });
    if (url.endsWith("/reference")) return referenceResponse();
    throw new Error(`raw summary must not be read for a ${label} mismatch`);
  });
  assert.equal(lookup.isError, true, `confirmed ${label} mismatch`);
  assert.equal(JSON.parse(lookup.content[0].text).backend.status, "invalid_response", `confirmed ${label}`);
  assert.doesNotMatch(lookup.content[0].text, /bars_frame|"signals"/);
}
{
  // A non-signal reference must not hand back a raw signal_snapshot entity.
  const lookup = await fetchByqResearchLookup("http://backend:8000", {
    entity_type: "artifact", idempotency_key: "signal-original-key", task_id: "task_signal",
  }, async (url) => {
    if (url.includes("/submissions/reconcile")) return new Response(JSON.stringify({
      schema_version: "research-submission-reconciliation.v1", entity_type: "artifact",
      idempotency_key: "signal-original-key", status: "confirmed", entity: rawSignalRow,
    }), { status: 200 });
    return referenceResponse(signalId, "web_research_evidence", signalHash);
  });
  assert.equal(lookup.isError, true);
  assert.equal(JSON.parse(lookup.content[0].text).backend.status, "invalid_response");
  assert.doesNotMatch(lookup.content[0].text, /bars_frame|"signals"/);
}
console.log("Confirmed reconcile mismatches PASS: typed reference and identity/kind/hash/status must agree");

{
  const read = await fetchByqResearchGet("http://backend:8000", "artifact", signalId, async () =>
    new Response(JSON.stringify({ artifact_id: signalId, content: { bars_frame: {} } }), { status: 200 }));
  assert.equal(read.isError, true);
  assert.equal(JSON.parse(read.content[0].text).backend.status, "invalid_response");
}

const webId = "artifact_" + "f".repeat(32);
{
  const calls: string[] = [];
  const read = await fetchByqResearchGet("http://backend:8000", "artifact", webId, async (url) => {
    calls.push(url);
    if (url.endsWith(`/artifacts/${webId}/reference`)) return new Response(JSON.stringify({
      artifact_id: webId, workspace_id: "ws", type: "web_research_evidence",
      ref: { kind: "artifact", id: webId }, metadata: {}, owner_principal: "owner",
      validation: { status: "validated", content_sha256: signalHash },
      lineage: [], created_at: "2026-01-01T00:00:00+00:00",
    }), { status: 200 });
    if (url.endsWith(`/artifacts/${webId}`)) return new Response(JSON.stringify({
      artifact_id: webId, task_id: "task_web", kind: "web_research_evidence", status: "validated",
      content_sha256: signalHash, content: { search: { plugin_id: "web-search" } },
    }), { status: 200 });
    throw new Error(`unexpected ${url}`);
  });
  assert.equal(read.isError, false);
  assert.deepEqual(calls, [
    `http://backend:8000/v1/research/artifacts/${webId}/reference`,
    `http://backend:8000/v1/research/artifacts/${webId}`,
  ]);
  assert.equal(JSON.parse(read.content[0].text).content.search.plugin_id, "web-search");
}
{
  const calls: string[] = [];
  const lookup = await fetchByqResearchLookup("http://backend:8000", {
    entity_type: "artifact", idempotency_key: "web-original-key", task_id: "task_web",
  }, async (url) => {
    calls.push(url);
    if (url.includes("/submissions/reconcile")) return new Response(JSON.stringify({
      schema_version: "research-submission-reconciliation.v1", entity_type: "artifact",
      idempotency_key: "web-original-key", status: "confirmed",
      entity: { artifact_id: webId, task_id: "task_web", kind: "web_research_evidence",
        status: "validated", content_sha256: signalHash,
        content: { search: { plugin_id: "web-search" } } },
    }), { status: 200 });
    if (url.endsWith(`/artifacts/${webId}/reference`)) {
      return referenceResponse(webId, "web_research_evidence", signalHash);
    }
    throw new Error(`unexpected ${url}`);
  });
  assert.equal(lookup.isError, false);
  assert.equal(calls.length, 2);
  assert.equal(JSON.parse(lookup.content[0].text).entity.content.search.plugin_id, "web-search");
}
console.log("Non-signal Artifact compatibility PASS: original full-row read and reconcile preserved");


// The signal response is a fixed, closed shape: reference metadata/ref and
// owner/workspace never reach the Agent even if the reference is poisoned.
{
  const calls: string[] = [];
  const read = await fetchByqResearchGet("http://backend:8000", "artifact", signalId, async (url) => {
    calls.push(url);
    if (url.endsWith("/reference")) {
      return referenceResponse(signalId, "signal_snapshot", signalHash, "validated", {
        metadata: { poison: "REFMETA_SECRET" },
        ref: { poison: "REFREF_SECRET" },
        owner_principal: { nested: "OWNER_SECRET" },
        workspace_id: { nested: "WS_SECRET" },
      });
    }
    return summaryResponse(signalSummary());
  });
  assert.equal(read.isError, false);
  const body = JSON.parse(read.content[0].text);
  assert.deepEqual(Object.keys(body).sort(),
    ["artifact_id", "content_sha256", "kind", "service", "status", "summary", "task_id"]);
  assert.doesNotMatch(read.content[0].text, /REFMETA_SECRET|REFREF_SECRET|OWNER_SECRET|WS_SECRET/);
  assert.deepEqual(calls, [
    `http://backend:8000/v1/research/artifacts/${signalId}/reference`,
    `http://backend:8000/v1/research/signal-snapshots/${signalId}/summary`,
  ]);
}
console.log("Signal payload closure PASS: fixed keys, poisoned reference metadata/ref/owner/workspace excluded");

const reconcileConfirmed = (entity: unknown, key = "signal-original-key") =>
  new Response(JSON.stringify({
    schema_version: "research-submission-reconciliation.v1", entity_type: "artifact",
    idempotency_key: key, status: "confirmed", entity,
  }), { status: 200 });
const missingDiagnosticSamples = { ...signalSummary() } as Record<string, unknown>;
delete missingDiagnosticSamples.diagnostic_samples;
const malformedSummaries: Array<[string, unknown]> = [
  ["missing-diagnostic_samples", missingDiagnosticSamples],
  ["missing-snapshot", signalSummary({ snapshot: undefined })],
  ["snapshot-not-record", signalSummary({ snapshot: "not-a-record" })],
  ["diagnostic-samples-not-record", signalSummary({ diagnostic_samples: "not-a-record" })],
  ["integrity-missing", signalSummary({ snapshot: { ...signalSummary().snapshot, integrity: undefined } })],
  ["integrity-not-record", signalSummary({ snapshot: { ...signalSummary().snapshot, integrity: "not-a-record" } })],
  ["integrity-hash-mismatch", signalSummary({ snapshot: {
    ...signalSummary().snapshot, integrity: { content_sha256: "e".repeat(64) } } })],
  ["strategy-not-record", signalSummary({ snapshot: {
    ...signalSummary().snapshot, strategy: "not-a-record" } })],
];
for (const [label, malformed] of malformedSummaries) {
  const read = await fetchByqResearchGet("http://backend:8000", "artifact", signalId, async (url) =>
    url.endsWith("/reference") ? referenceResponse() : summaryResponse(malformed));
  assert.equal(read.isError, true, `by-id malformed summary ${label}`);
  assert.equal(JSON.parse(read.content[0].text).backend.status, "invalid_response", `by-id ${label}`);
}
for (const [label, malformed] of malformedSummaries) {
  const lookup = await fetchByqResearchLookup("http://backend:8000", {
    entity_type: "artifact", idempotency_key: "signal-original-key", task_id: "task_signal",
  }, async (url) => {
    if (url.includes("/submissions/reconcile")) return reconcileConfirmed(rawSignalRow);
    if (url.endsWith("/reference")) return referenceResponse();
    return summaryResponse(malformed);
  });
  assert.equal(lookup.isError, true, `confirmed malformed summary ${label}`);
  assert.equal(JSON.parse(lookup.content[0].text).backend.status, "invalid_response", `confirmed ${label}`);
}
console.log("Signal summary shape PASS: exact four top-level fields, record blocks and integrity hash on both entries");

for (const field of ["parameters", "source", "snapshot"] as const) {
  const injected = signalSummary({ snapshot: {
    ...signalSummary().snapshot, strategy: { [field]: "INJECTED" } } });
  const read = await fetchByqResearchGet("http://backend:8000", "artifact", signalId, async (url) =>
    url.endsWith("/reference") ? referenceResponse() : summaryResponse(injected));
  assert.equal(read.isError, true, `strategy ${field} injection`);
  assert.equal(JSON.parse(read.content[0].text).backend.status, "invalid_response", `strategy ${field}`);
}
console.log("Signal strategy closure PASS: parameters/source/snapshot rejected inside snapshot.strategy");
