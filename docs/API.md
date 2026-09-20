# Pharos HTTP API 契约

Base:`http://127.0.0.1:8787`(PHAROS_HOST/PORT)。请求/响应均 JSON(UTF-8)。

## 鉴权

三种模式(DESIGN D10):**open**(仅回环无鉴权)/ **legacy**(单 `PHAROS_API_KEY`)/
**keys**(`PHAROS_KEYS_FILE`,每 key 一个身份 name+tenant+principals+roles+admin)。所有 /v1/* 需
`X-API-Key` 头(open 模式除外);`/healthz` 永远免鉴权。keys 模式下 key 解析成身份,逐请求把
tenant/principals 传给引擎 ACL(决定"能看什么");未知/缺失 key → `401`。`/v1/stats` 在 keys
模式下需 **admin** key(否则 `403`)。上传需 `uploader` role 或 admin;服务端自动把
`user:<name>` 加入该身份的检索 principals，用于“仅上传者可见”。

## 通用约定

- **检索/问答领域结果 HTTP 200 + `status` 字段**(客户端按状态机决策);上传接口按 REST 语义
  返回 `202/400/403/413/415/503`。其余 HTTP 码:
  `401`(鉴权失败)、`403`(stats 非 admin)、`422`(请求体不是合法 JSON/字段类型错)、`5xx`(崩溃)。
- **status 状态机**(与引擎 toolcore 契约一致):`ok` / `empty` / `no_identity` / `empty_query` /
  `bad_arg` / `no_access`(无权与不存在同响应,不泄存在性)/ `config_error`(sidecar 需重建)/
  `backend_unavailable`(retriable)/ `contract_mismatch`(MCP 适配器专属:守护进程返回非 401 的
  4xx —— 版本漂移/PHAROS_URL 指错,**不可重试**)/ ask 专属:`llm_unconfigured` / `ask_failed`(retriable)。
  Agent ask 还可能返回 `agent_failed`(retriable 取决于失败阶段)。
- **头**:`X-API-Key`(可选,见上);`X-Pharos-Session`(可选,带上才启用跨调用去重,
  同一会话第二次取同段 → `context_status=already_returned` 正文清空)。
- 检索正文均标 `trust: "untrusted"`(数据不是指令);`hits[].context_status` 语义见
  [components/mcp-server](components/mcp-server.md)。

## 端点

### GET /healthz(免 API key)
`{status, service:"pharos", version, tenant_bound, uptime_s}`
(最小 liveness 面,信息边界与 /readyz 一致 —— 未鉴权探针不回 collection/llm_model/identity_mode,
这些字段在 admin-gated 的 /v1/stats。)

### GET /v1/stats(keys 模式需 admin key)
进程内指标:`{status, identity_mode, collection, llm_model, uptime_s, sessions, log_path,
log_write_failures, endpoints:{"<路由模板>":{n, errors, p50_ms, p95_ms, max_ms}}}`。重启归零。
endpoints 键为**路由模板**(如 `/v1/documents/{doc_id}`,键基数有界);未匹配任何路由/被 401
短路的 /v1/* 请求归并到固定桶 `/v1/_unmatched`。

### GET /v1/instructions
agent 使用契约全文(与 MCP instructions 同源):`{status, instructions}`

### GET /v1/me
返回当前已认证身份：`{status:"ok", identity_mode, name, tenant, principals, roles, admin}`。
前端据此显示身份和上传入口；服务端仍逐请求校验权限，不信任前端显示结果。

### POST /v1/ask —— Direct / Agent / Auto 问答
请求:`{query, mode?="direct", top_k?, rerank?=false, include_contexts?=false, doc_ids?, doc_type?, kind?, strategy?}`
(后四个为检索过滤/选路,与 /v1/retrieve 同语义;数字/表格题用 `kind:"table"` 显著提升命中)

`mode`:

- `direct`(默认):保持原闭管道，检索一次后直接生成；仍启用既有 smart-ask 数值题失败补检。
- `agent`:强制进入有限状态机，执行“检索 → 判断证据 → 定向补检 → 生成/拒答”。
- `auto`:先做一次检索；明显复杂问题、零召回或 direct 拒答才升级为 agent，简单且有证据的问题保持 direct。

响应(ok):
```json
{"status":"ok", "answer":"…带 [cite:n] 的答案…",
 "citations":[{"marker":1,"chunk_id":"…#0062","doc_id":"…","title":"…","section":"…","page":18,
               "text":"(仅 include_contexts=true)"}],
 "n_contexts":5, "model":"deepseek-v4-flash", "finish_reason":"stop|length|…"}
```
`finish_reason=length` = 答案被 max_tokens 截断(尾部引用可能被切)。该值与 `answer` **同轮快照**
(smart-ask 重试被弃用时是第一轮的值,不是被丢弃那轮的);零召回不调 LLM 时为 `null`。

smart-ask(默认开,`PHAROS_SMART_ASK=off` 关;设计见 DESIGN D9):响应另含
`auto: ["table_leg_retry"?]`(自动动作留痕——数值题第一轮拒答时带 kind=table 补检腿重问一轮)与
`hints: [...]`(仅当最终答案仍为拒答/部分拒答时,≤3 条可操作建议;正常答案为空数组)。
smart-ask 属于 `direct` 路径；Agent 路径由自己的证据循环决定是否补检。

当 `mode=agent|auto` 时，响应额外包含：

```json
{
  "route":{"requested_mode":"auto","selected_mode":"direct|agent","reasons":["complex_query"]},
  "trace":[{"step":1,"action":"retrieve","returned":4,"new_evidence":4}],
  "budget":{"steps":4,"retrievals":2,"llm_calls":3,"elapsed_ms":842.1,
            "limits":{"max_steps":10,"max_retrievals":3,"max_llm_calls":4,"timeout_seconds":45}},
  "degraded":false
}
```

`trace` 只记录动作、数量、稳定原因码和补检词，不返回模型思维过程。检索结果先经过同一套 ACL
出口复核，再交给证据判断器；控制器格式错误或暂时不可用时，若已有安全证据则降级到 direct。
若控制器仍判不足但已没有新检索词或检索预算，系统会在剩余 LLM/trace/时间预算允许时用已积累证据
做一次受约束的尽力回答，并在 trace 中记录 `fallback` 与 `best_effort_*`；没有证据时仍明确拒答。

### POST /v1/agent/ask —— 强制 Agentic RAG

请求字段与 `/v1/ask` 相同，但始终按 `mode=agent` 执行（即使请求体传了其他 mode）。这是给前端
“深度检索”按钮和 Agentic RAG 演示保留的明确入口；常规业务建议使用 `/v1/ask` 的 `auto` 模式。

状态机、预算和安全边界见 [AGENTIC_RAG.md](AGENTIC_RAG.md)。

CLI 等价调用：`pharos ask --mode auto "你的问题"`；加 `--json` 可查看完整 route/trace/budget。

### POST /v1/retrieve —— 混合检索(+ small-to-big 上下文)
请求:`{query, top_k?, rerank?=false, doc_ids?, doc_type?, kind?, mode?="full"|"concise",
strategy?="hybrid"|"dense"|"sparse", rerank_top_n?}`
响应:`{status, retriable, hint, warning, meta{requested_k, returned_n, deduped_n, rerank,
rerank_degraded, already_returned_n, budget_truncated, context_tokens, mode, strategy, filters}, hits[]}`;
每条 hit:`{n, doc_id, chunk_id, kind, title, section_path, page_start/end, anchor,
resolved_section, n_tokens, score, score_kind(rrf|cosine|bm25|rerank), context_status, trust, text,
content_raw?(table/chart), image_path?(image/chart,仅定位锚)}`

### GET /v1/documents
`{status, retriable, hint, coverage:{doc_type:篇数}, documents:[{doc_id,title,…}]}`

### POST /v1/documents —— 上传并建库(keys 模式)

`multipart/form-data` 字段:

- `file`:支持 `.md` / `.markdown`(UTF-8)和 `.pdf`,默认上限 10 MiB;
- `access_scope`:`private`(默认)/`restricted`/`tenant`;
- `groups`:逗号分隔;`restricted` 必填,普通 uploader 只能选自己所属 principals;
  `tenant` 内公开仅 admin 可发布。

tenant/owner 只取 `X-API-Key` 解析出的身份，客户端无参数可覆盖。响应 `202`:

```json
{
  "status": "accepted",
  "document_status": "queued",
  "document_id": "upload__...",
  "job_id": "job_...",
  "access_scope": "private"
}
```

客户端应为一次逻辑上传生成 `Idempotency-Key` 请求头（1–128 位字母、数字或 `._:-`），网络超时后
重试时复用同一个值。同一 tenant、同一上传者下，同键同文件及同权限会返回原来的
`document_id/job_id`，并带 `idempotency_replayed=true`，不会重复投递任务；同键但文件或权限不同
返回 `409 idempotency_conflict`。不传该头时保留每次创建新文档的兼容行为。

Markdown 在本地标准化；PDF 使用 MinerU 精准解析 API(`vlm`)提取正文、标题层级、页码、表格和
图片，再进入同一条切块/建库链。PDF 需在服务环境中配置 `MINERU_TOKEN_A`，也可通过
`PHAROS_MINERU_TOKEN_ENV` 改用其他变量名；未配置时 PDF 上传直接返回 `503 mineru_unconfigured`，
不会留下一个注定失败的异步任务。

配置 `PHAROS_DATABASE_URL` 与 `PHAROS_REDIS_URL` 后，任务状态由 PostgreSQL 持久化，Celery Worker
执行解析/切块/建库，Redis 只作消息 broker。API 写入任务和 Outbox 后即返回；Redis 暂时不可用时
`dispatch_delayed=true`，scheduler 会在恢复后补投。瞬态网络/推理故障使用指数退避重试，Worker
失联任务由心跳超时恢复。未配置数据库和 Redis 时，仍可使用 JSON + FastAPI BackgroundTasks
兼容模式，但服务重启不保证续跑。

### GET /v1/jobs/{job_id}

上传者或同 tenant admin 可查;其他身份与不存在统一返回 `404`。响应中:

```json
{"status":"ok", "document_status":"queued|processing|ready|failed",
 "job_status":"queued|running|retrying|succeeded|failed",
 "stage":"uploaded|parsing|mineru_parsing|chunking|embedding|waiting_retry|ready|failed",
 "source_format":"markdown|pdf", "parser_batch_id":"batch-...|null",
 "attempts":1, "max_attempts":3, "chunk_count":12, "error_code":null}
```

PDF 常见失败码：`mineru_unconfigured`、`mineru_upload_failed`、`mineru_parse_failed`、
`mineru_timeout`、`mineru_output_missing`。客户端只看到稳定错误码，具体异常仅进入服务端日志。

### POST /v1/jobs/{job_id}/retry

只有失败任务的上传者或同 tenant admin 可调用。服务会为同一文档创建新的 `job_id`，旧失败任务
继续保留用于审计；响应 `202` 并包含 `previous_job_id`。非失败任务返回 `409 job_not_retryable`。
生产队列与兼容模式都会立刻调度新任务。

可靠任务的完整状态机、重试边界和故障恢复见 [RELIABLE_UPLOAD_JOBS.md](RELIABLE_UPLOAD_JOBS.md)。

### GET /v1/uploads —— 上传管理清单(keys 模式)

这是 PostgreSQL/JSON 管理清单，和 `GET /v1/documents` 的“当前可检索库存”不是同一个接口。
普通用户只看到自己上传的文档；同 tenant admin 可看到全部。它会包含尚未进入 Qdrant 的
`queued/processing/failed` 记录，默认隐藏软删除记录。

查询参数：`include_deleted=false`、`limit=100`（最大 500）、`offset=0`。

### POST /v1/documents/{document_id}/reindex

上传者或同 tenant admin 可从保留的原文件创建新摄取任务，响应 `202 accepted`。旧索引在解析、
切块和编码期间继续可用，到 Embedder 提交新版本时才短暂执行 `delete -> upsert -> sidecar replace`；
旧任务历史继续保存在 PostgreSQL。文档已有活动任务时返回 `409 document_busy`。

### PATCH /v1/documents/{document_id}/access

请求 JSON：

```json
{"access_scope":"restricted", "groups":["g_eng"]}
```

权限规则与上传一致。服务先在数据库创建不可领取的 `held` 任务来独占该文档，再删除旧 Qdrant
points 与 sidecar，最后以新 ACL 激活重建任务。这样权限收紧时不会出现数据库已更新、旧向量仍按
宽权限可检索的窗口。旧索引清理失败则记录 `access_update_failed`，不提交新 ACL；中断的 `held`
任务会由现有 stale recovery 标记失败，之后可重试。
权限修改失败后应重新提交本接口（再次明确目标权限）；通用的 `POST /v1/jobs/{job_id}/retry` 会拒绝
这类任务，避免在目标 ACL 未保存时误用旧 ACL 重建。

### DELETE /v1/documents/{document_id}

上传者或同 tenant admin 可删除。操作同步清理 Qdrant points、sidecar 与本地原文件/解析产物，
数据库文档和任务历史采用软删除保留审计。活动任务期间返回 `409 document_busy`；瞬态清理失败时
记录 `delete_failed` 并返回可重试的 `503`，重复 DELETE 会继续执行幂等清理。默认管理清单不再
显示已删除文档，`GET /v1/uploads?include_deleted=true` 可查看。

生命周期设计与一致性边界见 [DOCUMENT_LIFECYCLE.md](DOCUMENT_LIFECYCLE.md)。

### GET /v1/documents/{doc_id}?max_tokens=6000
通读整篇(逐元素 ACL 门控):`{status, doc_id, text, n_tokens, n_elements_visible, truncated, trust, warning}`

### GET /v1/documents/{doc_id}/outline
`{status, doc_id, sections:[…]}`

### POST /v1/expand
请求:`{chunk_id, target_tokens?=1500}` → `{status, chunk_id, text, anchor, resolved_section, n_tokens, climbed, trust, warning}`

### POST /v1/retrieve_grouped
请求:`{query, doc_ids(≤20), top_k?=3, rerank?=false}` → `{status, warning, groups:{doc_id:[hits]}}`

## MCP 工具 ↔ 端点对照

| MCP 工具(pharos mcp) | HTTP 端点 |
|---|---|
| retrieve | POST /v1/retrieve |
| list_documents | GET /v1/documents |
| get_document | GET /v1/documents/{doc_id} |
| get_outline | GET /v1/documents/{doc_id}/outline |
| expand | POST /v1/expand |
| retrieve_grouped | POST /v1/retrieve_grouped |

(MCP 侧无 ask:agentic 模式下答案由 agent 自己合成。)
