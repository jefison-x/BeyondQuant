/** Run explicitly against isolated Backend; separate invocations span its restart. */
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { fetchByqResearchTaskCreate, fetchByqExperimentCreate, fetchByqArtifactCreate, fetchByqResearchLookup } from '../src/research.js';
import { fetchByqFactorCompute } from '../src/factor-research.js';

assert.equal(process.env.BYQ_H4_RECOVERY, '1');
const fixture = JSON.parse(readFileSync('/evidence/fixture.json', 'utf8'));
const backend = 'http://backend:8000';
const phase = process.env.BYQ_H4_PHASE;
assert.ok(phase === 'submit' || phase === 'recover');
const saved: any[] = phase === 'recover' ? JSON.parse(readFileSync('/evidence/receipts.json', 'utf8')) : [];
for (const [index, entry] of fixture.cases.entries()) {
  const { kind, payload } = entry;
  let writes = 0;
  const fetcher = async (url: string, init?: RequestInit) => {
    if (phase === 'recover') assert.equal(init?.method, 'GET', 'recovery must never replay a write');
    if (init?.method === 'POST') writes++;
    const response = await fetch(url, {...init, headers:{...init?.headers, ...fixture.headers}});
    if (phase === 'submit' && init?.method === 'POST' && !url.endsWith('/submission-watches')) {
      assert.equal(response.status, 201);
      const original = await response.json() as any;
      const entity = kind === 'factor' ? original.artifact : original;
      saved.push({kind, entity});
      // Real HTTP commit succeeded; lose its response before MCP can acknowledge it.
      throw new Error('synthetic response loss after server commit');
    }
    return response;
  };
  if (phase === 'submit') {
    const creators = {research_task:fetchByqResearchTaskCreate, experiment:fetchByqExperimentCreate,
      artifact:fetchByqArtifactCreate, factor:fetchByqFactorCompute};
    const response = await creators[kind as keyof typeof creators](backend, payload, fetcher);
    assert.equal(JSON.parse(response.content[0].text).status, 'outcome_unknown');
    assert.equal(writes, kind === 'factor' ? 1 : 2);
  } else {
    const entity_type = kind === 'factor' ? 'artifact' : kind;
    const response = await fetchByqResearchLookup(backend, {entity_type,
      idempotency_key:payload.idempotency_key,
      ...(entity_type === 'research_task' ? {} : {task_id:payload.task_id})}, fetcher);
    assert.equal(response.isError, false);
    const value = JSON.parse(response.content[0].text);
    assert.equal(value.status, 'confirmed');
    assert.deepEqual(value.entity, saved[index].entity);
    assert.equal(writes, 0);
  }
}
if (phase === 'submit') writeFileSync('/evidence/receipts.json', JSON.stringify(saved));
console.log(`H4 real Backend ${phase} PASS: four original identities, no recovery writes`);
