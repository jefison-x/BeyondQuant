import assert from "node:assert/strict";
import test from "node:test";

import { extractPdfText } from "./byq-pdf-extract.js";

function escapePdfText(text) {
  return text.replaceAll("\\", "\\\\").replaceAll("(", "\\(").replaceAll(")", "\\)");
}

function makePdf(pageTexts, { pageWidth = 300 } = {}) {
  const pageCount = pageTexts.length;
  const fontObject = 3 + pageCount * 2;
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    `<< /Type /Pages /Kids [${pageTexts.map((_, index) => `${3 + index * 2} 0 R`).join(" ")}] /Count ${pageCount} >>`,
  ];

  for (let index = 0; index < pageCount; index += 1) {
    const pageObject = 3 + index * 2;
    const contentObject = pageObject + 1;
    const text = pageTexts[index];
    const stream = text === null ? "q Q" : `BT /F1 12 Tf 10 100 Td (${escapePdfText(text)}) Tj ET`;
    objects.push(
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageWidth} 144] /Resources << /Font << /F1 ${fontObject} 0 R >> >> /Contents ${contentObject} 0 R >>`,
      `<< /Length ${Buffer.byteLength(stream, "latin1")} >>\nstream\n${stream}\nendstream`,
    );
  }
  objects.push("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");

  let source = "%PDF-1.4\n";
  const offsets = [0];
  for (let index = 0; index < objects.length; index += 1) {
    offsets.push(Buffer.byteLength(source, "latin1"));
    source += `${index + 1} 0 obj\n${objects[index]}\nendobj\n`;
  }
  const xrefOffset = Buffer.byteLength(source, "latin1");
  source += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const offset of offsets.slice(1)) source += `${String(offset).padStart(10, "0")} 00000 n \n`;
  source += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`;
  return new Uint8Array(Buffer.from(source, "latin1"));
}

const runtimeRoot = process.env.BYQ_DSH_RUNTIME_ROOT || "/opt/dsh-runtime";

test("extracts selected 1-based pages and returns plain text-only metadata", async () => {
  const result = await extractPdfText(makePdf(["First page", "Second page"]), [2], { runtimeRoot });

  assert.equal(result.page_count, 2);
  assert.deepEqual(result.pages, [{ page: 2, text: "Second page", truncated: false, has_text: true }]);
  assert.equal(result.text_extraction_only, true);
});

test("reports an empty page explicitly", async () => {
  const result = await extractPdfText(makePdf([null]), [1], { runtimeRoot });

  assert.deepEqual(result.pages, [{ page: 1, text: "", truncated: false, has_text: false }]);
});

test("caps each page at 12000 characters and marks truncation", async () => {
  // Keep the long text inside the real page bounds so PDF.js does not crop it.
  const result = await extractPdfText(makePdf(["x".repeat(12020)], { pageWidth: 100000 }), [1], { runtimeRoot });

  assert.equal(result.pages[0].text.length, 12000);
  assert.equal(result.pages[0].truncated, true);
  assert.equal(result.pages[0].has_text, true);
});

test("validates requested page count, page numbers, and document range", async () => {
  const pdf = makePdf(["Only page"]);
  await assert.rejects(extractPdfText(pdf, []), { code: "invalid_input" });
  await assert.rejects(extractPdfText(pdf, [1, 2, 3, 4, 5, 6]), { code: "invalid_input" });
  await assert.rejects(extractPdfText(pdf, [0]), { code: "invalid_input" });
  await assert.rejects(extractPdfText(pdf, [2], { runtimeRoot }), { code: "page_out_of_range" });
});

test("rejects damaged PDF bytes with a safe error class", async () => {
  await assert.rejects(
    extractPdfText(new TextEncoder().encode("not a pdf"), [1], { runtimeRoot }),
    { code: "invalid_pdf" },
  );
});
