import { createRequire } from "node:module";
import { isAbsolute, join } from "node:path";
import { pathToFileURL } from "node:url";
import { parentPort, workerData } from "node:worker_threads";

const DEFAULT_RUNTIME_ROOT = "/opt/dsh-runtime";
const MAX_REQUESTED_PAGES = 5;
const MAX_DOCUMENT_PAGES = 2000;
const MAX_PAGE_TEXT_LENGTH = 12000;
const SAFE_ERROR_CODES = new Set([
  "invalid_input",
  "runtime_unavailable",
  "invalid_pdf",
  "document_page_limit",
  "page_out_of_range",
  "extract_failed",
]);

function safeError(code) {
  const error = new Error(code);
  error.code = code;
  return error;
}

function validateRequest(bytes, pages) {
  if (!(bytes instanceof Uint8Array) || bytes.byteLength === 0) {
    throw safeError("invalid_input");
  }
  if (!Array.isArray(pages) || pages.length === 0 || pages.length > MAX_REQUESTED_PAGES) {
    throw safeError("invalid_input");
  }
  if (pages.some((page) => !Number.isInteger(page) || page < 1 || page > MAX_DOCUMENT_PAGES)) {
    throw safeError("invalid_input");
  }
}

async function loadPdfJs(runtimeRoot) {
  const root = runtimeRoot || DEFAULT_RUNTIME_ROOT;
  if (typeof root !== "string" || !isAbsolute(root)) {
    throw safeError("runtime_unavailable");
  }

  try {
    const previewPackage = join(root, "packages/client/ui-sidebar-documentpreview/package.json");
    const requireFromRuntime = createRequire(previewPackage);
    const pdfJsPath = requireFromRuntime.resolve("pdfjs-dist/legacy/build/pdf.mjs");
    const pdfJs = await import(pathToFileURL(pdfJsPath).href);
    if (typeof pdfJs.getDocument !== "function") throw safeError("runtime_unavailable");
    return pdfJs;
  } catch (error) {
    if (SAFE_ERROR_CODES.has(error?.code)) throw error;
    throw safeError("runtime_unavailable");
  }
}

function appendCapped(current, value) {
  if (typeof value !== "string" || value.length === 0) return current;
  const remaining = MAX_PAGE_TEXT_LENGTH + 1 - current.length;
  if (remaining <= 0) return current;
  return current + value.slice(0, remaining);
}

function textFromContent(content) {
  let text = "";
  for (const item of content.items ?? []) {
    if (typeof item?.str === "string") text = appendCapped(text, item.str);
    if (item?.hasEOL) text = appendCapped(text, "\n");
    if (text.length > MAX_PAGE_TEXT_LENGTH) break;
  }

  const truncated = text.length > MAX_PAGE_TEXT_LENGTH;
  text = text.slice(0, MAX_PAGE_TEXT_LENGTH);
  // Avoid returning an unpaired high surrogate if the limit bisects a pair.
  if (text.length > 0 && /[\uD800-\uDBFF]$/.test(text)) text = text.slice(0, -1);
  text = text.replace(/\r\n?/g, "\n").trim();
  return { text, truncated, has_text: text.length > 0 };
}

async function ignoreCleanup(action) {
  try {
    await action?.();
  } catch {
    // Cleanup failures must not hide a completed extraction or its original error.
  }
}

export async function extractPdfText(bytes, pages, { runtimeRoot = process.env.BYQ_DSH_RUNTIME_ROOT } = {}) {
  validateRequest(bytes, pages);

  const copiedBytes = new Uint8Array(bytes);
  let loadingTask;
  let pdf;
  let stage = "runtime";

  try {
    const { getDocument } = await loadPdfJs(runtimeRoot);
    stage = "document";
    loadingTask = getDocument({
      data: copiedBytes,
      useSystemFonts: false,
      disableFontFace: true,
      useWorkerFetch: false,
      isEvalSupported: false,
      enableXfa: false,
      verbosity: 0,
      stopAtErrors: false,
      disableAutoFetch: true,
      disableStream: true,
      useWasm: false,
    });
    pdf = await loadingTask.promise;

    if (!Number.isInteger(pdf.numPages) || pdf.numPages < 1) throw safeError("invalid_pdf");
    if (pdf.numPages > MAX_DOCUMENT_PAGES) throw safeError("document_page_limit");
    if (pages.some((page) => page > pdf.numPages)) throw safeError("page_out_of_range");

    stage = "extract";
    const extractedPages = [];
    for (const pageNumber of pages) {
      const page = await pdf.getPage(pageNumber);
      try {
        const content = await page.getTextContent({ includeMarkedContent: false });
        extractedPages.push({ page: pageNumber, ...textFromContent(content) });
      } finally {
        await ignoreCleanup(() => page.cleanup?.());
      }
    }

    return {
      page_count: pdf.numPages,
      pages: extractedPages,
      text_extraction_only: true,
    };
  } catch (error) {
    if (SAFE_ERROR_CODES.has(error?.code)) throw error;
    throw safeError(stage === "runtime" ? "runtime_unavailable" : stage === "document" ? "invalid_pdf" : "extract_failed");
  } finally {
    await ignoreCleanup(() => pdf?.cleanup?.());
    await ignoreCleanup(() => pdf?.destroy?.());
    await ignoreCleanup(() => loadingTask?.destroy?.());
  }
}

if (parentPort !== null && workerData?.kind === "byq-pdf-extract") {
  try {
    const result = await extractPdfText(workerData.bytes, workerData.pages, { runtimeRoot: workerData.runtimeRoot });
    parentPort.postMessage({ ok: true, result });
  } catch (error) {
    const code = SAFE_ERROR_CODES.has(error?.code) ? error.code : "extract_failed";
    parentPort.postMessage({ ok: false, error: code });
  } finally {
    parentPort.close();
  }
}
