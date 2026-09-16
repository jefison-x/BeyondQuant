import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer, request } from 'node:http';
import { once } from 'node:events';
import { setTimeout as delay } from 'node:timers/promises';

const reserve = createServer();
await new Promise<void>(resolve => reserve.listen(0, '127.0.0.1', resolve));
const address = reserve.address();
assert.ok(address && typeof address === 'object');
await new Promise<void>(resolve => reserve.close(() => resolve()));
const port = address.port;
const child = spawn(process.execPath, ['dist/src/server.js'], {env: {
  PATH: process.env.PATH, PORT: String(port), BYQ_MCP_TOKEN: 'synthetic-transport-only',
  BYQ_BACKEND_URL: 'http://127.0.0.1:1',
}, stdio:'ignore'});
const base = `http://127.0.0.1:${port}`;
function raw(path: string, host: string): Promise<number> {
  return new Promise(resolve => {
    const call = request({host:'127.0.0.1',port,path,method:'GET',headers:{host}}, response => {
      response.resume(); response.on('end', () => resolve(response.statusCode ?? 0));
    });
    call.setTimeout(1000, () => call.destroy());
    call.on('error', () => resolve(0)); call.end();
  });
}
try {
  let ready = false;
  for (let attempt=0;attempt<50;attempt++) {
    ready = await fetch(base+'/healthz').then(r=>r.ok).catch(()=>false);
    if (ready) break;
    await delay(50);
  }
  assert.ok(ready, 'actual MCP server must start');
  assert.equal((await fetch(base+'/mcp/v1')).status, 401);
  assert.equal((await fetch(base+'/unknown')).status, 404);
  for (const [path,host] of [['/healthz','['], ['http://[','localhost']]) {
    await raw(path!,host!);
    await delay(30);
    assert.equal(child.exitCode, null, 'malformed request must not terminate MCP');
    assert.ok(await fetch(base+'/healthz').then(r=>r.ok).catch(()=>false), 'MCP must remain available');
  }
  console.log('MCP transport resilience PASS: malformed URL/Host cannot terminate the process');
} finally {
  if (child.exitCode === null && child.signalCode === null) {child.kill('SIGTERM'); await once(child,'exit');}
}
