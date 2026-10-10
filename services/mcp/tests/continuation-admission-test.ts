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
// The default resolver keeps the legacy header contract: a non-ACP caller that
// still presents x-byq-root-run-id has that exact root forwarded.
assert.equal((seen[0] as { call: { root_run_id: string } }).call.root_run_id, 'b'.repeat(32));
assert.equal((await gate.fetch(request('byq_research_get', 'malformed'))).status, 403);
assert.equal(calls, 1);
const lost = continuationAdmission(handler, async () => { throw new Error('synthetic timeout'); });
assert.equal((await (await lost.fetch(request('byq_research_get'))).json()).result.isError, true);
assert.equal(calls, 1);
await gate.fetch(request('ordinary-tool', null));
assert.equal(calls, 2);

// The authenticated ACP identity, not a client header, is the authoritative
// root: the DSH MCP client sends no x-byq-root-run-id, so the resolver supplies
// root_run_id, and a blocked tools/call still carries the 2026-07-28 resultType
// discriminator so a modern client surfaces the blocker instead of a protocol error.
const seenRoots: string[] = [];
const rootGate = continuationAdmission(handler, async (_reservation, call) => {
  seenRoots.push(call.root_run_id); return false;
}, () => 'c'.repeat(32));
const noHeader = new Request('http://localhost/mcp/v1', { method: 'POST',
  headers: { 'content-type': 'application/json', 'x-byq-continuation-reservation': 'continuation_' + 'a'.repeat(32) },
  body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'byq_research_get', arguments: { task_id: 'task' } } }) });
const blocked = ((await (await rootGate.fetch(noHeader)).json()) as { result: { resultType?: string; isError: boolean } }).result;
assert.equal(seenRoots[0], 'c'.repeat(32));
assert.equal(blocked.resultType, 'complete');
assert.equal(blocked.isError, true);
console.log('continuation admission: scope, lost reply, malformed identity, authenticated root and blocked resultType passed');
