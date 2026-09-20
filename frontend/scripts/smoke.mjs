/* Live integration smoke test. Requires PHAROS_DEV_API_KEY and running services. */
import assert from "node:assert/strict";

const web = process.env.PHAROS_WEB_URL ?? "http://127.0.0.1:3001";
const api = process.env.PHAROS_API_URL ?? "http://127.0.0.1:8787";
const key = process.env.PHAROS_DEV_API_KEY;
assert.ok(key, "PHAROS_DEV_API_KEY is required");

let cookie = "";
let createdDocument = "";
let testJob = "";

async function request(base, path, options = {}) {
  const headers = new Headers(options.headers);
  if (base === api) headers.set("X-API-Key", key);
  if (base === web && cookie) headers.set("cookie", cookie);
  const response = await fetch(`${base}${path}`, {
    ...options,
    headers,
    signal: AbortSignal.timeout(120_000),
  });
  let data;
  try { data = await response.json(); }
  catch { data = await response.text(); }
  return { response, data };
}

async function check(label, base, path, options = {}, expectedHttp = 200, expectedStatus = "ok") {
  const result = await request(base, path, options);
  const { response, data } = result;
  const code = response.status;
  const status = data?.status;
  console.log(`${label}: HTTP ${code}, status=${String(status)}`);
  assert.equal(code, expectedHttp, `${label}: ${JSON.stringify(data).slice(0, 500)}`);
  if (expectedStatus) assert.equal(status, expectedStatus, label);
  return result;
}

function postJson(value) {
  return { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(value) };
}

function wait(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

async function waitForJob(jobId) {
  let finalJob;
  for (let attempt = 0; attempt < 90; attempt++) {
    const result = await check("frontend job", web, `/api/jobs/${encodeURIComponent(jobId)}`);
    finalJob = result.data;
    if (["ready", "failed"].includes(finalJob.document_status)) break;
    await wait(2000);
  }
  assert.equal(finalJob?.document_status, "ready", JSON.stringify(finalJob));
}

try {
  await check("backend health", api, "/healthz");
  await check("backend ready", api, "/readyz", {}, 200, "ready");
  await check("backend me", api, "/v1/me");
  await check("backend instructions", api, "/v1/instructions");
  await check("backend stats", api, "/v1/stats");

  await check("frontend session anonymous", web, "/api/session", {}, 401, "unauthorized");
  await check("frontend documents anonymous", web, "/api/documents", {}, 401, "unauthorized");
  await check("frontend ask anonymous", web, "/api/ask", postJson({ query: "test" }), 401, "unauthorized");
  await check("frontend retrieve anonymous", web, "/api/retrieve", postJson({ query: "test" }), 401, "unauthorized");
  await check("frontend upload records anonymous", web, "/api/uploads", {}, 401, "unauthorized");
  await check("frontend login invalid", web, "/api/session", postJson({ key: "invalid-smoke-key" }), 401, "unauthorized");
  const login = await check("frontend login", web, "/api/session", postJson({ key }));
  assert.equal(login.data.name !== undefined, true);
  assert.equal("key" in login.data, false);
  const setCookie = login.response.headers.get("set-cookie") ?? "";
  assert.match(setCookie, /HttpOnly/i);
  assert.match(setCookie, /SameSite=strict/i);
  cookie = setCookie.split(";")[0];
  assert.ok(cookie.startsWith("pharos_key="));
  await check("frontend session", web, "/api/session");
  const docs = await check("frontend documents", web, "/api/documents");
  assert.ok(Array.isArray(docs.data.documents) && docs.data.documents.length > 0);
  const uploads = await check("frontend uploads", web, "/api/uploads");
  assert.ok(Array.isArray(uploads.data.documents));
  if (uploads.data.documents.length) {
    assert.equal(typeof uploads.data.documents[0].document_id, "string");
    assert.equal(typeof uploads.data.documents[0].filename, "string");
  }

  const docId = docs.data.documents.find((item) => item.doc_id === "docker__volumes")?.doc_id
    ?? docs.data.documents[0].doc_id;
  const encodedDoc = encodeURIComponent(docId);
  await check("frontend document", web, `/api/documents/${encodedDoc}`);
  await check("frontend outline", web, `/api/documents/${encodedDoc}/outline`);
  const retrieve = await check("frontend retrieve", web, "/api/retrieve", postJson({ query: "Docker volume 与 bind mount 有什么区别", top_k: 3, strategy: "hybrid", mode: "full" }));
  assert.ok(Array.isArray(retrieve.data.hits) && retrieve.data.hits.length > 0);
  await check("frontend expand", web, "/api/expand", postJson({ chunk_id: retrieve.data.hits[0].chunk_id, target_tokens: 1000 }));
  await check("backend grouped", api, "/v1/retrieve_grouped", postJson({
    query: "Docker volume", doc_ids: [docId], top_k: 3,
  }));

  if (process.env.PHAROS_SMOKE_SKIP_ASK !== "1") {
    const question = { query: "Docker volume 和 bind mount 有什么区别？", top_k: 4, rerank: true };
    for (const mode of ["direct", "auto", "agent"]) {
      const result = await check(`frontend ask ${mode}`, web, "/api/ask", postJson({ ...question, mode }));
      assert.equal(typeof result.data.answer, "string");
      assert.ok(result.data.answer.length > 0);
      assert.ok(Array.isArray(result.data.citations));
      if (mode !== "direct") {
        assert.ok(["direct", "agent"].includes(result.data.route?.selected_mode));
        assert.ok(Array.isArray(result.data.trace) && result.data.trace.length > 0);
        assert.equal(result.data.budget?.steps, result.data.trace.length);
        assert.equal(typeof result.data.budget?.retrievals, "number");
        assert.equal(typeof result.data.budget?.llm_calls, "number");
        assert.equal(typeof result.data.degraded, "boolean");
      }
      console.log(`  answer length=${result.data.answer.length}, citations=${result.data.citations.length}`);
    }
    await check("backend explicit agent", api, "/v1/agent/ask", postJson({ ...question, mode: "direct" }));
  }

  const body = new FormData();
  const filename = `pharos_smoke_${Date.now()}.md`;
  body.set("file", new Blob(["# Smoke Test\n\nThis temporary private document checks the upload pipeline.\n"], { type: "text/markdown" }), filename);
  body.set("access_scope", "private");
  const uploaded = await check("frontend upload", web, "/api/documents", { method: "POST", body }, 202, "accepted");
  createdDocument = uploaded.data.document_id;
  testJob = uploaded.data.job_id;
  assert.ok(createdDocument && testJob);
  await waitForJob(testJob);
  await check("frontend retry nonfailed", web, `/api/jobs/${encodeURIComponent(testJob)}/retry`, { method: "POST" }, 409, "job_not_retryable");
  const refreshed = await check("frontend uploaded docs", web, "/api/documents");
  assert.ok(refreshed.data.documents.some((item) => item.doc_id === createdDocument));
  const refreshedUploads = await check("frontend uploaded records", web, "/api/uploads");
  assert.ok(refreshedUploads.data.documents.some((item) => item.document_id === createdDocument));

  const reindex = await check("frontend reindex", web,
    `/api/documents/${encodeURIComponent(createdDocument)}/reindex`, { method: "POST" }, 202, "accepted");
  await waitForJob(reindex.data.job_id);
  const access = await check("frontend update access", web,
    `/api/documents/${encodeURIComponent(createdDocument)}/access`, {
      method: "PATCH", headers: { "content-type": "application/json" },
      body: JSON.stringify({ access_scope: "restricted", groups: ["g_dev"] }),
    }, 202, "accepted");
  await waitForJob(access.data.job_id);
  await check("frontend updated document", web, `/api/documents/${encodeURIComponent(createdDocument)}`);

  const removed = await check("frontend delete", web,
    `/api/documents/${encodeURIComponent(createdDocument)}`, { method: "DELETE" });
  assert.equal(removed.data.document_id, createdDocument);
  createdDocument = "";

  await check("frontend logout", web, "/api/session", { method: "DELETE" });
  cookie = "";
  await check("frontend session after logout", web, "/api/session", {}, 401, "unauthorized");
} catch (error) {
  console.error("SMOKE TEST FAILED:", error);
  process.exitCode = 1;
} finally {
  if (createdDocument) {
    try {
      let removed;
      for (let attempt = 0; attempt < 90; attempt++) {
        removed = await request(api, `/v1/documents/${encodeURIComponent(createdDocument)}`,
          { method: "DELETE" });
        if (removed.response.status !== 409 && removed.response.status !== 503) break;
        await wait(2000);
      }
      console.log(`cleanup temporary document: HTTP ${removed.response.status}, status=${removed.data.status}`);
      assert.equal(removed.response.status, 200, JSON.stringify(removed.data));
      assert.equal(removed.data.document_id, createdDocument);
    } catch (error) {
      console.error(`CLEANUP FAILED for temporary document ${createdDocument}:`, error);
      process.exitCode = 1;
    }
  }
}
if (process.exitCode !== 1) console.log("SMOKE TEST PASSED");
