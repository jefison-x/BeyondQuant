import assert from 'node:assert/strict';
import {
  RESEARCH_JUDGMENT_STAGE_HEADER,
  STAGE_READ_TOOLS,
  researchJudgmentAdmission,
} from '../src/research-judgment-admission.js';

let calls = 0;
const handler = { async fetch() { calls++; return Response.json({ executed: true }); } };
const gate = researchJudgmentAdmission(handler);

function request(tool: string, stage: string | null = 'backtest_analysis') {
  const headers: Record<string, string> = { 'content-type': 'application/json' };
  if (stage !== null) headers[RESEARCH_JUDGMENT_STAGE_HEADER] = stage;
  return new Request('http://localhost/mcp/v1', { method: 'POST', headers,
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call',
      params: { name: tool, arguments: { task_id: 'task' } } }) });
}

// A read-only tool for the stage is admitted.
assert.equal((await (await gate.fetch(request('byq_backtest_analysis_get'))).json()).executed, true);
assert.equal(calls, 1);
// Every write/approval/execute tool is blocked in a bounded judgment turn.
for (const write of ['byq_backtest_task_execute', 'byq_backtest_task_create',
  'byq_strategy_version_create', 'byq_agent_approval_decide', 'byq_research_transition',
  'byq_backtest_task_prepare']) {
  const blocked = await (await gate.fetch(request(write))).json();
  assert.equal(blocked.result.isError, true, write);
  assert.match(blocked.result.content[0].text, /research_judgment_tool_not_allowed/);
}
assert.equal(calls, 1);
// An unknown stage fails closed.
assert.equal((await (await gate.fetch(request('byq_research_get', 'secret-hook'))).json()).result.isError, true);
assert.equal(calls, 1);
// No header = ordinary foreground traffic, unchanged.
await gate.fetch(request('byq_backtest_task_execute', null));
assert.equal(calls, 2);
// Non-tool methods pass through.
const ping = new Request('http://localhost/mcp/v1', { method: 'POST',
  headers: { 'content-type': 'application/json', [RESEARCH_JUDGMENT_STAGE_HEADER]: 'strategy_draft' },
  body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }) });
assert.equal((await (await gate.fetch(ping)).json()).executed, true);
assert.equal(calls, 3);
// The enumerated read tools are exactly the four read-only names per stage.
for (const [stage, tools] of Object.entries(STAGE_READ_TOOLS)) {
  for (const tool of tools) {
    assert.doesNotMatch(tool, /_create$|_execute$|_approve$|_decide$|_transition$|_prepare$/, `${stage}:${tool}`);
  }
}
console.log('research-judgment admission: stage-scoped read-only tools enforced, writes blocked PASS');
