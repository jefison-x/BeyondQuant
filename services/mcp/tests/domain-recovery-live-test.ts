/** Explicit isolated Backend probe: submit/lose ACK, exit, restart Backend, GET from new process. */
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {fetchByqPoolCreate,fetchByqPoolCreationReconcile} from '../src/stock-pool.js';
import {fetchByqLearningRunStart,fetchByqLearningIterationRecord,fetchByqLearningSignalCreate,fetchByqLessonPropose,fetchByqLearningReceipt} from '../src/learning.js';
import {fetchByqFeedbackCreate,fetchByqFeedbackReceipt} from '../src/feedback.js';
assert.equal(process.env.BYQ_H4_RECOVERY,'1');
const fixture = JSON.parse(readFileSync('/evidence/domain-fixture.json','utf8'));
const phase = process.env.BYQ_H4_PHASE;
assert.ok(phase === 'submit' || phase === 'recover');
const saved:any[] = phase === 'recover' ? JSON.parse(readFileSync('/evidence/domain-receipts.json','utf8')) : [];
const backend = 'http://backend:8000';
for(const [index,{kind,payload}] of fixture.cases.entries()) {
  let writes = 0;
  const fetcher = async(url:string,init?:RequestInit) => {
    if(phase === 'recover') assert.equal(init?.method,'GET');
    const response = await fetch(url,{...init,headers:{...init?.headers,...fixture.headers}});
    if(init?.method === 'POST') {
      writes++;
      assert.equal(response.status,201);
      saved.push({kind,body:await response.json()});
      throw Error('synthetic loss after actual commit');
    }
    return response;
  };
  if(phase === 'submit') {
    const context = fixture.context;
    const creators:Record<string,()=>Promise<any>> = {
      pool:()=>fetchByqPoolCreate(backend,payload,context,fetcher),
      run:()=>fetchByqLearningRunStart(backend,payload,context,fetcher),
      iteration:()=>fetchByqLearningIterationRecord(backend,fixture.run_id,payload,context,fetcher),
      signal:()=>fetchByqLearningSignalCreate(backend,payload,context,fetcher),
      lesson:()=>fetchByqLessonPropose(backend,payload,context,fetcher),
      feedback:()=>fetchByqFeedbackCreate(backend,payload,fetcher),
    };
    const result = await creators[kind]();
    assert.equal(JSON.parse(result.content[0].text).status,'outcome_unknown');assert.equal(writes,1);
  } else {
    const result = kind === 'pool' ? await fetchByqPoolCreationReconcile(backend,'custom',payload.idempotency_key,fixture.context,fetcher)
      : kind === 'feedback' ? await fetchByqFeedbackReceipt(backend,{operation:'create',idempotency_key:payload.idempotency_key},fetcher)
      : await fetchByqLearningReceipt(backend,kind,{idempotency_key:payload.idempotency_key,...(kind === 'iteration' ? {run_id:fixture.run_id}:{task_id:fixture.task_id})},fixture.context,fetcher);
    assert.equal(result.isError,false);
    const value = JSON.parse(result.content[0].text); assert.equal(value.state,'confirmed');
    const field = kind === 'pool' ? 'pool' : kind;
    const original = saved[index].body[field] ?? saved[index].body; // lesson proposal is the direct object
    assert.deepEqual(value[field],original);
    assert.equal(writes,0);
  }
}
if(phase === 'submit') writeFileSync('/evidence/domain-receipts.json',JSON.stringify(saved));
console.log('H4 six-family real Backend '+phase+' PASS; no recovery writes');
