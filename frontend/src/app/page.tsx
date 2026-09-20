"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  BookOpenText, FileText, FolderSearch, LogOut, RefreshCw, Search,
  ShieldCheck, Trash2, UploadCloud,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { AgentTrace, type AgentBudget, type AgentStep } from "@/components/agent-trace";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

type Identity = {
  identity_mode: string;
  name: string;
  tenant: string;
  principals: string[];
  roles: string[];
  admin: boolean;
};
type Citation = { marker: number; doc_id: string; title?: string; section?: string; page?: number };
type Answer = {
  status: string;
  answer?: string;
  citations?: Citation[];
  n_contexts?: number;
  hints?: string[];
  route?: { requested_mode?: string; selected_mode?: string; reasons?: string[] };
  trace?: AgentStep[];
  budget?: AgentBudget;
  degraded?: boolean;
  finish_reason?: string | null;
  truncated?: boolean;
  generation_calls?: number;
  continuations?: number;
};
type Document = { doc_id: string; title?: string; doc_type?: string };
type UploadRecord = {
  document_id: string;
  job_id?: string;
  filename: string;
  owner: string;
  status: string;
  stage?: string;
  error_code?: string | null;
  source_format?: string;
  access_scope: string;
  groups?: string[];
};
type Job = {
  job_id?: string;
  document_status?: string;
  job_status?: string;
  stage?: string;
  chunk_count?: number;
  error_code?: string | null;
};
type DocumentDetail = { text: string; n_tokens?: number; truncated?: boolean };
type Section = { sec_id: string; title: string; level: number; start_idx: number };
type Hit = {
  chunk_id: string;
  doc_id: string;
  title?: string;
  section_path?: string;
  score?: number;
  score_kind?: string;
  kind?: string;
  text?: string;
};
type Retrieval = {
  status: string;
  hits: Hit[];
  meta?: { returned_n?: number; rerank_degraded?: boolean; budget_truncated?: boolean };
};

const fieldClass = "block h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm";
const primaryClass = "bg-[#0e7c76] hover:bg-[#096760]";

async function json(response: Response): Promise<Record<string, unknown>> {
  try { return (await response.json()) as Record<string, unknown>; }
  catch { return { hint: "服务返回了无法解析的内容。" }; }
}

function errorMessage(data: Record<string, unknown>, fallback: string): string {
  return typeof data.hint === "string" && data.hint ? data.hint : fallback;
}

function assertResponse(response: Response, data: Record<string, unknown>, allowed: string[], fallback: string) {
  if (!response.ok || !allowed.includes(String(data.status))) {
    throw new Error(errorMessage(data, `${fallback}（${String(data.status ?? response.status)}）`));
  }
}

function statusLabel(status?: string) {
  const labels: Record<string, string> = {
    queued: "排队中", processing: "处理中", ready: "已就绪", failed: "失败",
    deleted: "已删除", deleting: "删除中",
  };
  return labels[status ?? ""] ?? status ?? "未知";
}

export default function Home() {
  const [session, setSession] = useState<"checking" | "signed_out" | "ready">("checking");
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [key, setKey] = useState("");
  const [loginError, setLoginError] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [view, setView] = useState<"ask" | "retrieve" | "documents">("ask");

  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"auto" | "direct" | "agent">("auto");
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [askError, setAskError] = useState("");

  const [retrievalQuery, setRetrievalQuery] = useState("");
  const [retrievalStrategy, setRetrievalStrategy] = useState("hybrid");
  const [retrievalMode, setRetrievalMode] = useState("full");
  const [rerank, setRerank] = useState(true);
  const [retrieving, setRetrieving] = useState(false);
  const [retrieval, setRetrieval] = useState<Retrieval | null>(null);
  const [retrievalError, setRetrievalError] = useState("");
  const [expanded, setExpanded] = useState<Record<string, string>>({});
  const [expandingId, setExpandingId] = useState("");

  const [documents, setDocuments] = useState<Document[]>([]);
  const [uploads, setUploads] = useState<UploadRecord[]>([]);
  const [docSearch, setDocSearch] = useState("");
  const [documentsError, setDocumentsError] = useState("");
  const [loadingDocuments, setLoadingDocuments] = useState(false);
  const [selectedDocId, setSelectedDocId] = useState("");
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [outline, setOutline] = useState<Section[]>([]);
  const [detailError, setDetailError] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);
  const detailRequestId = useRef(0);

  const [file, setFile] = useState<File | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const uploadAttempt = useRef({ fingerprint: "", key: "" });
  const [scope, setScope] = useState("private");
  const [groups, setGroups] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState("");
  const [jobId, setJobId] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [selectedUploadId, setSelectedUploadId] = useState("");
  const [manageScope, setManageScope] = useState("private");
  const [manageGroups, setManageGroups] = useState("");
  const [managing, setManaging] = useState(false);
  const [manageMessage, setManageMessage] = useState("");
  const [manageError, setManageError] = useState("");

  const loadDocuments = useCallback(async () => {
    setLoadingDocuments(true);
    setDocumentsError("");
    try {
      const response = await fetch("/api/documents", { cache: "no-store" });
      const data = await json(response);
      assertResponse(response, data, ["ok", "empty"], "读取文档失败");
      setDocuments(Array.isArray(data.documents) ? data.documents as Document[] : []);
      if (identity?.identity_mode === "keys") {
        const uploadResponse = await fetch("/api/uploads", { cache: "no-store" });
        const uploadData = await json(uploadResponse);
        assertResponse(uploadResponse, uploadData, ["ok"], "读取上传记录失败");
        setUploads(Array.isArray(uploadData.documents) ? uploadData.documents as UploadRecord[] : []);
      }
    } catch (error) {
      setDocumentsError(error instanceof Error ? error.message : "读取文档失败。");
    } finally { setLoadingDocuments(false); }
  }, [identity]);

  useEffect(() => {
    let active = true;
    void fetch("/api/session", { cache: "no-store" }).then(async (response) => {
      const data = await json(response);
      if (!active) return;
      if (response.ok) { setIdentity(data as Identity); setSession("ready"); }
      else {
        setSession("signed_out");
        if (response.status !== 401) setLoginError(errorMessage(data, "连接后端失败。"));
      }
    }).catch(() => {
      if (active) { setSession("signed_out"); setLoginError("连接前端服务失败。"); }
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (session === "ready") queueMicrotask(() => void loadDocuments());
  }, [session, loadDocuments]);

  useEffect(() => {
    if (!jobId || session !== "ready") return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { cache: "no-store" });
        const data = await json(response);
        if (!active) return;
        if (response.ok && data.status === "ok") {
          setJob(data as Job);
          if (data.document_status === "ready" || data.document_status === "failed") {
            void loadDocuments();
            return;
          }
        }
      } catch { /* 下一轮重试。 */ }
      if (active) timer = setTimeout(poll, 3000);
    };
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [jobId, session, loadDocuments]);

  async function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setConnecting(true); setLoginError("");
    try {
      const response = await fetch("/api/session", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ key }),
      });
      const data = await json(response);
      assertResponse(response, data, ["ok"], "API Key 无效");
      setIdentity(data as Identity);
      setKey("");
      setSession("ready");
    } catch (error) { setLoginError(error instanceof Error ? error.message : "连接失败。"); }
    finally { setConnecting(false); }
  }

  async function disconnect() {
    await fetch("/api/session", { method: "DELETE" });
    detailRequestId.current += 1;
    setIdentity(null); setSession("signed_out");
    setAnswer(null); setRetrieval(null); setDocuments([]); setUploads([]);
    setSelectedDocId(""); setDetail(null); setSelectedUploadId("");
    setJobId(""); setJob(null);
  }

  async function ask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!query.trim()) return;
    setAsking(true); setAskError(""); setAnswer(null);
    try {
      const response = await fetch("/api/ask", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ query: query.trim(), mode, rerank: true, top_k: 4 }),
      });
      const data = await json(response);
      assertResponse(response, data, ["ok", "empty"], "问答失败");
      setAnswer(data as Answer);
    } catch (error) { setAskError(error instanceof Error ? error.message : "问答失败。"); }
    finally { setAsking(false); }
  }

  async function retrieve(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!retrievalQuery.trim()) return;
    setRetrieving(true); setRetrievalError(""); setRetrieval(null); setExpanded({});
    try {
      const response = await fetch("/api/retrieve", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ query: retrievalQuery.trim(), top_k: 6,
          rerank, mode: retrievalMode, strategy: retrievalStrategy }),
      });
      const data = await json(response);
      assertResponse(response, data, ["ok", "empty"], "检索失败");
      setRetrieval(data as Retrieval);
    } catch (error) { setRetrievalError(error instanceof Error ? error.message : "检索失败。"); }
    finally { setRetrieving(false); }
  }

  async function expand(hit: Hit) {
    setExpandingId(hit.chunk_id); setRetrievalError("");
    try {
      const response = await fetch("/api/expand", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ chunk_id: hit.chunk_id, target_tokens: 1500 }),
      });
      const data = await json(response);
      assertResponse(response, data, ["ok"], "扩展上下文失败");
      setExpanded((current) => ({ ...current, [hit.chunk_id]: String(data.text ?? "") }));
    } catch (error) { setRetrievalError(error instanceof Error ? error.message : "扩展上下文失败。"); }
    finally { setExpandingId(""); }
  }

  async function openDocument(docId: string) {
    const requestId = ++detailRequestId.current;
    setView("documents"); setSelectedDocId(docId);
    setDetail(null); setOutline([]); setDetailError(""); setDetailLoading(true);
    try {
      const path = `/api/documents/${encodeURIComponent(docId)}`;
      const [contentResponse, outlineResponse] = await Promise.all([
        fetch(path, { cache: "no-store" }),
        fetch(`${path}/outline`, { cache: "no-store" }),
      ]);
      const [content, sections] = await Promise.all([json(contentResponse), json(outlineResponse)]);
      if (requestId !== detailRequestId.current) return;
      assertResponse(contentResponse, content, ["ok"], "读取正文失败");
      setDetail(content as DocumentDetail);
      if (outlineResponse.ok && sections.status === "ok") {
        setOutline(Array.isArray(sections.sections) ? sections.sections as Section[] : []);
      } else {
        setDetailError(errorMessage(sections, "正文已加载，但目录暂不可用。"));
      }
    } catch (error) {
      if (requestId === detailRequestId.current)
        setDetailError(error instanceof Error ? error.message : "读取文档失败。");
    } finally { if (requestId === detailRequestId.current) setDetailLoading(false); }
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    setUploading(true); setUploadMessage("");
    try {
      const body = new FormData();
      body.set("file", file); body.set("access_scope", scope);
      if (scope === "restricted") body.set("groups", groups);
      const fingerprint = [file.name, file.size, file.lastModified, scope, groups].join(":");
      if (uploadAttempt.current.fingerprint !== fingerprint) {
        uploadAttempt.current = { fingerprint, key: crypto.randomUUID() };
      }
      const response = await fetch("/api/documents", {
        method: "POST",
        headers: { "Idempotency-Key": uploadAttempt.current.key },
        body,
      });
      const data = await json(response);
      assertResponse(response, data, ["accepted"], "上传失败");
      setUploadMessage("文件已接收，正在处理。下方可查看任务状态。");
      setJobId(typeof data.job_id === "string" ? data.job_id : "");
      setJob(null); setFile(null);
      uploadAttempt.current = { fingerprint: "", key: "" };
      if (fileInput.current) fileInput.current.value = "";
      await loadDocuments();
    } catch (error) { setUploadMessage(error instanceof Error ? error.message : "上传失败。"); }
    finally { setUploading(false); }
  }

  function selectUpload(record: UploadRecord) {
    setSelectedUploadId(record.document_id);
    setManageScope(record.access_scope || "private");
    setManageGroups((record.groups ?? []).join(","));
    setManageError(""); setManageMessage("");
    setJobId(record.job_id ?? "");
    setJob({ document_status: record.status, stage: record.stage, error_code: record.error_code });
  }

  async function startManagedJob(path: string, method: "POST" | "PATCH", body: object | null, success: string) {
    setManaging(true); setManageError(""); setManageMessage("");
    try {
      const response = await fetch(path, {
        method,
        ...(body ? { headers: { "content-type": "application/json" }, body: JSON.stringify(body) } : {}),
      });
      const data = await json(response);
      assertResponse(response, data, ["accepted"], "操作失败");
      setManageMessage(success);
      setJobId(typeof data.job_id === "string" ? data.job_id : ""); setJob(null);
      await loadDocuments();
    } catch (error) { setManageError(error instanceof Error ? error.message : "操作失败。"); }
    finally { setManaging(false); }
  }

  async function updateAccess(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedUpload) return;
    const requestedGroups = manageScope === "restricted"
      ? manageGroups.split(",").map((group) => group.trim()).filter(Boolean) : [];
    if (manageScope === "restricted" && !requestedGroups.length) {
      setManageError("指定用户组时至少填写一个组。"); return;
    }
    if (manageScope === "restricted" && !identity?.admin &&
        requestedGroups.some((group) => !identity?.principals.includes(group))) {
      setManageError("只能指定自己所属的用户组。"); return;
    }
    await startManagedJob(`/api/documents/${encodeURIComponent(selectedUpload.document_id)}/access`,
      "PATCH", { access_scope: manageScope, groups: requestedGroups }, "权限更新已提交，等待重新建库。");
  }

  async function removeDocument() {
    if (!selectedUpload || !window.confirm(`确定删除「${selectedUpload.filename}」吗？原文件与索引会被清理。`)) return;
    setManaging(true); setManageError(""); setManageMessage("");
    try {
      const response = await fetch(`/api/documents/${encodeURIComponent(selectedUpload.document_id)}`, {
        method: "DELETE",
      });
      const data = await json(response);
      assertResponse(response, data, ["ok"], "删除失败");
      if (selectedDocId === selectedUpload.document_id) {
        detailRequestId.current += 1;
        setSelectedDocId(""); setDetail(null); setOutline([]);
      }
      setSelectedUploadId(""); setJobId(""); setJob(null);
      setManageMessage("文档已删除。");
      await loadDocuments();
    } catch (error) { setManageError(error instanceof Error ? error.message : "删除失败。"); }
    finally { setManaging(false); }
  }

  const canUpload = identity?.identity_mode === "keys" &&
    (identity.admin || identity.roles.includes("uploader"));
  const selectedUpload = uploads.find((item) => item.document_id === selectedUploadId);
  const canManage = selectedUpload && (identity?.admin || selectedUpload.owner === identity?.name);
  const isBusy = selectedUpload && ["queued", "processing", "deleting"].includes(selectedUpload.status);
  const visibleDocs = documents.filter((doc) =>
    `${doc.title ?? ""} ${doc.doc_id}`.toLowerCase().includes(docSearch.toLowerCase().trim()));

  if (session === "checking")
    return <main className="grid min-h-screen place-items-center text-sm text-slate-500">正在连接 Pharos…</main>;

  if (session === "signed_out") return (
    <main className="flex min-h-screen items-center justify-center bg-[radial-gradient(circle_at_top_left,#d8f3eb,transparent_35%),#f4f7f9] px-5">
      <Card className="w-full max-w-md border-slate-200 bg-white/95 shadow-xl shadow-slate-200/50">
        <CardHeader className="space-y-4">
          <div className="grid size-12 place-items-center rounded-2xl bg-[#0e7c76] text-white"><BookOpenText size={24} /></div>
          <div><CardTitle className="text-2xl">连接 Pharos 知识库</CardTitle><CardDescription className="mt-2">使用你的 API Key 进入文档问答与知识库。</CardDescription></div>
        </CardHeader>
        <CardContent><form onSubmit={connect} className="space-y-4">
          <div className="space-y-2"><label htmlFor="api-key" className="text-sm font-medium">API Key</label><Input id="api-key" type="password" value={key} onChange={(event) => setKey(event.target.value)} autoComplete="off" placeholder="pk_…" required /></div>
          {loginError && <p role="alert" className="text-sm text-red-600">{loginError}</p>}
          <Button type="submit" disabled={connecting} className={`h-10 w-full ${primaryClass}`}>{connecting ? "正在验证…" : "连接知识库"}</Button>
          <p className="text-xs leading-5 text-slate-500">密钥由前端服务验证，并保存在仅服务端可读的会话 Cookie 中。</p>
        </form></CardContent>
      </Card>
    </main>
  );

  return (
    <div className="min-h-screen bg-[#f4f7f9] text-slate-900 lg:flex">
      <aside className="flex w-full shrink-0 flex-col bg-[#102c3c] px-5 py-6 text-white lg:min-h-screen lg:w-64">
        <div className="flex items-center gap-3 px-2"><div className="grid size-10 place-items-center rounded-xl bg-[#0e8b83]"><BookOpenText size={22} /></div><div><p className="text-lg font-semibold">Pharos</p><p className="text-xs text-slate-300">团队知识库</p></div></div>
        <nav className="mt-7 flex gap-2 lg:flex-col" aria-label="主导航">
          {([
            ["ask", "知识问答", Search],
            ["retrieve", "检索实验室", FolderSearch],
            ["documents", "文档库", FileText],
          ] as const).map(([target, title, Icon]) => (
            <button key={target} onClick={() => setView(target)} className={`flex flex-1 items-center gap-3 rounded-xl px-4 py-3 text-left text-sm lg:flex-none ${view === target ? "bg-[#17656a]" : "text-slate-300 hover:bg-white/10"}`}><Icon size={18} />{title}</button>
          ))}
        </nav>
        <div className="mt-8 rounded-xl border border-white/10 bg-white/5 p-4 lg:mt-auto">
          <p className="text-sm font-medium">{identity?.name}</p>
          <p className="mt-1 text-xs text-slate-300">租户 {identity?.tenant || "未设置"}</p>
          <div className="mt-3 flex flex-wrap gap-1">{identity?.admin && <Badge className="bg-teal-600 text-white">管理员</Badge>}{identity?.roles.map((role) => <Badge key={role} variant="secondary" className="bg-white/15 text-white">{role}</Badge>)}</div>
          <Button variant="ghost" onClick={disconnect} className="mt-4 w-full justify-start text-slate-200 hover:bg-white/10 hover:text-white"><LogOut size={16} />断开连接</Button>
        </div>
      </aside>

      <main className="mx-auto w-full max-w-6xl px-5 py-8 sm:px-9 lg:px-12 lg:py-12">
        {view === "ask" && <div className="space-y-7">
          <header><Badge variant="outline" className="border-teal-300 bg-teal-50 text-teal-800">Agentic RAG</Badge><h1 className="mt-3 text-3xl font-semibold">向团队文档提问</h1><p className="mt-2 text-slate-500">答案会附上可追溯的文档来源。</p></header>
          <Card className="border-slate-200 shadow-sm"><CardHeader><CardTitle>新问题</CardTitle><CardDescription>选择快速问答、自动路由或深度检索。</CardDescription></CardHeader><CardContent><form onSubmit={ask} className="space-y-4">
            <label htmlFor="query" className="sr-only">问题</label><Textarea id="query" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="例如：Docker volume 和 bind mount 有什么区别？" className="min-h-32 resize-y" />
            <div className="flex flex-wrap items-end justify-between gap-3"><div className="space-y-1"><label htmlFor="mode" className="text-xs font-medium text-slate-500">回答模式</label><select id="mode" value={mode} onChange={(event) => setMode(event.target.value as typeof mode)} className={fieldClass}><option value="auto">自动选择</option><option value="direct">快速问答</option><option value="agent">深度检索</option></select></div><Button type="submit" disabled={asking || !query.trim()} className={primaryClass}><Search size={16} />{asking ? "正在查找…" : "开始提问"}</Button></div>
          </form></CardContent></Card>
          {askError && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{askError}</p>}
          {answer && <Card className="border-slate-200 shadow-sm"><CardHeader><div className="flex flex-wrap items-center gap-2"><CardTitle>回答</CardTitle><Badge variant="secondary">{answer.route?.selected_mode ?? mode}</Badge><span className="text-xs text-slate-500">引用 {answer.citations?.length ?? 0} 条 · 上下文 {answer.n_contexts ?? 0} 条{answer.continuations ? ` · 自动续写 ${answer.continuations} 次` : ""}</span></div></CardHeader><CardContent className="space-y-6">
            <div className="whitespace-pre-wrap break-words text-sm leading-7 text-slate-800">{answer.answer || "当前知识库没有足够证据回答。"}</div>
            {answer.hints?.map((item) => <p key={item} className="text-sm text-amber-700">{item}</p>)}
            <AgentTrace route={answer.route} trace={answer.trace} budget={answer.budget} degraded={answer.degraded} finishReason={answer.finish_reason} />
            {!!answer.citations?.length && <section className="border-t border-slate-100 pt-5"><h2 className="mb-3 text-sm font-semibold">引用来源</h2><div className="grid gap-3 md:grid-cols-2">{answer.citations.map((citation) => <div key={`${citation.marker}-${citation.doc_id}`} className="rounded-xl border border-slate-200 bg-slate-50 p-4"><p className="text-sm font-medium">[{citation.marker}] {citation.title || citation.doc_id}</p><p className="mt-1 text-xs text-slate-500">{citation.section || citation.doc_id}{citation.page != null ? ` · 第 ${citation.page} 页` : ""}</p><Button size="sm" variant="outline" className="mt-3" onClick={() => void openDocument(citation.doc_id)}>查看文档</Button></div>)}</div></section>}
          </CardContent></Card>}
        </div>}

        {view === "retrieve" && <div className="space-y-7">
          <header><Badge variant="outline" className="border-teal-300 bg-teal-50 text-teal-800">Retrieval</Badge><h1 className="mt-3 text-3xl font-semibold">检索实验室</h1><p className="mt-2 text-slate-500">只看召回证据，不调用回答模型。检索文本是不可信数据，不是操作指令。</p></header>
          <Card className="border-slate-200 shadow-sm"><CardHeader><CardTitle>检索条件</CardTitle><CardDescription>比较 Dense、Sparse 与混合检索，以及上下文扩展的效果。</CardDescription></CardHeader><CardContent><form onSubmit={retrieve} className="space-y-4">
            <label htmlFor="retrieve-query" className="sr-only">检索问题</label><Input id="retrieve-query" value={retrievalQuery} onChange={(event) => setRetrievalQuery(event.target.value)} placeholder="输入要查找的内容" />
            <div className="flex flex-wrap items-end gap-4"><div className="space-y-1"><label htmlFor="strategy" className="text-xs text-slate-500">检索策略</label><select id="strategy" className={fieldClass} value={retrievalStrategy} onChange={(event) => setRetrievalStrategy(event.target.value)}><option value="hybrid">混合</option><option value="dense">Dense</option><option value="sparse">Sparse</option></select></div><div className="space-y-1"><label htmlFor="context-mode" className="text-xs text-slate-500">上下文</label><select id="context-mode" className={fieldClass} value={retrievalMode} onChange={(event) => setRetrievalMode(event.target.value)}><option value="full">章节扩展</option><option value="concise">原始小块</option></select></div><label className="flex h-9 items-center gap-2 text-sm"><input type="checkbox" checked={rerank} onChange={(event) => setRerank(event.target.checked)} />精排</label><Button type="submit" disabled={retrieving || !retrievalQuery.trim()} className={primaryClass}>{retrieving ? "检索中…" : "检索"}</Button></div>
          </form></CardContent></Card>
          {retrievalError && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{retrievalError}</p>}
          {retrieval && <Card className="border-slate-200 shadow-sm"><CardHeader><CardTitle>命中结果 <span className="text-sm font-normal text-slate-500">{retrieval.hits?.length ?? 0} 条</span></CardTitle>{retrieval.meta?.rerank_degraded && <CardDescription>精排暂不可用，结果按召回排序。</CardDescription>}{retrieval.meta?.budget_truncated && <CardDescription>上下文预算已截断部分内容。</CardDescription>}</CardHeader><CardContent className="space-y-4">{retrieval.hits?.length ? retrieval.hits.map((hit) => <article key={hit.chunk_id} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><p className="text-sm font-semibold">{hit.title || hit.doc_id}</p><p className="mt-1 text-xs text-slate-500">{hit.section_path || hit.doc_id} · {hit.kind || "text"} · {hit.score_kind || "score"} {typeof hit.score === "number" ? hit.score.toFixed(3) : ""}</p></div><div className="flex gap-2"><Button variant="outline" size="sm" onClick={() => void openDocument(hit.doc_id)}>文档</Button><Button variant="outline" size="sm" disabled={expandingId === hit.chunk_id} onClick={() => void expand(hit)}>{expandingId === hit.chunk_id ? "扩展中…" : "扩展上下文"}</Button></div></div><p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">{hit.text || "该结果没有可显示的正文。"}</p>{Object.prototype.hasOwnProperty.call(expanded, hit.chunk_id) && <div className="mt-4 rounded-lg bg-teal-50 p-4"><p className="mb-2 text-xs font-semibold text-teal-800">扩展后的上下文</p><p className="whitespace-pre-wrap break-words text-sm leading-6">{expanded[hit.chunk_id]}</p></div>}</article>) : <p className="text-sm text-slate-500">当前条件下没有命中结果。</p>}</CardContent></Card>}
        </div>}

        {view === "documents" && <div className="space-y-7">
          <header className="flex flex-wrap items-end justify-between gap-3"><div><Badge variant="outline" className="border-teal-300 bg-teal-50 text-teal-800">Knowledge Base</Badge><h1 className="mt-3 text-3xl font-semibold">文档库</h1><p className="mt-2 text-slate-500">可检索文档与上传管理记录分开显示，均按当前身份过滤。</p></div><Button variant="outline" onClick={() => void loadDocuments()} disabled={loadingDocuments}><RefreshCw size={16} />刷新</Button></header>
          {!selectedUploadId && manageMessage && <p role="status" className="rounded-xl border border-teal-200 bg-teal-50 p-4 text-sm text-teal-800">{manageMessage}</p>}
          {documentsError && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{documentsError}</p>}
          <Card className="border-slate-200 shadow-sm"><CardHeader><CardTitle>可访问文档 <span className="ml-2 text-sm font-normal text-slate-500">{documents.length}</span></CardTitle><CardDescription>这里显示当前身份能检索到的文档；新上传的文档处理完成后才会出现。</CardDescription></CardHeader><CardContent><Input aria-label="筛选文档" value={docSearch} onChange={(event) => setDocSearch(event.target.value)} placeholder="按标题或文档 ID 筛选" className="mb-4 max-w-md" />{loadingDocuments ? <p className="text-sm text-slate-500">正在读取…</p> : visibleDocs.length ? <div className="grid gap-3 sm:grid-cols-2">{visibleDocs.map((doc) => <div key={doc.doc_id} className="flex gap-3 rounded-xl border border-slate-200 p-4"><FileText size={20} className="mt-0.5 shrink-0 text-teal-700" /><div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{doc.title || doc.doc_id}</p><p className="mt-1 truncate text-xs text-slate-500">{doc.doc_id}</p><div className="mt-3 flex items-center gap-2">{doc.doc_type && <Badge variant="secondary">{doc.doc_type}</Badge>}<Button size="sm" variant="outline" onClick={() => void openDocument(doc.doc_id)}>阅读</Button></div></div></div>)}</div> : <p className="text-sm text-slate-500">{documents.length ? "没有匹配的文档。" : "还没有可访问的文档。"}</p>}</CardContent></Card>

          {selectedDocId && <Card className="border-slate-200 shadow-sm"><CardHeader><div className="flex flex-wrap items-center justify-between gap-2"><CardTitle>文档内容</CardTitle><Button variant="outline" size="sm" onClick={() => { detailRequestId.current += 1; setSelectedDocId(""); setDetail(null); setOutline([]); }}>关闭</Button></div><CardDescription className="break-all">{selectedDocId} · 正文按后端 ACL 裁剪</CardDescription></CardHeader><CardContent className="space-y-5">{detailLoading && <p className="text-sm text-slate-500">正在读取正文和目录…</p>}{detailError && <p role="alert" className="text-sm text-amber-700">{detailError}</p>}{detail && <div className="grid gap-5 lg:grid-cols-[220px_minmax(0,1fr)]"><aside className="rounded-xl border border-slate-200 bg-slate-50 p-4"><h2 className="mb-3 text-sm font-semibold">目录</h2>{outline.length ? <div className="space-y-1">{outline.map((section) => <p key={section.sec_id} className="break-words text-xs leading-5 text-slate-600" style={{ paddingLeft: Math.min(Math.max(section.level, 0), 4) * 10 }}>{section.title}</p>)}</div> : <p className="text-xs text-slate-500">没有可见章节。</p>}</aside><div className="min-w-0 rounded-xl border border-slate-200 p-4"><p className="mb-3 text-xs text-slate-500">约 {detail.n_tokens ?? 0} tokens{detail.truncated ? " · 正文已截断" : ""}</p><pre className="max-h-[600px] overflow-auto whitespace-pre-wrap break-words font-sans text-sm leading-7">{detail.text || "没有可显示的正文。"}</pre></div></div>}</CardContent></Card>}

          {canUpload && <Card className="border-slate-200 shadow-sm"><CardHeader><CardTitle className="flex items-center gap-2"><UploadCloud size={20} className="text-teal-700" />上传文档</CardTitle><CardDescription>支持 Markdown 和 PDF；上传后异步解析并建库。</CardDescription></CardHeader><CardContent><form onSubmit={upload} className="space-y-4"><div className="space-y-2"><label htmlFor="file" className="text-sm font-medium">选择文件</label><Input id="file" ref={fileInput} type="file" accept=".md,.markdown,.pdf" onChange={(event) => setFile(event.target.files?.[0] ?? null)} required /></div><div className="flex flex-wrap gap-4"><div className="space-y-2"><label htmlFor="scope" className="text-sm font-medium">访问范围</label><select id="scope" value={scope} onChange={(event) => setScope(event.target.value)} className={fieldClass}><option value="private">仅自己</option><option value="restricted">指定用户组</option>{identity?.admin && <option value="tenant">整个租户</option>}</select></div>{scope === "restricted" && <div className="min-w-52 flex-1 space-y-2"><label htmlFor="groups" className="text-sm font-medium">用户组</label><Input id="groups" value={groups} onChange={(event) => setGroups(event.target.value)} placeholder="g_eng,g_ops" required /><p className="text-xs text-slate-500">非管理员只能选择自己所属的组。</p></div>}</div><Button type="submit" disabled={uploading || !file} className={primaryClass}>{uploading ? "正在上传…" : "上传并建库"}</Button></form>{uploadMessage && <p role="status" className="mt-4 text-sm text-slate-700">{uploadMessage}</p>}</CardContent></Card>}

          {jobId && <Card className="border-slate-200 shadow-sm"><CardHeader><CardTitle>当前任务</CardTitle><CardDescription className="break-all">{jobId}</CardDescription></CardHeader><CardContent className="flex flex-wrap items-center gap-3 text-sm"><Badge variant="secondary">{statusLabel(job?.document_status ?? "queued")}</Badge><span>{job?.stage || "等待处理"}</span>{job?.chunk_count != null && <span>{job.chunk_count} 块</span>}{job?.error_code && <span className="text-red-600">错误：{job.error_code}</span>}{job?.document_status === "failed" && job.error_code !== "access_update_failed" && <Button variant="outline" size="sm" disabled={managing} onClick={() => void startManagedJob(`/api/jobs/${encodeURIComponent(jobId)}/retry`, "POST", null, "重试任务已提交。")}>重试</Button>}</CardContent></Card>}

          {identity?.identity_mode === "keys" && <Card className="border-slate-200 shadow-sm"><CardHeader><CardTitle>上传管理 <span className="ml-2 text-sm font-normal text-slate-500">{uploads.length}</span></CardTitle><CardDescription>{identity.admin ? "当前租户的上传记录" : "你上传的文档"}；包含尚未进入检索库的任务。</CardDescription></CardHeader><CardContent className="space-y-2">{uploads.length ? uploads.map((record) => <div key={record.document_id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 px-4 py-3 text-sm"><div className="min-w-0"><p className="truncate font-medium">{record.filename || record.document_id}</p><p className="mt-1 break-all text-xs text-slate-500">{record.document_id} · {record.owner} · {record.access_scope}</p></div><div className="flex items-center gap-2"><Badge variant="secondary">{statusLabel(record.status)}</Badge><Button variant="outline" size="sm" onClick={() => selectUpload(record)}>管理</Button></div></div>) : <p className="text-sm text-slate-500">还没有上传记录。</p>}</CardContent></Card>}

          {selectedUpload && canManage && <Card className="border-slate-200 shadow-sm"><CardHeader><div className="flex items-center gap-2"><ShieldCheck size={20} className="text-teal-700" /><CardTitle>管理 {selectedUpload.filename}</CardTitle></div><CardDescription className="break-all">当前权限：{selectedUpload.access_scope}{selectedUpload.groups?.length ? ` · ${selectedUpload.groups.join(", ")}` : ""}{selectedUpload.error_code ? ` · 错误：${selectedUpload.error_code}` : ""}</CardDescription></CardHeader><CardContent className="space-y-5">{manageError && <p role="alert" className="text-sm text-red-600">{manageError}</p>}{manageMessage && <p role="status" className="text-sm text-teal-700">{manageMessage}</p>}<div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" disabled={selectedUpload.status !== "ready"} onClick={() => void openDocument(selectedUpload.document_id)}>阅读正文</Button><Button variant="outline" size="sm" disabled={managing || !!isBusy} onClick={() => void startManagedJob(`/api/documents/${encodeURIComponent(selectedUpload.document_id)}/reindex`, "POST", null, "重建索引已提交。")}>重建索引</Button>{selectedUpload.status === "failed" && selectedUpload.job_id && selectedUpload.error_code !== "access_update_failed" && <Button variant="outline" size="sm" disabled={managing} onClick={() => void startManagedJob(`/api/jobs/${encodeURIComponent(selectedUpload.job_id ?? "")}/retry`, "POST", null, "重试任务已提交。")}>重试失败任务</Button>}</div><form onSubmit={updateAccess} className="space-y-3 rounded-xl border border-slate-200 p-4"><h3 className="text-sm font-semibold">调整阅读权限</h3><p className="text-xs text-slate-500">提交后会下线旧索引并按新权限重建；处理中暂不可再次修改。</p><div className="flex flex-wrap gap-3"><div className="space-y-1"><label htmlFor="manage-scope" className="text-xs text-slate-500">访问范围</label><select id="manage-scope" className={fieldClass} value={manageScope} onChange={(event) => setManageScope(event.target.value)}><option value="private">仅自己</option><option value="restricted">指定用户组</option>{identity?.admin && <option value="tenant">整个租户</option>}</select></div>{manageScope === "restricted" && <div className="min-w-48 flex-1 space-y-1"><label htmlFor="manage-groups" className="text-xs text-slate-500">用户组（逗号分隔）</label><Input id="manage-groups" value={manageGroups} onChange={(event) => setManageGroups(event.target.value)} required /></div>}</div><Button type="submit" size="sm" disabled={managing || !!isBusy} className={primaryClass}>保存权限</Button></form><div className="border-t border-slate-100 pt-4"><Button variant="destructive" size="sm" disabled={managing || !!isBusy} onClick={() => void removeDocument()}><Trash2 size={15} />删除文档</Button><p className="mt-2 text-xs text-slate-500">删除会清理原文件与索引，操作前会再次确认。</p></div></CardContent></Card>}
        </div>}
      </main>
    </div>
  );
}
