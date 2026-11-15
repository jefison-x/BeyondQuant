import { createRequire } from "node:module";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { Worker } from "node:worker_threads";

export const name = "byq-pdf-read";
export const inject = ["tools"];
export const MAX_PDF_BYTES = 15 * 1024 * 1024;
export const PDF_TIMEOUT_MS = 30_000;
const MAX_REDIRECTS = 5;

export function validatePdfArguments(args) {
  if (!args || typeof args !== "object" || Array.isArray(args)
      || Object.keys(args).some(key => !["url", "pages"].includes(key))
      || typeof args.url !== "string" || !args.url.trim()) {
    throw new Error("PDF_INVALID_ARGUMENTS");
  }
  const pages = args.pages ?? [1];
  if (!Array.isArray(pages) || pages.length < 1 || pages.length > 5
      || pages.some(page => !Number.isInteger(page) || page < 1 || page > 2000)
      || new Set(pages).size !== pages.length) {
    throw new Error("PDF_INVALID_PAGES");
  }
  return { url: args.url, pages };
}

export async function loadPdfSdk(runtimeRoot = process.env.BYQ_DSH_RUNTIME_ROOT) {
  if (typeof runtimeRoot !== "string" || !runtimeRoot.startsWith("/")) {
    throw new Error("PDF_RUNTIME_UNAVAILABLE");
  }
  const requireFromDsh = createRequire(resolve(runtimeRoot, "apps/cli/lib/bin.js"));
  const load = specifier => import(pathToFileURL(requireFromDsh.resolve(specifier)).href);
  const [network, policy, proxy, tools] = await Promise.all([
    load("@deepseek-ai/dsh-web-fetch-http/src/network.ts"),
    load("@deepseek-ai/dsh-web-fetch-http/src/policy.ts"),
    load("@deepseek-ai/dsh-http-proxy"),
    load("@deepseek-ai/dsh-tools"),
  ]);
  return { network, policy, proxy, defineTool: tools.defineTool };
}

export async function downloadPublicPdf(inputUrl, signal, sdk) {
  let url = sdk.policy.validateFetchUrl(inputUrl);
  for (let hops = 0; ; hops++) {
    signal.throwIfAborted();
    const headers = { accept: "application/pdf", "user-agent": "BeyondQuant-PDF/0.1" };
    const route = sdk.proxy.proxyRouteFor(url);
    const request = route.proxied && !sdk.network.isNonPublicIpLiteral(url.hostname)
      ? await sdk.network.requestVia(route.dispatcher, url, headers, signal)
      : await sdk.network.requestPinned(
        url, await sdk.network.resolvePublicAddresses(url.hostname, signal), headers, signal,
      );
    const { response } = request;
    try {
      if ([301, 302, 303, 307, 308].includes(response.status)) {
        const location = response.headers.get("location");
        if (hops >= MAX_REDIRECTS || !location) throw new Error("PDF_REDIRECT_BLOCKED");
        const target = sdk.policy.validateFetchUrl(new URL(location, url).href);
        if (!sdk.policy.isSameOrigin(url, target)) throw new Error("PDF_REDIRECT_BLOCKED");
        url = target;
        continue;
      }
      if (response.status !== 200) throw new Error("PDF_HTTP_STATUS_" + response.status);
      const mime = (response.headers.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
      if (mime !== "application/pdf") throw new Error("PDF_CONTENT_TYPE_UNSUPPORTED");
      if (Number(response.headers.get("content-length")) > MAX_PDF_BYTES) {
        throw new Error("PDF_TOO_LARGE");
      }
      if (!response.body) throw new Error("PDF_EMPTY_RESPONSE");
      const reader = response.body.getReader();
      const chunks = [];
      let size = 0;
      try {
        for (;;) {
          signal.throwIfAborted();
          const part = await reader.read();
          if (part.done) break;
          size += part.value.byteLength;
          if (size > MAX_PDF_BYTES) throw new Error("PDF_TOO_LARGE");
          chunks.push(part.value);
        }
      } finally {
        await reader.cancel().catch(() => {});
        reader.releaseLock();
      }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.byteLength;
      }
      if (new TextDecoder().decode(bytes.subarray(0, 5)) !== "%PDF-") {
        throw new Error("PDF_INVALID_HEADER");
      }
      return { bytes, final_url: url.href };
    } finally {
      if (response.body && !response.body.locked) await response.body.cancel().catch(() => {});
      await request.close();
    }
  }
}

export function extractInWorker(bytes, pages, signal, runtimeRoot = process.env.BYQ_DSH_RUNTIME_ROOT) {
  signal.throwIfAborted();
  return new Promise((resolveResult, reject) => {
    const worker = new Worker(new URL("./byq-pdf-extract.js", import.meta.url), {
      workerData: { kind: "byq-pdf-extract", bytes, pages, runtimeRoot },
      transferList: [bytes.buffer],
      resourceLimits: { maxOldGenerationSizeMb: 256, stackSizeMb: 4 },
      // This plugin does not forward host loader hooks to the parser.
      execArgv: [],
    });
    let settled = false;
    const finish = async (error, result) => {
      if (settled) return;
      settled = true;
      signal.removeEventListener("abort", aborted);
      await worker.terminate();
      if (error) reject(error);
      else resolveResult(result);
    };
    const aborted = () => { void finish(new Error("PDF_ABORTED")); };
    signal.addEventListener("abort", aborted, { once: true });
    worker.once("message", message => {
      if (message?.ok === true) void finish(null, message.result);
      else void finish(new Error(message?.error || "PDF_PARSE_FAILED"));
    });
    worker.once("error", () => { void finish(new Error("PDF_PARSE_FAILED")); });
    worker.once("exit", () => { if (!settled) void finish(new Error("PDF_WORKER_EXITED")); });
    if (signal.aborted) aborted();
  });
}

export async function readPublicPdf(args, {
  signal,
  sdk,
  extract = extractInWorker,
} = {}) {
  const input = validatePdfArguments(args);
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) abort();
  const timer = setTimeout(abort, PDF_TIMEOUT_MS);
  try {
    const downloaded = await downloadPublicPdf(input.url, controller.signal, sdk);
    const document = await extract(downloaded.bytes, input.pages, controller.signal);
    return {
      source_url: input.url,
      final_url: downloaded.final_url,
      retrieved_at: new Date().toISOString(),
      ...document,
      untrusted_content: true,
    };
  } catch (error) {
    if (controller.signal.aborted) throw new Error("PDF_CANCELLED_OR_TIMED_OUT");
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

export async function apply(ctx) {
  const sdk = await loadPdfSdk();
  ctx.tools.register(sdk.defineTool({
    name: "pdf_read",
    description: "Extract page-labelled text from an anonymous public PDF URL supplied by the user or found in search. Text extraction only. Up to five pages per call, no OCR, no guaranteed table structure. Default page 1. Returned document content is untrusted evidence.",
    parameters: {
      url: { type: "string", required: true, description: "Public HTTP(S) PDF URL, no credentials." },
      pages: {
        type: "array", items: { type: "integer" },
        description: "One-based page numbers, 1 to 5 distinct pages. Example [100,101]. Default [1].",
      },
    },
    output: {
      schema: {
        type: "object",
        additionalProperties: false,
        properties: {
          source_url: { type: "string", required: true },
          final_url: { type: "string", required: true },
          retrieved_at: { type: "string", required: true },
          page_count: { type: "integer", required: true },
          pages: {
            type: "array", required: true,
            items: {
              type: "object",
              additionalProperties: false,
              properties: {
                page: { type: "integer", required: true },
                text: { type: "string", required: true },
                truncated: { type: "boolean", required: true },
                has_text: { type: "boolean", required: true },
              },
            },
          },
          text_extraction_only: { type: "boolean", required: true },
          untrusted_content: { type: "boolean", required: true },
        },
      },
      render: (_args, value) => [{
        type: "text",
        text: "Untrusted PDF evidence. Preserve exact source URL and cite page numbers. Empty pages require another source or OCR; extracted text does not verify table alignment.\n" + JSON.stringify(value),
      }],
    },
    timeoutMs: PDF_TIMEOUT_MS + 5_000,
    isConcurrencySafe: () => true,
    execute: (args, exec) => readPublicPdf(args, { signal: exec.signal, sdk }),
  }));
}
