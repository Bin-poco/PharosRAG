/* Live acceptance test: two distinct identities in the same tenant. Creates and deletes one disposable document. */
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";

const api = process.env.PHAROS_API_URL ?? "http://127.0.0.1:8787";
const ownerKey = process.env.PHAROS_DEV_API_KEY;
const readerKey = process.env.PHAROS_SECOND_API_KEY;
assert.ok(ownerKey && readerKey && ownerKey !== readerKey,
  "Set two different keys in PHAROS_DEV_API_KEY and PHAROS_SECOND_API_KEY");

let documentId = "";

async function call(key, path, options = {}) {
  const headers = new Headers(options.headers);
  headers.set("X-API-Key", key);
  const response = await fetch(`${api}${path}`, {
    ...options, headers, signal: AbortSignal.timeout(120_000),
  });
  const data = await response.json();
  return { code: response.status, data };
}

function json(body, method = "POST") {
  return { method, headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
}

function expect(result, code, status, label) {
  console.log(`${label}: HTTP ${result.code}, status=${result.data.status}`);
  assert.equal(result.code, code, label);
  assert.equal(result.data.status, status, label);
  return result.data;
}

async function poll(jobId) {
  for (let attempt = 0; attempt < 90; attempt++) {
    const result = expect(await call(ownerKey, `/v1/jobs/${encodeURIComponent(jobId)}`), 200, "ok", "owner job");
    if (result.document_status === "ready") return;
    if (result.document_status === "failed") throw new Error(`Ingestion failed: ${result.error_code ?? "unknown"}`);
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error(`Job did not finish: ${jobId}`);
}

async function visible(key, query, shouldSee, label) {
  const docs = await call(key, "/v1/documents");
  assert.ok(["ok", "empty"].includes(docs.data.status), label);
  assert.equal(docs.data.documents.some((doc) => doc.doc_id === documentId), shouldSee, `${label}: list`);

  const detail = await call(key, `/v1/documents/${encodeURIComponent(documentId)}`);
  expect(detail, 200, shouldSee ? "ok" : "no_access", `${label}: read`);

  const results = await call(key, "/v1/retrieve", json({ query, doc_ids: [documentId], top_k: 4, rerank: false }));
  assert.ok(["ok", "empty"].includes(results.data.status), `${label}: retrieve ${results.data.status}`);
  const hits = results.data.hits.filter((hit) => hit.doc_id === documentId);
  assert.equal(hits.length > 0, shouldSee, `${label}: retrieval visibility`);
  console.log(`${label}: list/read/retrieve ${shouldSee ? "visible" : "isolated"}`);
}

async function answer(key, query, shouldCite, label) {
  const result = expect(await call(key, "/v1/ask", json({
    query, doc_ids: [documentId], mode: "direct", top_k: 4, rerank: false,
  })), 200, "ok", label);
  const citations = result.citations ?? [];
  assert.equal(citations.some((citation) => citation.doc_id === documentId), shouldCite,
    `${label}: citations must ${shouldCite ? "include" : "exclude"} the test document`);
  if (!shouldCite) assert.equal(result.n_contexts, 0, `${label}: inaccessible context leaked`);
}

try {
  const owner = expect(await call(ownerKey, "/v1/me"), 200, "ok", "owner identity");
  const reader = expect(await call(readerKey, "/v1/me"), 200, "ok", "reader identity");
  assert.notEqual(owner.name, reader.name, "Keys must represent different users");
  assert.equal(owner.tenant, reader.tenant, "Keys must belong to the same tenant");
  assert.ok(owner.admin || owner.roles.includes("uploader"), "First user must be able to upload");
  assert.ok(owner.admin, "First user must be admin to publish tenant-wide for the sharing phase");
  assert.equal(reader.admin, false, "Second user must not be admin; admin bypasses document ACL");

  const nonce = randomUUID().replaceAll("-", "").slice(0, 12);
  const query = `According to the private handbook, what is the retention window for vault ${nonce}?`;
  const content = `# Vault ${nonce} retention handbook\n\nFor vault ${nonce}, the retention window is 37 days. This handbook defines the retention window for this vault, not for any other system.\n`;
  const body = new FormData();
  body.set("file", new Blob([content], { type: "text/markdown" }), `acl-smoke-${nonce}.md`);
  body.set("access_scope", "private");
  const created = expect(await call(ownerKey, "/v1/documents", { method: "POST", body }), 202, "accepted", "upload private");
  documentId = created.document_id;
  assert.ok(documentId && created.job_id);
  await poll(created.job_id);

  await visible(ownerKey, query, true, "owner private");
  await visible(readerKey, query, false, "reader private");
  expect(await call(readerKey, `/v1/jobs/${encodeURIComponent(created.job_id)}`), 404, "not_found", "reader job");
  expect(await call(readerKey, `/v1/documents/${encodeURIComponent(documentId)}`, { method: "DELETE" }), 404, "not_found", "reader management");
  await answer(ownerKey, query, true, "owner answer and citation");
  await answer(readerKey, query, false, "reader answer isolated");

  const shared = expect(await call(ownerKey, `/v1/documents/${encodeURIComponent(documentId)}/access`,
    json({ access_scope: "tenant", groups: [] }, "PATCH")), 202, "accepted", "publish tenant");
  await poll(shared.job_id);
  await visible(readerKey, query, true, "reader after sharing");
  await answer(readerKey, query, true, "reader answer after sharing");

  const revoked = expect(await call(ownerKey, `/v1/documents/${encodeURIComponent(documentId)}/access`,
    json({ access_scope: "private", groups: [] }, "PATCH")), 202, "accepted", "revoke sharing");
  await poll(revoked.job_id);
  await visible(readerKey, query, false, "reader after revocation");
  await answer(readerKey, query, false, "reader answer after revocation");
  console.log("TWO-USER ACCEPTANCE PASSED");
} catch (error) {
  console.error("TWO-USER ACCEPTANCE FAILED:", error);
  process.exitCode = 1;
} finally {
  if (documentId) {
    try {
      let result;
      for (let attempt = 0; attempt < 90; attempt++) {
        result = await call(ownerKey, `/v1/documents/${encodeURIComponent(documentId)}`, { method: "DELETE" });
        if (![409, 503].includes(result.code)) break;
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }
      expect(result, 200, "ok", "cleanup temporary document");
    } catch (error) {
      console.error(`CLEANUP FAILED for ${documentId}:`, error);
      process.exitCode = 1;
    }
  }
}
