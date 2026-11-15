import assert from "node:assert/strict";
import test from "node:test";
import { createServer } from "node:http";
import {
  apply, downloadPublicPdf, loadPdfSdk, MAX_PDF_BYTES, readPublicPdf,
  extractInWorker, validatePdfArguments,
} from "./byq-pdf-read.js";

const sdk = await loadPdfSdk();
const bytes = new TextEncoder().encode("%PDF-1.7\nfixture");
function transport(responses) {
  const calls = [];
  const closed = [];
  const custom = {
    ...sdk,
    proxy: { proxyRouteFor: () => ({ proxied: false }) },
    network: {
      ...sdk.network,
      async resolvePublicAddresses(host) {
        calls.push({ host });
        return [{ address: "8.8.8.8", family: 4 }];
      },
      async requestPinned(url, addresses, headers, signal) {
        calls.push({ url: url.href, addresses, headers, signal });
        return { response: responses.shift(), close: async () => { closed.push(url.href); } };
      },
    },
  };
  return { sdk: custom, calls, closed };
}
const pdf = () => new Response(bytes, { headers: { "content-type": "application/pdf" } });

test("validates bounded one-based page arguments", () => {
  assert.deepEqual(validatePdfArguments({ url: "https://example.com/a.pdf" }).pages, [1]);
  for (const pages of [[], [0], [1, 1], [1.5], [2001], [1, 2, 3, 4, 5, 6]]) {
    assert.throws(() => validatePdfArguments({ url: "https://example.com/a.pdf", pages }));
  }
  assert.throws(() => validatePdfArguments({ url: "https://example.com/a.pdf", headers: {} }));
});

test("preserves URL and uses public resolution for every same-origin redirect", async () => {
  const t = transport([
    new Response(null, { status: 302, headers: { location: "/final.pdf?x=1#page=2" } }),
    pdf(),
  ]);
  const result = await downloadPublicPdf("https://example.com/a.pdf?x=1#page=2", new AbortController().signal, t.sdk);
  assert.equal(result.final_url, "https://example.com/final.pdf?x=1#page=2");
  assert.deepEqual([...result.bytes], [...bytes]);
  assert.equal(t.calls.filter(x => x.host).length, 2);
  assert.equal(t.closed.length, 2);
  assert.ok(t.calls.filter(x => x.url).every(x => x.addresses[0].address === "8.8.8.8"));
  assert.ok(t.calls.filter(x => x.url).every(x => !("authorization" in x.headers) && !("cookie" in x.headers)));
});

test("rejects credentials, non-HTTP protocols and cross-origin redirects before connecting", async () => {
  for (const url of ["file:///tmp/a.pdf", "https://user:secret@example.com/a.pdf"]) {
    const t = transport([pdf()]);
    await assert.rejects(downloadPublicPdf(url, new AbortController().signal, t.sdk));
    assert.equal(t.calls.length, 0);
  }
  const t = transport([new Response(null, { status: 302, headers: { location: "http://127.0.0.1/a.pdf" } })]);
  await assert.rejects(downloadPublicPdf("https://example.com/a.pdf", new AbortController().signal, t.sdk), /REDIRECT_BLOCKED/);
  assert.equal(t.closed.length, 1);
  assert.equal(t.calls.filter(x => x.host).length, 1);
});

test("DSH's real public-address guard blocks literal and DNS-resolved private addresses", async () => {
  for (const host of ["127.0.0.1", "169.254.169.254", "::1"]) {
    await assert.rejects(sdk.network.resolvePublicAddresses(host, new AbortController().signal, async () => []));
  }
  const t = transport([pdf()]);
  t.sdk.network.resolvePublicAddresses = (host, signal) => sdk.network.resolvePublicAddresses(
    host, signal, async () => [{ address: "127.0.0.1", family: 4 }],
  );
  await assert.rejects(downloadPublicPdf("https://example.com/a.pdf", new AbortController().signal, t.sdk));
  assert.equal(t.calls.filter(x => x.url).length, 0);
});

test("rejects excessive headers, excessive streamed bytes, HTML and invalid PDF headers", async () => {
  const cases = [
    new Response(bytes, { headers: { "content-type": "application/pdf", "content-length": String(MAX_PDF_BYTES + 1) } }),
    new Response(new Uint8Array(MAX_PDF_BYTES + 1), { headers: { "content-type": "application/pdf" } }),
    new Response("not a PDF", { headers: { "content-type": "text/html" } }),
    new Response("not a PDF", { headers: { "content-type": "application/pdf" } }),
  ];
  for (const response of cases) {
    const t = transport([response]);
    await assert.rejects(downloadPublicPdf("https://example.com/a.pdf", new AbortController().signal, t.sdk));
    assert.equal(t.closed.length, 1);
  }
});

test("bounds redirect loops and releases every response", async () => {
  const responses = Array.from({ length: 6 }, () => new Response(null, {
    status: 302, headers: { location: "/loop.pdf" },
  }));
  const t = transport(responses);
  await assert.rejects(downloadPublicPdf("https://example.com/a.pdf", new AbortController().signal, t.sdk), /REDIRECT_BLOCKED/);
  assert.equal(t.closed.length, 6);
});

test("read result marks external content and preserves the exact original source", async () => {
  const url = "https://example.com/a.pdf?token=public#page=2";
  const t = transport([pdf()]);
  const result = await readPublicPdf({ url, pages: [2] }, {
    sdk: t.sdk,
    extract: async (_bytes, pages) => ({
      page_count: 2, pages: pages.map(page => ({ page, text: "Evidence", truncated: false, has_text: true })),
      text_extraction_only: true,
    }),
  });
  assert.equal(result.source_url, url);
  assert.equal(result.untrusted_content, true);
  assert.equal(result.pages[0].page, 2);
});

test("already cancelled requests perform no network operation", async () => {
  const t = transport([pdf()]);
  const signal = AbortSignal.abort();
  await assert.rejects(readPublicPdf({ url: "https://example.com/a.pdf" }, { signal, sdk: t.sdk }), /CANCELLED_OR_TIMED_OUT/);
  assert.equal(t.calls.length, 0);
});

test("cancellation terminates parser Worker startup", async () => {
  const controller = new AbortController();
  const started = Date.now();
  const result = extractInWorker(new Uint8Array(bytes), [1], controller.signal);
  controller.abort();
  await assert.rejects(result, /PDF_ABORTED/);
  assert.ok(Date.now() - started < 2000);
});

test("registers with the actual DSH schema compiler", async () => {
  let registered;
  await apply({ tools: { register(value) { registered = value; } } });
  assert.equal(registered.name, "pdf_read");
  assert.equal(registered.timeoutMs, 35000);
  assert.equal(typeof registered.execute, "function");
});

test("the real Node24 HTTP stream closes when the complete tool deadline expires", { timeout: 36_000 }, async t => {
  let responseClosed = false;
  let received = false;
  const server = createServer((_request, response) => {
    received = true;
    response.writeHead(200, { "content-type": "application/pdf" });
    response.write("%PDF-1.7\n");
    const interval = setInterval(() => response.write("slow stream\n"), 100);
    response.on("close", () => { responseClosed = true; clearInterval(interval); });
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  t.after(async () => {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  });
  const fixtureSdk = {
    ...sdk,
    proxy: { proxyRouteFor: () => ({ proxied: false }) },
    network: {
      ...sdk.network,
      // Test-only pin to the fixture. Production always uses DSH public DNS.
      resolvePublicAddresses: async () => [{ address: "127.0.0.1", family: 4 }],
    },
  };
  const started = Date.now();
  await assert.rejects(readPublicPdf({
    url: "http://fixture.invalid:" + server.address().port + "/slow.pdf",
  }, { sdk: fixtureSdk }), /PDF_CANCELLED_OR_TIMED_OUT/);
  const elapsed = Date.now() - started;
  assert.equal(received, true);
  await new Promise(resolve => setTimeout(resolve, 50));
  assert.equal(responseClosed, true);
  assert.ok(elapsed >= 29_500 && elapsed < 33_000, "deadline elapsed " + elapsed);
});
