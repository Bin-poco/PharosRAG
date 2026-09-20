/* Optional live PDF/MinerU test. PHAROS_SMOKE_PDF_PATH must point to a disposable PDF. */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { basename } from "node:path";

const web = process.env.PHAROS_WEB_URL ?? "http://127.0.0.1:3001";
const api = process.env.PHAROS_API_URL ?? "http://127.0.0.1:8787";
const key = process.env.PHAROS_DEV_API_KEY;
const pdfPath = process.env.PHAROS_SMOKE_PDF_PATH;
const expectedText = process.env.PHAROS_SMOKE_EXPECT_TEXT;
assert.ok(key && pdfPath, "PHAROS_DEV_API_KEY and PHAROS_SMOKE_PDF_PATH are required");

let documentId = "";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

try {
  const login = await fetch(`${web}/api/session`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ key }), signal: AbortSignal.timeout(120_000),
  });
  assert.equal(login.status, 200, await login.text());
  const cookie = (login.headers.get("set-cookie") ?? "").split(";")[0];
  assert.ok(cookie.startsWith("pharos_key="));

  const bytes = await readFile(pdfPath);
  const body = new FormData();
  body.set("file", new Blob([bytes], { type: "application/pdf" }), basename(pdfPath));
  body.set("access_scope", "private");
  const upload = await fetch(`${web}/api/documents`, {
    method: "POST", headers: { cookie }, body, signal: AbortSignal.timeout(120_000),
  });
  const accepted = await upload.json();
  console.log(`PDF upload: HTTP ${upload.status}, status=${accepted.status}`);
  assert.equal(upload.status, 202, JSON.stringify(accepted));
  documentId = accepted.document_id;
  const jobId = accepted.job_id;
  assert.ok(documentId && jobId);

  let job;
  for (let attempt = 0; attempt < 120; attempt++) {
    const response = await fetch(`${web}/api/jobs/${encodeURIComponent(jobId)}`, {
      headers: { cookie }, signal: AbortSignal.timeout(120_000),
    });
    assert.equal(response.status, 200);
    job = await response.json();
    if (attempt === 0 || attempt % 5 === 0 || ["ready", "failed"].includes(job.document_status)) {
      console.log(`PDF job: ${job.document_status}, stage=${job.stage}, error=${job.error_code ?? "none"}`);
    }
    if (["ready", "failed"].includes(job.document_status)) break;
    await sleep(3000);
  }
  assert.equal(job?.document_status, "ready", JSON.stringify(job));
  assert.equal(job?.source_format, "pdf");
  const content = await fetch(`${api}/v1/documents/${encodeURIComponent(documentId)}`, {
    headers: { "X-API-Key": key }, signal: AbortSignal.timeout(120_000),
  });
  const parsed = await content.json();
  assert.equal(content.status, 200, JSON.stringify(parsed));
  assert.ok(typeof parsed.text === "string" && parsed.text.trim(), "parsed PDF text is empty");
  if (expectedText) assert.ok(parsed.text.includes(expectedText), "expected text missing from parsed PDF");
} catch (error) {
  console.error("PDF SMOKE TEST FAILED:", error);
  process.exitCode = 1;
} finally {
  if (documentId) {
    let removed;
    for (let attempt = 0; attempt < 90; attempt++) {
      removed = await fetch(`${api}/v1/documents/${encodeURIComponent(documentId)}`, {
        method: "DELETE", headers: { "X-API-Key": key }, signal: AbortSignal.timeout(120_000),
      });
      if (removed.status !== 409 && removed.status !== 503) break;
      await sleep(2000);
    }
    console.log(`PDF cleanup: HTTP ${removed.status}`);
    if (removed.status !== 200) process.exitCode = 1;
  }
}
if (process.exitCode !== 1) console.log("PDF SMOKE TEST PASSED");
