// Run inside the ACP image: node --expose-gc --test <this file>.
// Exercise the unchanged native provider, including redirect:error and body reads.
import assert from 'node:assert/strict';
import http from 'node:http';
import test from 'node:test';
import { DeepSeekSearchProvider } from '/opt/dsh-runtime/packages/web/web-search-deepseek/lib/index.js';
import { deadline } from '/opt/dsh-runtime/packages/util/timeout/lib/index.js';

for (const phase of ['headers', 'body', 'error-body']) {
  for (const count of [1, 2]) {
    test(`native search cancels ${phase}, queries=${count}, after GC`, async () => {
      assert.equal(typeof globalThis.gc, 'function', 'run Node with --expose-gc');
      const sockets = new Set();
      let received = 0;
      const server = http.createServer((req, res) => {
        received++;
        sockets.add(req.socket);
        req.socket.once('close', () => sockets.delete(req.socket));
        req.resume();
        if (phase !== 'headers') {
          res.writeHead(phase === 'body' ? 200 : 503, {
            'content-type': 'application/json', 'connection': 'close',
          });
          res.write('{'); // Leave body pending until cancellation closes it.
        }
      });
      await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
      const provider = new DeepSeekSearchProvider(() => ({
        apiKey: 'local-fixture-only',
        baseURL: `http://127.0.0.1:${server.address().port}`,
        model: 'fixture', apiVersion: '2023-06-01', maxTokens: 1, maxUses: 1,
      }));
      const caller = new AbortController();
      const d = deadline(caller.signal, 300, 'TOOL_TIMEOUT');
      const batch = new AbortController();
      const signal = count === 1 ? d.signal : AbortSignal.any([d.signal, batch.signal]);
      const started = performance.now();
      let abortMs;
      signal.addEventListener('abort', () => { abortMs = performance.now() - started; }, { once: true });
      const gc = setInterval(() => globalThis.gc(), 25);
      let forcedClose = false;
      const fallback = setTimeout(() => { forcedClose = true; server.closeAllConnections(); }, 1500);
      try {
        const results = await Promise.allSettled(Array.from({ length: count }, (_, i) =>
          provider.search({ query: `fixture ${i}` }, signal).catch(error => {
            batch.abort(error);
            throw error;
          })));
        const elapsedMs = performance.now() - started;
        console.log(JSON.stringify({ phase, count, node: process.version, undici: process.versions.undici,
          abortMs, elapsedMs, forcedClose }));
        assert.equal(received, count);
        assert.equal(forcedClose, false, 'HTTP read outlived cancellation until fixture closed the connection');
        assert.ok(abortMs >= 250 && elapsedMs < 1000);
        for (const result of results) {
          assert.equal(result.status, 'rejected');
          assert.equal(result.reason.code, 'WEB_ABORTED');
        }
        // Allow the local server to observe client-side socket destruction.
        for (let i = 0; i < 10 && sockets.size; i++) await new Promise(r => setTimeout(r, 10));
        assert.equal(sockets.size, 0, 'cancelled HTTP connections must be closed');
      } finally {
        clearInterval(gc);
        clearTimeout(fallback);
        d[Symbol.dispose]();
        server.closeAllConnections();
        await new Promise(resolve => server.close(resolve));
      }
    });
  }
}
