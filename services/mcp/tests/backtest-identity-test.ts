import assert from 'node:assert/strict';
import {fetchByqBacktestGet,fetchByqBacktestAnalysis,fetchByqBacktestRun,fetchByqBacktestCancel,
 fetchByqBacktestTaskGet,fetchByqBacktestTaskExecute,fetchByqBacktestTaskCancel,fetchByqSignalSnapshotGet,
 fetchByqBacktestSubmit,fetchByqBacktestTaskCreate} from '../src/backtest.js';
const job='backtest_'+'a'.repeat(32),task='backtesttask_'+'a'.repeat(32),artifact='artifact_'+'a'.repeat(32);
const wrong=async()=>new Response(JSON.stringify({job:{job_id:'backtest_'+'b'.repeat(32)},
 task:{backtest_task_id:'backtesttask_'+'b'.repeat(32)},snapshot:{artifact_id:'artifact_'+'b'.repeat(32),kind:'signal_snapshot'},job_id:'backtest_'+'b'.repeat(32),analysis:{schema_version:'backtest-analysis.v1'}}));
for(const fn of [fetchByqBacktestGet,fetchByqBacktestRun,fetchByqBacktestCancel]) {
 const response=await fn('http://backend',job,wrong);const value=JSON.parse(response.content[0].text);
 assert.ok(response.isError || value.status==='outcome_unknown','wrong job cannot confirm requested job');
}
for(const fn of [fetchByqBacktestTaskGet,fetchByqBacktestTaskExecute,fetchByqBacktestTaskCancel]) {
 const response=await fn('http://backend',task,wrong);const value=JSON.parse(response.content[0].text);
 assert.ok(response.isError || value.status==='outcome_unknown','wrong task cannot confirm original task');
}
assert.equal((await fetchByqSignalSnapshotGet('http://backend',artifact,wrong)).isError,true);
assert.equal((await fetchByqBacktestAnalysis('http://backend',job,{section:'summary',limit:1,offset:0},wrong)).isError,true);
for(const [fn,tool] of [[fetchByqBacktestSubmit,'byq_backtest_get'],[fetchByqBacktestTaskCreate,'byq_backtest_task_get']] as const) {
 const response=await fn('http://backend',{task_id:'task_'+'c'.repeat(32),idempotency_key:'original-key'},async()=>{throw Error('ack lost')});
 const value=JSON.parse(response.content[0].text);assert.equal(value.status,'outcome_unknown');assert.equal(value.reconciliation.tool,tool);
 assert.equal(value.reconciliation.arguments.idempotency_key,'original-key');
}
console.log('Backtest exact read and unknown original receipt PASS');
