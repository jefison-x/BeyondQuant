import assert from 'node:assert/strict';
import { continuationAdmission } from '../src/continuation-admission.js';

let calls = 0;
const seen: unknown[] = [];
const handler = { async fetch() { calls++; return Response.json({ executed: true }); } };
const gate = continuationAdmission(handler, async (reservation, call) => {
  seen.push({ reservation, call }); return call.tool === 'byq_research_get';
});
function request(tool: string, reservation: string | null = 'continuation_' + 'a'.repeat(32)) {
  const headers: Record<string, string> = { 'content-type': 'application/json', 'x-byq-root-run-id': 'b'.repeat(32) };
  if (reservation !== null) headers['x-byq-continuation-reservation'] = reservation;
  return new Request('http://localhost/mcp/v1', { method: 'POST', headers,
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: tool, arguments: { task_id: 'task' } } }) });
}
assert.equal((await (await gate.fetch(request('byq_research_get'))).json()).executed, true);
assert.equal(calls, 1);
assert.equal((await (await gate.fetch(request('byq_agent_approval_decide'))).json()).result.isError, true);
assert.equal(calls, 1);
assert.equal(seen.length, 2);
assert.equal((await gate.fetch(request('byq_research_get', 'malformed'))).status, 403);
assert.equal(calls, 1);
const lost = continuationAdmission(handler, async () => { throw new Error('synthetic timeout'); });
assert.equal((await (await lost.fetch(request('byq_research_get'))).json()).result.isError, true);
assert.equal(calls, 1);
await gate.fetch(request('ordinary-tool', null));
assert.equal(calls, 2);
console.log('continuation admission: scope, lost reply, malformed identity and foreground isolation passed');
