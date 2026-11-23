import { createRequire } from "node:module";
import { mkdtemp, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { spawn } from "node:child_process";
import { Worker } from "node:worker_threads";

export const name = "byq-pdf-read";
export const inject = ["tools"];
export const MAX_PDF_BYTES = 15 * 1024 * 1024;
export const PDF_TIMEOUT_MS = 30_000;
export const MAX_OCR_RENDER_DIMENSION = 1_600;
export const MAX_OCR_IMAGE_BYTES = 8 * 1024 * 1024;
export const MAX_OCR_PROCESS_MEMORY_BYTES = 512 * 1024 * 1024;
const MAX_REDIRECTS = 5;
const MAX_OCR_PROCESS_MS = 5_000;
const MAX_OCR_STDOUT_BYTES = 1024 * 1024;
const MAX_OCR_TEXT_LENGTH = 12_000;
const OCR_LANGUAGES = "chi_sim+eng";

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
      // Keep the downloaded bytes in the parent so only empty selected pages
      // can be rendered for OCR after the PDF.js worker has finished.
      workerData: { kind: "byq-pdf-extract", bytes: new Uint8Array(bytes), pages, runtimeRoot },
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

function signalProcessGroup(pid, signal) {
  if (!Number.isInteger(pid) || pid < 1) return;
  try {
    process.kill(process.platform === "win32" ? pid : -pid, signal);
  } catch (error) {
    if (error?.code !== "ESRCH") throw error;
  }
}

export function runBoundedProcess(command, args, {
  signal,
  deadlineAt,
  maxMs = MAX_OCR_PROCESS_MS,
  maxStdoutBytes = MAX_OCR_STDOUT_BYTES,
  onStdoutChunk,
} = {}) {
  signal?.throwIfAborted();
  const remaining = Number.isFinite(deadlineAt) ? deadlineAt - Date.now() : maxMs;
  const timeoutMs = Math.min(maxMs, remaining);
  if (timeoutMs <= 0) return Promise.reject(Object.assign(new Error("OCR_TIMEOUT"), { code: "OCR_TIMEOUT" }));

  return new Promise((resolveResult, reject) => {
    const child = spawn(command, args, {
      shell: false,
      detached: process.platform !== "win32",
      stdio: ["ignore", "pipe", "ignore"],
      env: { PATH: process.env.PATH || "/usr/bin:/bin", LANG: "C.UTF-8" },
    });
    let reason;
    let spawnError;
    let outputTooLarge = false;
    let stdoutSize = 0;
    const stdout = [];
    let killTimer;
    const timeout = setTimeout(() => terminate("OCR_TIMEOUT"), timeoutMs);

    const aborted = () => terminate("PDF_ABORTED");
    signal?.addEventListener("abort", aborted, { once: true });

    function terminate(code) {
      if (reason) return;
      reason = code;
      signalProcessGroup(child.pid, "SIGTERM");
      killTimer = setTimeout(() => signalProcessGroup(child.pid, "SIGKILL"), 200);
    }

    child.stdout.on("data", chunk => {
      stdoutSize += chunk.byteLength;
      if (stdoutSize > maxStdoutBytes) {
        outputTooLarge = true;
        terminate("OCR_OUTPUT_LIMIT");
        return;
      }
      stdout.push(chunk);
      try {
        onStdoutChunk?.(chunk);
      } catch {
        terminate("OCR_OUTPUT_CALLBACK_FAILED");
      }
    });
    child.once("exit", () => signalProcessGroup(child.pid, "SIGKILL"));
    child.once("error", error => {
      spawnError = error;
      if (error?.code === "ENOENT") terminate("OCR_UNAVAILABLE");
      else terminate("OCR_COMMAND_FAILED");
    });
    child.once("close", (exitCode, childSignal) => {
      clearTimeout(timeout);
      clearTimeout(killTimer);
      signal?.removeEventListener("abort", aborted);
      signalProcessGroup(child.pid, "SIGKILL");
      if (reason) {
        const error = new Error(reason);
        error.code = reason;
        reject(error);
      } else if (spawnError) {
        const error = new Error(spawnError.code === "ENOENT" ? "OCR_UNAVAILABLE" : "OCR_COMMAND_FAILED");
        error.code = spawnError.code === "ENOENT" ? "OCR_UNAVAILABLE" : "OCR_COMMAND_FAILED";
        reject(error);
      } else if (outputTooLarge) {
        const error = new Error("OCR_OUTPUT_LIMIT");
        error.code = "OCR_OUTPUT_LIMIT";
        reject(error);
      } else if (exitCode !== 0 || childSignal) {
        const error = new Error("OCR_COMMAND_FAILED");
        error.code = "OCR_COMMAND_FAILED";
        reject(error);
      } else {
        resolveResult(Buffer.concat(stdout, stdoutSize));
      }
    });
    if (signal?.aborted) aborted();
  });
}

export function limitedNativeCommand(command, args) {
  if (process.platform !== "linux") return [command, args];
  const binary = command.startsWith("/") ? command : `/usr/bin/${command}`;
  return ["/usr/bin/prlimit", [
    `--as=${MAX_OCR_PROCESS_MEMORY_BYTES}`,
    `--fsize=${MAX_OCR_IMAGE_BYTES}`,
    "--", binary, ...args,
  ]];
}

export function textWithPositionsFromTsv(tsv) {
  const tokens = [];
  for (const sourceLine of tsv.toString("utf8").split(/\r?\n/).slice(1)) {
    const fields = sourceLine.split("\t");
    if (fields.length < 12 || fields[0] !== "5" || !fields[11]?.trim()) continue;
    const token = {
      x: Number(fields[6]),
      y: Number(fields[7]),
      height: Number(fields[9]),
      text: fields.slice(11).join("\t").trim(),
    };
    if (!Number.isFinite(token.x) || !Number.isFinite(token.y) || !Number.isFinite(token.height)) continue;
    tokens.push(token);
  }

  const rows = [];
  for (const token of tokens.sort((left, right) => left.y - right.y || left.x - right.x)) {
    const row = rows.at(-1);
    const tolerance = row ? Math.max(4, Math.min(row.height, token.height) * 0.45) : 0;
    if (!row || token.y - row.y > tolerance) {
      rows.push({ y: token.y, height: token.height, tokens: [token] });
    } else {
      row.height = Math.max(row.height, token.height);
      row.tokens.push(token);
    }
  }

  return rows
    .sort((left, right) => left.y - right.y)
    .map(row => `row y=${row.y}: ${row.tokens.sort((left, right) => left.x - right.x)
      .map(token => `[x=${token.x}]${token.text}`).join("  ")}`)
    .join("\n");
}

export async function performOcrFallback(bytes, document, signal, deadlineAt, { temporaryRoot = tmpdir() } = {}) {
  const pagesToRecognize = document.pages.filter(page => !page.has_text);
  if (pagesToRecognize.length === 0) {
    return { ...document, ocr_attempted: false, text_extraction_only: true };
  }

  const extractedByPage = new Map(document.pages.map(page => [page.page, { ...page }]));
  for (const page of pagesToRecognize) extractedByPage.get(page.page).extraction_method = "ocr_failed";
  let directory;
  let tempPdf;
  try {
    directory = await mkdtemp(join(temporaryRoot, "byq-pdf-ocr-"));
    tempPdf = join(directory, "source.pdf");
    await writeFile(tempPdf, bytes, { flag: "wx", mode: 0o600, signal });
    for (let index = 0; index < pagesToRecognize.length; index += 1) {
      const page = pagesToRecognize[index];
      signal.throwIfAborted();
      const remainingPages = pagesToRecognize.length - index;
      if (deadlineAt - Date.now() < remainingPages * 500) {
        for (const skipped of pagesToRecognize.slice(index)) {
          extractedByPage.get(skipped.page).extraction_method = "ocr_timeout";
        }
        break;
      }
      const outputPrefix = join(directory, `page-${page.page}`);
      const maxCommandMs = stepsRemaining => Math.max(1, Math.min(
        MAX_OCR_PROCESS_MS,
        Math.floor((deadlineAt - Date.now()) / stepsRemaining),
      ));
      try {
        const [renderer, renderArgs] = limitedNativeCommand("pdftoppm", [
          "-f", String(page.page), "-l", String(page.page), "-singlefile",
          "-scale-to", String(MAX_OCR_RENDER_DIMENSION), tempPdf, outputPrefix,
        ]);
        await runBoundedProcess(renderer, renderArgs, {
          signal, deadlineAt, maxMs: maxCommandMs(remainingPages * 2), maxStdoutBytes: 32 * 1024,
        });
        const imagePath = outputPrefix + ".ppm";
        const imageInfo = await stat(imagePath);
        if (!imageInfo.isFile() || imageInfo.size > MAX_OCR_IMAGE_BYTES) {
          const error = new Error("OCR_IMAGE_LIMIT");
          error.code = "OCR_IMAGE_LIMIT";
          throw error;
        }
        const [recognizer, recognizeArgs] = limitedNativeCommand("tesseract", [
          imagePath, "stdout", "-l", OCR_LANGUAGES, "--psm", "3", "tsv",
        ]);
        const tsv = await runBoundedProcess(recognizer, recognizeArgs, {
          signal, deadlineAt, maxMs: maxCommandMs(remainingPages * 2 - 1),
        });
        const text = textWithPositionsFromTsv(tsv);
        const isTruncated = text.length > MAX_OCR_TEXT_LENGTH;
        const recognized = text.slice(0, MAX_OCR_TEXT_LENGTH).replace(/[\uD800-\uDBFF]$/, "").trim();
        extractedByPage.set(page.page, {
          ...page,
          text: recognized,
          truncated: isTruncated,
          has_text: recognized.length > 0,
          extraction_method: recognized.length > 0 ? "ocr" : "ocr_empty",
        });
      } catch (error) {
        if (signal.aborted || error?.code === "PDF_ABORTED") throw error;
        const method = error?.code === "OCR_TIMEOUT" ? "ocr_timeout"
          : error?.code === "OCR_UNAVAILABLE" ? "ocr_unavailable" : "ocr_failed";
        extractedByPage.get(page.page).extraction_method = method;
        if (method === "ocr_unavailable") {
          for (const skipped of pagesToRecognize.slice(index + 1)) {
            extractedByPage.get(skipped.page).extraction_method = "ocr_unavailable";
          }
          break;
        }
      }
    }
  } catch (error) {
    if (signal.aborted || error?.name === "AbortError") throw error;
    const method = error?.code === "OCR_TIMEOUT" ? "ocr_timeout"
      : error?.code === "OCR_UNAVAILABLE" || error?.code === "EACCES" ? "ocr_unavailable" : "ocr_failed";
    for (const page of pagesToRecognize) {
      if (extractedByPage.get(page.page).extraction_method === "ocr_failed") {
        extractedByPage.get(page.page).extraction_method = method;
      }
    }
  } finally {
    if (directory) await rm(directory, { recursive: true, force: true }).catch(() => {});
  }

  return {
    ...document,
    pages: document.pages.map(page => extractedByPage.get(page.page)),
    ocr_attempted: true,
    text_extraction_only: false,
  };
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
  const deadlineAt = Date.now() + PDF_TIMEOUT_MS;
  try {
    const downloaded = await downloadPublicPdf(input.url, controller.signal, sdk);
    const parsed = await extract(downloaded.bytes, input.pages, controller.signal);
    const document = await performOcrFallback(downloaded.bytes, parsed, controller.signal, deadlineAt);
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
    description: "Extract page-labelled text from an anonymous public PDF URL supplied by the user or found in search. Empty selected pages receive bounded OCR fallback. OCR includes approximate reading-row and horizontal-position cues; table columns and merged cells are not guaranteed. Up to five pages per call. Default page 1. Returned document content is untrusted evidence.",
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
                extraction_method: { type: "string", required: true, description: "native_text, ocr, ocr_empty, ocr_unavailable, ocr_timeout, or ocr_failed." },
              },
            },
          },
          text_extraction_only: { type: "boolean", required: true },
          ocr_attempted: { type: "boolean", required: true },
          untrusted_content: { type: "boolean", required: true },
        },
      },
      render: (_args, value) => [{
        type: "text",
        text: "Untrusted PDF evidence. Preserve exact source URL and cite page numbers. Absence claims apply only to the pages returned, never unread pages. Check each page's extraction_method. OCR text and row/x-position cues are approximate. Verify any table values against the source page; columns and merged cells are not reconstructed. Empty or failed OCR does not show that a disclosure is absent.\n" + JSON.stringify(value),
      }],
    },
    timeoutMs: PDF_TIMEOUT_MS + 5_000,
    isConcurrencySafe: () => true,
    execute: (args, exec) => readPublicPdf(args, { signal: exec.signal, sdk }),
  }));
}
