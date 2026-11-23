import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, readFile, readdir, rm, access } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  limitedNativeCommand, performOcrFallback, runBoundedProcess, textWithPositionsFromTsv,
} from "./byq-pdf-read.js";

const scanPdf = new Uint8Array(await readFile(new URL("./byq-pdf-scan-fixture.pdf", import.meta.url)));
const hasPackagedRenderer = await access("/usr/bin/pdftoppm").then(() => true, () => false);

function word({ block, paragraph, line, x, y, text }) {
  return [5, 1, block, paragraph, line, 1, x, y, 90, 20, 95, text].join("\t");
}

test("OCR row cues align same-height words across separate PDF blocks", () => {
  const tsv = [
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
    word({ block: 1, paragraph: 1, line: 1, x: 20, y: 10, text: "项目" }),
    word({ block: 2, paragraph: 1, line: 1, x: 300, y: 12, text: "2025年" }),
    word({ block: 3, paragraph: 1, line: 1, x: 600, y: 11, text: "2024年" }),
    word({ block: 1, paragraph: 2, line: 1, x: 20, y: 80, text: "营业收入" }),
    word({ block: 2, paragraph: 2, line: 1, x: 300, y: 82, text: "10.80" }),
    word({ block: 3, paragraph: 2, line: 1, x: 600, y: 81, text: "9.50" }),
  ].join("\n");
  const rows = textWithPositionsFromTsv(tsv).split("\n");

  assert.equal(rows.length, 2);
  assert.match(rows[0], /\[x=20\]项目.*\[x=300\]2025年.*\[x=600\]2024年/);
  assert.match(rows[1], /\[x=20\]营业收入.*\[x=300\]10\.80.*\[x=600\]9\.50/);
});

test("scanned PDF fallback rasterizes within a temp directory and cleans it", {
  skip: !hasPackagedRenderer,
}, async () => {
  const tempRoot = await mkdtemp(join(tmpdir(), "byq-pdf-ocr-test-"));
  try {
    const result = await performOcrFallback(scanPdf, {
      page_count: 1,
      pages: [{ page: 1, text: "", truncated: false, has_text: false, extraction_method: "empty" }],
      text_extraction_only: true,
    }, new AbortController().signal, Date.now() + 10_000, { temporaryRoot: tempRoot });

    assert.equal(result.ocr_attempted, true);
    assert.equal(result.text_extraction_only, false);
    assert.ok(["ocr", "ocr_unavailable"].includes(result.pages[0].extraction_method));
    assert.deepEqual(await readdir(tempRoot), []);
    if (result.pages[0].extraction_method === "ocr") {
      assert.match(result.pages[0].text, /营业.*收入/);
      assert.match(result.pages[0].text, /10\.80/);
      assert.match(result.pages[0].text, /9\.50/);
      assert.match(result.pages[0].text, /row y=.*\[x=/);
    } else {
      await assert.rejects(access("/usr/bin/tesseract"), { code: "ENOENT" });
    }
  } finally {
    await rm(tempRoot, { recursive: true, force: true });
  }
});

test("native text pages do not invoke OCR", async () => {
  const result = await performOcrFallback(new Uint8Array(), {
    page_count: 1,
    pages: [{ page: 1, text: "Already extracted", truncated: false, has_text: true, extraction_method: "native_text" }],
    text_extraction_only: true,
  }, new AbortController().signal, Date.now() + 1_000);

  assert.equal(result.ocr_attempted, false);
  assert.equal(result.text_extraction_only, true);
  assert.equal(result.pages[0].extraction_method, "native_text");
});

test("aborting a bounded OCR subprocess kills its child process group", { timeout: 3_000 }, async () => {
  const controller = new AbortController();
  let descendantPid;
  const script = "/bin/sleep 20 & printf '%s\\n' \"$!\"; wait";
  const [command, args] = limitedNativeCommand("/bin/sh", ["-c", script]);
  const result = runBoundedProcess(command, args, {
    signal: controller.signal,
    deadlineAt: Date.now() + 2_000,
    maxMs: 2_000,
    onStdoutChunk(chunk) {
      descendantPid = Number(chunk.toString("utf8").trim());
      if (descendantPid > 0) setImmediate(() => controller.abort());
    },
  });

  await assert.rejects(result, error => error.code === "PDF_ABORTED");
  assert.ok(descendantPid > 0);
  if (process.platform !== "win32") {
    await new Promise(resolve => setTimeout(resolve, 50));
    try {
      process.kill(descendantPid, 0);
      const status = await readFile(`/proc/${descendantPid}/stat`, "utf8");
      assert.equal(status.slice(status.lastIndexOf(")") + 2, status.lastIndexOf(")") + 3), "Z");
    } catch (error) {
      assert.equal(error.code, "ESRCH");
    }
  }
});
