import assert from 'node:assert/strict';
import { fetchByqResearchTaskCreate, fetchByqResearchLookup } from '../src/research.js';

const payload = { owner_principal:'synthetic',title:'Original',objective:'No execution',trace_id:'trace-synthetic',idempotency_key:'original-key' };
const watch = {schema_version:'research-receipt-watch.v1',watch_id:'researchwatch_'+'a'.repeat(32),
  entity_type:'research_task',task_id:null,idempotency_key:'original-key',status:'awaiting_receipt',
  entity_id:null,attempts:1,max_attempts:8,registration_created:true};
const json = (value:unknown,status=200) => new Response(JSON.stringify(value),{status});
for (const failure of [() => {throw new Error('private transport');}, () => json({},503), () => json({},201)]) {
  const paths:string[] = [];
  const result = await fetchByqResearchTaskCreate('http://backend',payload,async (url,init) => {
    paths.push(url);
    if (url.endsWith('/submission-watches')) {
      assert.deepEqual(JSON.parse(String(init?.body)),{entity_type:'research_task',request:payload});
      return json(watch,201);
    }
    return failure();
  });
  assert.equal(paths.length,2);
  assert.equal(JSON.parse(result.content[0].text).submission_watch.watch_id,watch.watch_id);
  assert.equal(JSON.parse(result.content[0].text).status,'outcome_unknown');
  assert.doesNotMatch(result.content[0].text,/private transport/);
}
for (const status of ['awaiting_receipt','needs_attention','conflict']) {
  let writes=0;
  const result = await fetchByqResearchTaskCreate('http://backend',payload,async (url) => {
    if (!url.endsWith('/submission-watches')) writes++;
    return json({...watch,status,registration_created:false});
  });
  assert.equal(writes,0);
  assert.equal(JSON.parse(result.content[0].text).status,'outcome_unknown');
}
const id = 'task_'+'b'.repeat(32);
const paths:string[]=[];
const found=await fetchByqResearchTaskCreate('http://backend',payload,async (url,init) => {
  paths.push(url);
  if (url.endsWith('/submission-watches')) return json({...watch,status:'confirmed',entity_id:id,registration_created:false});
  assert.equal(init?.method,'GET');
  assert.equal(url,'http://backend/v1/research/tasks/'+id);
  return json({task_id:id,status:'planned'});
});
assert.equal(JSON.parse(found.content[0].text).task_id,id);
assert.equal(paths.length,2);
let lookups=0;
const invalid=await fetchByqResearchLookup('http://backend',{entity_type:'research_task',watch_id:watch.watch_id,entity_id:id},async()=>{lookups++;return json({});});
assert.equal(invalid.isError,true);assert.equal(lookups,0);
const state=await fetchByqResearchLookup('http://backend',{entity_type:'research_task',watch_id:watch.watch_id},async (url,init)=>{
  assert.equal(init?.method,'GET');assert.ok(url.endsWith(watch.watch_id));return json(watch);
});
assert.equal(state.isError,false);
console.log('Research durable watch PASS: pre-admission, unknown, restart, no repeated write and exact receipt reads');

for (const entity_type of ['research_task', 'experiment', 'artifact'] as const) {
  const field = {research_task:'task_id',experiment:'experiment_id',artifact:'artifact_id'}[entity_type];
  for (const returnedId of [undefined, null, 42, 'other', 'original']) {
    let calls = 0;
    const response = await fetchByqResearchLookup('http://backend', {
      entity_type, entity_id:'original',
    }, async (_url, init) => {
      calls++;
      assert.equal(init?.method, 'GET');
      return json({[field]:returnedId});
    });
    assert.equal(calls,1);
    assert.equal(response.isError,returnedId !== 'original', `${entity_type}: exact returned ID ${returnedId}`);
  }
}
const mismatched = await fetchByqResearchTaskCreate('http://backend',payload,async (url,init) => {
  if (url.endsWith('/submission-watches')) return json({...watch,status:'confirmed',entity_id:id,registration_created:false});
  assert.equal(init?.method,'GET');
  return json({task_id:'task_'+'c'.repeat(32),objective:'Wrong task'});
});
assert.equal(mismatched.isError,true);
assert.doesNotMatch(mismatched.content[0].text,/Wrong task/);
console.log('Exact research reads PASS: all three entity identities and confirmed-watch readback');
