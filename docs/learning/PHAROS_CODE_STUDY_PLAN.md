# PharosRAG 代码学习计划（唯一进度源）

> 作用：固定学习顺序、记录完成情况，并让后续对话在上下文压缩后仍能准确续学。
>
> 学习原则：每次只学习一课；先读对应教学文档，再沿真实代码执行链阅读，最后做实验和小结。实验默认执行；学习者明确选择跳过时，必须在进度和小结中如实记录，不伪造实验结果。

## 0. 当前进度

- 当前阶段：阶段四——服务化与 Agentic RAG
- 当前课程：`L11 身份认证、ACL 与会话隔离（待开始）`
- 下一步：阅读 `docs/learning/04-acl-security.md`，再沿身份认证、ACL 下推和会话隔离跟踪一次请求
- 最近更新：2026-09-20
- 当前环境：Apple Silicon Mac + Docker Compose + Qdrant + 阿里云 Embedding/Rerank + DeepSeek
- 当前知识库：37 篇固定版本官方技术文档
- 当前验证：`/readyz`、`/v1/retrieve`、`/v1/ask` 和内置 Agentic RAG 已完成真实服务验证；文档生命周期完成 Docker 实测；2026-09-20 本地全量回归为 350 passed、12 skipped，前端 lint/build 通过

### 学习进度与开发进度不是一回事

- `L01`：主体已学，独立复述与书面小结待补。
- `L02`：已完成配置、装配、核心数据结构和数据变化图的学习。
- `L03`：已完成文档下载、Markdown/MinerU 解析路径、统一 Element 接缝和 metadata 学习。
- `L04`：已完成标题树、结构化切块、资产块、元数据盖章与查询期 small-to-big 学习和实验。
- `L05`：已完成 Embedding、Sparse、Point 构造、Qdrant Collection 与写入链路；隔离建库实验按学习者选择跳过。
- `L06`：已完成 Dense、Sparse、Hybrid、ACL 下推与 RRF 融合的代码和原理学习；对比实验按学习者选择跳过。
- `L07`：已完成候选池、Rerank、section 去重、Sidecar 缓存与 small-to-big 上下文扩展；接口对比实验按学习者选择跳过。
- `L08`：已完成 Prompt 组装、Grounding、防提示注入、引用解析、LLM 协议与 MockLLM 学习。
- `L09`：已完成 FastAPI 应用工厂、中间件、健康探针、错误契约和可观测性学习；接口实验因 Docker 已关闭而跳过。
- `L10`：已完成镜像与容器、Compose 网络、数据挂载、在线推理适配器、启动依赖和服务生命周期学习；故障与 reload 实验因 Docker 已关闭而跳过。
- 文档上传、可靠异步任务和文档生命周期已经实现并合入 `main`，但安排到 `L14–L16` 再系统学习。
- “代码已实现”只表示功能和测试完成；学习掌握情况以对应阅读、复述和记录为准，实验若明确跳过须单独注明。

### 已完成的准备工作

- [x] 拉取并了解 PharosRAG 项目定位
- [x] 安装 Docker Desktop
- [x] 跑通三个容器：`pharos`、`qdrant`、`cloud-inference`
- [x] 配置阿里云 Embedding 与 Rerank
- [x] 配置 DeepSeek 生成模型
- [x] 导入 FastAPI、Docker、Qdrant 共 10 篇官方文档
- [x] 完成第一次带引用的知识库问答
- [x] 开始按代码调用链系统学习
- [x] 增加 Markdown/PDF 上传与 MinerU 解析
- [x] 增加 PostgreSQL + Redis + Celery 可靠异步入库
- [x] 增加文档列表、重建索引、权限变更和软删除
- [x] 完成全量自动化测试与真实 Docker 生命周期验证

## 1. 固定学习方法

每一课都严格执行下面六步：

1. **先提问题**：这一层解决什么问题，不做会怎样？
2. **阅读文档**：只读本课列出的章节，不提前扩散。
3. **跟踪代码**：找到入口、核心函数、输入、输出和外部依赖。
4. **运行实验**：改变一个变量，观察日志或返回结果。
5. **自己复述**：不看文档，用自己的话讲清执行流程和设计理由。
6. **留下证据**：完成检查项，并在本文末尾追加学习记录。

每个模块必须能回答：

- 输入是什么？
- 输出是什么？
- 核心类和函数在哪里？
- 调用了哪个外部组件？
- 当前方案为什么这样设计？
- 失败时如何处理或降级？

## 2. 总体路线

```text
阶段一：先看懂一条完整问答
  L01 请求全链路 → L02 核心数据结构与装配

阶段二：索引侧——文档怎样进入知识库
  L03 文档导入 → L04 结构化切块 → L05 Embedding 与 Qdrant 建库

阶段三：查询侧——答案怎样产生
  L06 混合检索 → L07 Rerank 与上下文扩展 → L08 生成、Grounding 与引用

阶段四：服务、安全与 Agent
  L09 FastAPI 服务 → L10 Docker 与在线推理 → L11 身份、ACL 与会话
  → L12 MCP 工具面 → L13 有限步 Agentic RAG

阶段五：个人新增能力与项目收口
  L14 上传入口与解析 Pipeline → L15 PostgreSQL/Redis/Celery 异步任务
  → L16 文档生命周期与并发一致性 → L17 Next.js 前端与 BFF
  → L18 测试与 Agent 评测 → L19 可靠性、扩容与部署
  → L20 Git 溯源、简历与面试复盘
```

课程以“课”为单位，不按自然日强制推进。建议每课 60–120 分钟，每天最多两课。

---

## 阶段一：建立系统地图

### L01 一次 `/v1/ask` 请求的完整生命周期

**目标**：能画出你刚才那次 Docker 问答经过的全部核心组件。

**先读**：

- `docs/learning/01-rag-overview.md`：第 1、2 节

**按顺序看代码**：

1. `src/pharos/service.py`：`create_app()`、`ask()`
2. `src/pharos/engine.py`：`build_retriever()`、`build_generator()`
3. `src/generator/generate.py`：`Generator.answer()`
4. `src/embedder/retrieve.py`：`Retriever.search()`、`search_with_context()`
5. `src/embedder/store.py`：`hybrid_search()`

**实验**：

- 一个终端观察 `pharos` 和 `cloud-inference` 日志。
- 另一个终端分别调用 `/v1/retrieve` 和 `/v1/ask`。
- 对比二者：哪一步只在 `/v1/ask` 中出现？

**完成标准**：

- [ ] 能独立画出请求链路图
- [ ] 能解释 `/v1/retrieve` 和 `/v1/ask` 的区别
- [ ] 能指出 Embedding、Qdrant、Rerank、DeepSeek 分别在哪里参与
- [ ] 写出 150–300 字本课小结

### L02 配置、装配与核心数据结构

**目标**：理解代码为什么能替换本地模型、在线模型、假对象和真实 Qdrant。

**先读**：

- `docs/learning/01-rag-overview.md`：第 2、3 节
- `docs/learning/08-service-architecture.md`：装配与依赖部分

**看代码**：

- `src/pharos/config.py`
- `src/pharos/engine.py`
- `src/chunker/types.py`
- `src/embedder/types.py`
- `src/generator/types.py`

**实验**：

- 找出 `.env.mac` 中的配置如何进入 `PharosConfig`。
- 画出 `Element → Chunk → Hit/Context → Answer/Citation` 的数据变化。

**完成标准**：

- [x] 能解释依赖注入在本项目中的作用
- [x] 能区分 `Element`、`Chunk`、检索命中和 `Citation`
- [x] 能说明为什么测试不必真的调用云模型
- [x] 完成本课小结

---

## 阶段二：索引侧——文档怎样进入知识库

### L03 文档下载、解析与标准化

**目标**：理解原始文档如何变成 Chunker 可以消费的统一结构。

**先读**：

- `docs/learning/02-parsing-chunking.md`：解析和 Element 部分
- `docs/MAC_DOCKER_DEV.md`：第 4 节

**看代码和数据**：

- `config/official_tech_docs.json`
- `src/pharos/markdown_ingest.py`
- `src/chunker/adapters/mineru.py`
- `data/parsed/docker__volumes/source.md`
- `data/parsed/docker__volumes/docker__volumes_content_list.json`

**实验**：

- 选择一个很短的 Markdown 文件，加入标题、正文、列表和代码块。
- 调用 `markdown_to_content_list()`，观察四种内容变成了哪些 Element。

**完成标准**：

- [x] 能解释为什么要有统一 Element 层
- [x] 能说明 Markdown 导入和 MinerU 导入在哪里汇合
- [x] 能解释 `metadata.json` 的作用
- [x] 完成本课小结

### L04 标题树、切块与 small-to-big 的索引基础

**目标**：理解为什么不能按固定字符数粗暴切文档。

**先读**：

- `docs/learning/02-parsing-chunking.md`：切块、标题树、动手实验

**看代码**：

- `src/chunker/core.py`：`Chunker.chunk()`
- `src/chunker/retrieve.py`
- `src/chunker/types.py`：`Section`、`Chunk`、`BigBlock`

**实验**：

- 用测试数据构造两级标题和多个段落。
- 运行 Chunker，打印每个 chunk 的 `section_path`、`source_indices` 和 token 数。
- 改变段落长度，观察 chunk 边界变化。

**完成标准**：

- [x] 能解释标题树如何保留文档结构
- [x] 能解释“小块用于检索，大块用于生成”
- [x] 能说出固定长度切块的两个问题
- [x] 完成本课小结

### L05 Embedding、稀疏向量与 Qdrant 建库

**目标**：理解一个 Chunk 怎样成为 Qdrant 中可搜索的 point。

**先读**：

- `docs/learning/03-retrieval.md`：Dense、Sparse、索引部分

**看代码**：

- `src/pharos/indexer.py`
- `src/embedder/embed.py`
- `src/embedder/dense.py`
- `src/embedder/sparse.py`
- `src/embedder/store.py`
- `src/embedder/remote.py`

**实验**：

- 只保留一篇小文档，建一个实验 collection。
- 查看文档产生的 chunk 数。
- 确认普通文本 point 同时包含 dense、sparse 和 payload；`image_only` point 只有图片 dense 和 payload。

**注意**：不要直接清空当前 `tech_docs`；实验应使用新 collection。

**完成标准**：

- [x] 能解释 Embedding 的输入与 1024 维输出
- [x] 能解释 sparse 向量保存了什么
- [x] 能说清 Qdrant point 的 vector 与 payload
- [x] 能解释为什么建库和查询必须使用同一个 Embedding 模型
- [x] 完成本课小结

---

## 阶段三：查询侧——答案怎样产生

### L06 Dense、Sparse、Hybrid 与 RRF

**目标**：理解混合检索为什么比只用向量更稳。

**先读**：

- `docs/learning/03-retrieval.md`：混合召回、RRF、动手实验

**看代码**：

- `src/embedder/retrieve.py`：`search()`
- `src/embedder/store.py`：`hybrid_search()`
- `src/embedder/acl.py`：只观察过滤如何传入，暂不深挖安全模型

**实验**：

对相同问题分别设置：

- `strategy=dense`
- `strategy=sparse`
- `strategy=hybrid`

至少测试两类问题：概念语义问题、包含精确命令或术语的问题。记录前三名差异。

**完成标准**：

- [x] 能解释 Dense 和 Sparse 各自擅长什么
- [x] 能用自己的话解释 RRF，不背公式也能讲明白
- [x] 能根据问题类型预测哪条检索路线更有优势
- [x] 完成本课小结和对比表

### L07 Rerank、去重与 small-to-big

**目标**：理解“召回”和“最终交给模型的上下文”不是同一份数据。

**先读**：

- `docs/learning/03-retrieval.md`：Rerank 部分
- `docs/learning/02-parsing-chunking.md`：small-to-big 部分

**看代码**：

- `src/embedder/retrieve.py`：`search_with_context()`、`_assemble()`
- `src/embedder/rerank.py`
- `src/chunker/retrieve.py`：`assemble_big()`

**实验**：

- 对同一问题比较 `rerank=false` 和 `rerank=true`。
- 对一个命中的 `chunk_id` 调用 `/v1/expand`。
- 比较命中小块和扩展上下文。

**完成标准**：

- [x] 能解释召回候选池与 top-k 的区别
- [x] 能解释 Rerank 为什么更准但更慢
- [x] 能解释 section 去重与上下文扩展
- [x] 完成本课小结

### L08 Prompt、Grounding 与引用

**目标**：理解模型为什么尽量只根据知识库作答，以及引用如何回指原文。

**先读**：

- `docs/learning/05-generation-grounding.md`

**看代码**：

- `src/generator/generate.py`
- `src/generator/prompt.py`
- `src/generator/llm.py`
- `src/generator/types.py`

**实验**：

- 问一个库内存在的问题，再问一个明显不存在的问题。
- 查看两次返回的 `answer`、`citations`、`n_contexts`。
- 阅读 PromptBuilder 最终发给模型的 system/user messages。

**完成标准**：

- [x] 能解释零召回时为什么不应该让 LLM 自由回答
- [x] 能解释 `[cite:n]` 到 Citation 对象的映射
- [x] 能说出至少两种幻觉或提示注入防线
- [x] 完成本课小结

---

## 阶段四：服务化与 Agentic RAG

### L09 FastAPI 服务、错误契约和可观测性

**目标**：从一个 RAG 函数上升到可运行的后端服务。

**先读**：

- `docs/learning/08-service-architecture.md`
- `docs/API.md`

**看代码**：

- `src/pharos/service.py`
- `src/pharos/obs.py`
- `src/pharos/cli.py`

**实验**：

- 分别触发：无 API Key、空 query、正常 query、无匹配结果。
- 记录 HTTP 状态和业务 `status` 的区别。
- 查看 `/healthz`、`/readyz` 和 `/v1/stats`。

**完成标准**：

- [x] 能解释 liveness 和 readiness 的区别
- [x] 能解释为什么部分业务失败仍返回结构化 JSON
- [x] 能找到请求耗时和错误统计的位置
- [x] 完成本课小结

### L10 Docker 与在线推理适配器

**目标**：理解三层核心 RAG（Pharos、Qdrant、在线推理适配器）以及 PostgreSQL、Redis、Worker 等配套服务的职责和网络调用，而不是只会启动命令。

**先读**：

- `docs/MAC_DOCKER_DEV.md`：第 1、3、6 节
- `docs/learning/09-scale-out.md`：只读三层拆分部分

**看配置和代码**：

- `compose.mac.yml`
- `Dockerfile.pharos`
- `Dockerfile.cloud-inference`
- `src/cloud_inference/service.py`
- `src/embedder/remote.py`

**实验**：

- 画出当前 Compose 服务、两个云 API 和端口之间的连接图。
- 单独停止 `cloud-inference`，观察 `/readyz` 与检索如何变化，然后恢复。
- 修改一条无关紧要的日志文字，观察自动 reload。

**完成标准**：

- [x] 能解释容器与镜像的区别
- [x] 能解释 bind mount 和 named volume 在本项目中分别保存什么
- [x] 能解释为什么 `pharos` 容器不需要 GPU/torch
- [x] 完成本课小结

### L11 身份认证、ACL 与会话隔离

**目标**：沿真实代码区分“你是谁”“你能看什么”“同一会话看过什么”，理解项目最重要的安全边界。

**已有材料**：

- `docs/learning/04-acl-security.md`
- `src/pharos/identity.py`：API Key 到 `Identity` 的解析与配置校验。
- `src/pharos/service.py`：鉴权 middleware、`request.state.identity` 和 `_current_user()`。
- `src/embedder/types.py`、`src/embedder/acl.py`：检索用户和 fail-closed ACL 判定。
- `src/embedder/store.py`：ACL 如何下推到 Dense/Sparse 召回过滤器。
- `src/pharos/sessions.py`：有界 LRU 会话去重集合。
- `tests/engine/test_acl.py`、`tests/test_sessions.py`、`tests/test_team.py`：安全不变量的现成测试。

**按顺序学习**：

1. `load_keys()` 如何把密钥解析为 tenant、principals、roles 和 admin。
2. middleware 如何拒绝错误密钥，并把身份放入单次请求。
3. `acl_admits()` 如何默认拒绝，Qdrant 召回时又如何提前过滤。
4. 同一个伪造 session id 为什么不能让两个用户共享去重状态。
5. 对照测试确认“无身份、跨租户、空 allow”均不会意外放行。

**实验**：

- Docker 关闭时先运行 ACL、Session 和身份单测，并手工画出 `API Key → Identity → User → Qdrant Filter`。
- Docker 恢复后再补双身份实测：私有文档只允许拥有者检索，其他身份得到空结果而不是暴露文档存在性。

**完成标准**：

- [ ] 能区分 authentication、authorization 和 session state
- [ ] 能解释 ACL 为什么既要下推检索，又要在出口复核
- [ ] 能解释 fail-closed，以及空 ACL/无身份为何不能默认放行
- [ ] 能说明会话去重为什么必须绑定身份
- [ ] 完成本课小结

### L12 MCP 工具面与两种调用出口

**目标**：先学清 MCP 只是把检索能力暴露给外部 Agent 的工具协议，不把“接入 MCP”误认为项目内部已经完成规划。

**已有材料**：

- `docs/learning/06-agentic-mcp.md`
- `docs/components/mcp-server.md`
- `src/pharos/toolcore.py`：六个工具共享的业务语义。
- `src/pharos/mcp_adapter.py`：通过 HTTP 调用正在运行的 FastAPI。
- `src/pharos/mcp_stdio.py`：同进程 direct 模式，直接装配 Retriever。
- `.mcp.json.example`
- `tests/engine/test_tools.py`、`tests/test_adapter.py`、`tests/test_review_fixes.py`

**按顺序学习**：

1. 六个工具：`retrieve`、`list_documents`、`get_document`、`get_outline`、`expand`、`retrieve_grouped`。
2. 为什么工具语义只放在 `toolcore.py`，HTTP 与 direct 出口只负责适配。
3. HTTP adapter 如何转发 API Key、Session 和过滤参数，并把后端错误变成稳定结构。
4. direct stdio 如何绑定服务端身份，以及它与守护进程模式的部署差异。
5. MCP 客户端负责决定调用顺序，Pharos 只执行受约束的工具。

**实验**：

- 先运行工具与适配器单测，比较同一工具经 `mcp_adapter` 和 `mcp_stdio` 的输入输出契约。
- Docker 恢复后再做一次真实 MCP 调用：`list_documents → get_outline → retrieve → expand`。

**完成标准**：

- [ ] 能说出六个 MCP 工具各自的输入、输出和适用时机
- [ ] 能解释 HTTP adapter、direct stdio 和 `toolcore` 的职责边界
- [ ] 能解释 MCP 为什么只是 Agentic RAG 的工具层
- [ ] 能说明身份、超时和错误如何穿过适配层
- [ ] 完成本课小结

### L13 内置有限步 Agentic RAG 状态机

**目标**：学习当前项目已经实现的 `direct / auto / agent` 三种路线，而不是再把 Agentic RAG 写成未来计划。

**已有材料**：

- `docs/AGENTIC_RAG.md`
- `src/pharos/agentic.py`：路由、证据判断、补检、预算和 trace。
- `src/pharos/service.py`：`_agentic_ask()`、`/v1/ask` 与 `/v1/agent/ask`。
- `src/generator/generate.py`：复用 ACL 后 Context 和最终 Grounded 生成。
- `src/rag_runtime/deadline.py`：请求截止时间和阻塞调用容量控制。
- `tests/test_agentic.py`、`tests/test_runtime_deadlines.py`、`tests/test_eval_agent_benchmark.py`

**按顺序学习**：

1. `requires_agent()` 和 auto 路由为什么只是低成本启发式。
2. `EvidenceController` 如何只返回受校验 JSON，不负责最终回答。
3. `AgenticRunner.run()` 如何执行“检索 → 判断 → 改写 query → 补检 → 合并证据 → 回答”。
4. 最大检索次数、LLM 次数、步骤数、deadline 和线程槽位分别限制什么。
5. 控制器异常、超时、零召回和预算耗尽时如何降级或拒答。
6. trace 为什么是行为审计，不是暴露模型 chain-of-thought。

**实验**：

- 运行 Agent 状态机和 deadline 单测，挑选“证据充足、补检成功、控制器异常、超时”四条 trace 逐步解释。
- Docker 恢复后，再用同一问题比较 direct、auto、agent 的检索次数、延迟、引用和停止原因。

**完成标准**：

- [ ] 能画出有限步 Agent 状态机
- [ ] 能解释 query 改写与再次检索在什么条件下发生
- [ ] 能区分 MCP 外部 Agent 与项目内置 Agentic Runner
- [ ] 能解释预算、deadline、降级和 trace
- [ ] 完成本课小结

---

## 阶段五：把项目变成自己的

### L14 上传入口、格式解析与入库 Pipeline

**目标**：先理解“一份 Markdown/PDF 怎样变成可供异步任务处理的标准入库流程”，暂时不深入 PostgreSQL 和 Celery 的可靠投递。

**已有材料**：

- `docs/API.md`：上传与任务接口。
- `src/pharos/service.py`：`upload_document()` 入口和权限检查。
- `src/pharos/uploads.py`：`build_upload_acl()`、`DocumentUploadManager.create()`。
- `src/pharos/markdown_ingest.py`：Markdown/RST 到 `content_list`。
- `src/pharos/mineru.py`、`src/pharos/ingestion/factory.py`：PDF 上传、轮询、下载和安全解压。
- `src/pharos/ingestion/pipeline.py`：解析、Chunk、Embedding、Qdrant 与 Sidecar 发布。
- `tests/test_markdown_ingest.py`、`tests/test_mineru.py`、`tests/test_uploads.py`

**按顺序学习**：

1. 上传角色、access scope、groups 如何被校验并生成 ACL。
2. 文件大小、扩展名、文件名和落盘目录怎样限制危险输入。
3. Markdown 与 PDF 两条解析路径怎样重新汇合到 `Element[]/ChunkResult`。
4. Pipeline 各 stage：解析、切块、编码、发布、清理临时产物。
5. 为什么上传 API 只创建文档和任务，而不在 HTTP 请求里完成耗时入库。

**实验**：

- 运行 Markdown、MinerU 和上传校验测试；用一份极小 Markdown 手工跟踪生成的 `content_list`、Chunk 和最终 document id。
- PDF 在线实测留到 Docker 与 MinerU 均启动时执行，未启动时不阻塞代码学习。

**完成标准**：

- [ ] 能解释上传入口如何生成文档身份和 ACL
- [ ] 能画出 Markdown/PDF 两条解析路径的汇合点
- [ ] 能说出 Pipeline 的阶段、正式产物和临时产物
- [ ] 能解释为什么上传不能长期占用一次 HTTP 请求
- [ ] 完成本课小结

### L15 PostgreSQL、Outbox、Redis 与 Celery 可靠任务

**目标**：聚焦任务可靠性，理解 PostgreSQL 为什么是事实源，以及 Outbox、Redis、Celery Worker 和 Scheduler 如何协作。

**先读**：

- `docs/RELIABLE_UPLOAD_JOBS.md`
- `migrations/versions/0001_reliable_upload_jobs.py`

**按执行顺序看代码**：

1. `src/pharos/jobs/models.py`：Document、IngestionJob、Outbox 三张表。
2. `src/pharos/jobs/repository.py`：只读 `create/claim/heartbeat/retry/recover/outbox` 相关方法，不通读全部 996 行。
3. `src/pharos/jobs/dispatcher.py`：先抢占 Outbox 发布权，再投递 Celery。
4. `src/pharos/worker/celery_app.py`：ingestion/control 两个队列和 Beat 周期任务。
5. `src/pharos/worker/tasks.py`：Worker 执行、心跳、待投递扫描和失联恢复。
6. `src/pharos/worker/runtime.py`：Worker 进程怎样装配 Repository、Pipeline 和 Dispatcher。
7. `tests/test_jobs.py`、`tests/test_worker_tasks.py`、`tests/test_celery_config.py`。

**实验**：

- 先运行 jobs、worker 和 Celery 配置测试，跟踪一条任务从 `queued → running → succeeded`。
- 用状态表推演三种故障：数据库提交后 Redis 不可用、消息已发但确认丢失、Worker 运行中失联。
- Docker 恢复后再做暂停 Worker 的真实实验，观察 PostgreSQL、Outbox 和恢复任务的变化。

**完成标准**：

- [ ] 能画出 `API → PostgreSQL/Outbox → Redis → Celery Worker → MinerU → Qdrant` 链路
- [ ] 能解释为什么任务状态不能只放 Redis
- [ ] 能解释 Outbox 解决的“双写一致性”问题
- [ ] 能说明认领、心跳、退避重试和定时恢复分别防什么故障
- [ ] 能解释 at-least-once 为什么仍然要求任务幂等
- [ ] 完成本课小结

### L16 文档生命周期、ACL 变更与并发一致性

**目标**：理解文档从上传到重建、改权限和删除的完整状态机，以及为什么这部分已经不再只是 Demo 逻辑。

**先读**：

- `docs/DOCUMENT_LIFECYCLE.md`
- `docs/RELIABILITY_FIXES_2026-09-19.md`：只读 publication fencing 部分。
- `docs/API.md`：`/v1/uploads`、`reindex`、`access` 和删除接口

**按场景看代码**：

1. `src/pharos/service.py`：列表、重建、权限变更和删除 API 的权限与错误契约。
2. `src/pharos/uploads.py`：`reindex_document/update_access/delete_document` 编排。
3. `src/pharos/jobs/repository.py`：prepare/activate/fail access update、软删除、恢复和固定锁顺序。
4. `src/pharos/ingestion/pipeline.py`：`publish_guard` 内删除旧索引、写新向量和替换 Sidecar。
5. `tests/test_uploads.py`、`tests/test_jobs.py`、`tests/test_publication_fencing.py`：状态机、并发与旧 Worker 复活回归。

**实验**：

- 先运行生命周期、jobs 和 publication fencing 测试，画出 document state 与 job state 两条相关但不同的状态机。
- 根据真实修复记录复述 PostgreSQL 死锁的两条锁路径，以及统一 `job → outbox` 锁顺序为什么能解决问题。
- 推演“旧 Worker 超时后复活”的场景，解释租约和 `publish_guard` 为什么必须覆盖正式发布区。
- Docker 恢复后再对一份临时文档完整执行：列表、重建、收紧 ACL、软删除。

**完成标准**：

- [ ] 能区分 Qdrant 可检索库存 `/v1/documents` 与数据库管理库存 `/v1/uploads`
- [ ] 能解释为什么 ACL 更新先进入 held 状态，再删除旧索引并发布新任务
- [ ] 能解释软删除为何保留数据库审计记录，但删除向量和本地资产
- [ ] 能解释 `job → outbox` 统一锁顺序如何避免死锁
- [ ] 能解释旧 Worker 为什么不能在失去租约后覆盖新索引
- [ ] 完成本课小结和一张文档状态机图

### L17 Next.js 前端、BFF 与权限展示

**目标**：学习已经存在的完整前端，理解浏览器为什么不直接保存或发送后端密钥，以及 UI 如何承接问答、上传、生命周期和 Agent trace。

**已有材料**：

- `frontend/README.md`
- `frontend/src/app/page.tsx`：页面状态和主要交互。
- `frontend/src/app/api/session/route.ts`：登录验证和 HttpOnly Cookie。
- `frontend/src/app/api/ask/route.ts`、`retrieve/route.ts`、`expand/route.ts`：问答代理。
- `frontend/src/app/api/uploads/route.ts`、`documents/**`、`jobs/**`：上传和管理代理。
- `frontend/src/lib/pharos.ts`：统一后端请求、错误映射和 Cookie 取 key。
- `frontend/src/components/agent-trace.tsx`：Agent 路由、步骤和预算展示。
- `frontend/scripts/smoke.mjs`、`two-user-smoke.mjs`、`pdf-smoke.mjs`：真实联调脚本。

**按顺序学习**：

1. 浏览器 → Next.js Route Handler → FastAPI 的 BFF 链路。
2. API Key 为什么进入 HttpOnly Cookie，而不是 localStorage 或 `NEXT_PUBLIC_*`。
3. `/v1/me` 返回的角色如何控制按钮显示，但真正授权仍由 FastAPI 执行。
4. direct/auto/agent 的结果、引用、空答案、降级和 trace 如何映射成 UI 状态。
5. 上传任务轮询、失败重试、ACL 修改、重建和删除如何复用统一错误结构。

**实验**：

- 在不启动后端时先阅读路由和运行 `npm run lint`、`npm run build`。
- Docker 恢复后按顺序运行基础 smoke、双身份 smoke；MinerU PDF smoke 单独执行并记录外部调用。

**完成标准**：

- [ ] 能解释 BFF、HttpOnly Cookie 和 FastAPI 权限校验的分工
- [ ] 能从一个按钮追到对应 Route Handler 和后端 API
- [ ] 能解释 Agent trace、引用和任务状态的前端数据结构
- [ ] 能说明“隐藏按钮”为什么不等于安全授权
- [ ] 完成本课小结

### L18 自动化测试、Golden Set 与 Agent 配对评测

**目标**：把“测试代码是否符合契约”和“评测 RAG 答得是否更好”分开，学会正确解释现有指标和局限。

**已有材料**：

- `docs/learning/07-evaluation.md`、`docs/TESTING.md`
- `eval/README.md`、`eval/BASELINE.md`
- `eval/official_agent_smoke.json`、`eval/official_agent_gold.json`、`eval/official_agent_gold_v2.json`
- `eval/agent_benchmark.py`、`eval/run_eval.py`、`eval/aggregate.py`
- `eval/GOLD_REVIEW_2026-09-19.md`、`eval/GOLD_V2_AI_SOURCE_REVIEW_2026-09-19.md`
- `tests/test_eval_agent_benchmark.py`、`tests/test_eval_service_smoke.py`

**按顺序学习**：

1. 单元测试、契约测试、集成测试、smoke 和离线/在线评测分别证明什么。
2. 检索 Recall@K、MRR、引用来源组召回、答案正确性、忠实度和拒答率。
3. 同一题成对运行 direct/agent/auto，为什么比只展示 Agent 成功案例更可信。
4. Golden Set 的题型、必需事实、允许来源和人工审核记录怎样组织。
5. 同厂模型裁判、样本量小、单次运行和答案截断为什么限制结论外推。

**实验**：

- 不调用付费模型：先运行评测脚本自身的单测，并人工检查至少 5 道题的题目、必需事实和引用来源。
- 选一份已有 benchmark report，手算一题的正确性/引用/成本字段，核对聚合结果。
- 需要新指标时再复跑固定版本考卷；不要为了学习重复产生云模型费用。

**完成标准**：

- [ ] 能区分自动化测试通过与 RAG 效果好
- [ ] 能解释 Recall、MRR、正确性、忠实度、引用正确性和正确拒答
- [ ] 能读懂一条 gold case 和一条 benchmark result
- [ ] 能指出当前基线至少三项局限，避免把开发基线写成最终结论
- [ ] 完成本课小结

### L19 可靠性边界、扩容与部署运维

**目标**：学习项目里已经落地的超时、发布保护、代理安全、备份恢复和横向扩容设计，不再笼统写“以后补工程化”。

**已有材料**：

- `docs/RELIABILITY_FIXES_2026-09-19.md`
- `docs/OPERATIONS.md`、`docs/RUNBOOK.md`、`docs/SCALE_OUT.md`
- `compose.mac.yml`、`deploy/nginx.conf`
- `src/rag_runtime/deadline.py`、`src/pharos/obs.py`
- `src/embedder/remote.py`、`src/generator/llm.py`：剩余时间如何传入网络调用。
- `src/pharos/ingestion/pipeline.py`、`src/pharos/jobs/repository.py`：发布围栏。
- `tests/test_runtime_deadlines.py`、`tests/test_proxy_safety.py`、`tests/test_publication_fencing.py`

**按顺序学习**：

1. Agent 绝对 deadline、网络 timeout、线程槽位和“超时不能杀死 Python 线程”的边界。
2. publication fencing 如何阻止失去租约的 Worker 覆盖正式索引。
3. Nginx 为什么只安全重试幂等请求，写请求为何禁止自动重放。
4. 多副本下哪些状态已经外置，哪些本地文件仍限制真正水平扩容。
5. named volume、备份/恢复、RTO/RPO、密钥和 HTTPS 的部署要求。
6. 结构化日志、健康探针和 P50/P95 如何用于容量判断。

**实验**：

- 运行 deadline、代理配置和 publication fencing 回归测试。
- 阅读现有备份恢复记录，写出“已经实测 / 仅推算 / 尚未验证”三列证据表。
- Docker 恢复后做一次从空环境启动和数据重启保留检查；不重复破坏性故障演练现有正式数据。

**完成标准**：

- [ ] 能解释 timeout、deadline、取消和远端计费不是一回事
- [ ] 能解释为什么写请求不能由代理透明重放
- [ ] 能说清当前多副本扩容的可行部分和本地状态限制
- [ ] 能根据证据区分已验证能力和设计目标
- [ ] 完成本课小结

### L20 Git 溯源、项目归属、简历与面试复盘

**目标**：最后再用 Git 和文档划清上游能力、个人提交和当前未提交改动，把已经学懂的系统转换为可核验的项目陈述。

**已有材料**：

- `docs/PROVENANCE.md`
- `docs/learning/10-methodology-stories.md`
- `docs/learning/11-interview-qa.md`
- `README.md`、`docs/assets/architecture.svg`
- Git 里程碑：`162c7ca` 上游基线、`0995802` 上传、`6e01f28` Mac 在线推理、`9f787cc..cd6629d` 可靠任务、`f0cb7ba` 生命周期、`a28829a..5414a51` Agent 与评测；本轮新增 `83c243e` 发布围栏、`61cc214` Agent deadline、`d4a1d35` V2 题库和 `576a115` Web UI。
- 当前分支已将前端、可靠性修复、Agent 截止时间和 V2 评测题库拆成独立提交；合并前仍需完成真实 V2 在线评测与最终人工签收。

**按顺序学习**：

1. 用 `git diff`/`git log` 比较每个里程碑，建立“上游已有 / 个人新增 / 未完成”对照表。
2. 从上传、Agentic RAG、ACL/并发修复中各选一个，讲清问题、方案、权衡、测试和结果。
3. 把架构图中的每个组件与真实文件、接口和数据存储对应起来。
4. 检查 README、评测数字和截图，只保留能够由日志、测试或报告复现的说法。
5. 准备 30 秒、3 分钟、15 分钟三个粒度的项目介绍。

**最终产出**：

- [ ] 一张自己能从请求入口讲到存储与云服务的系统架构图
- [ ] 一张“上游已有 / 个人新增 / 当前限制”归属表
- [ ] README 中的运行方式、测试、指标和截图与当前代码一致
- [ ] 3 个有真实提交和测试证据的个人改造故事
- [ ] 1 个真实故障排查故事和 1 个明确的负面/局限结论
- [ ] 30 秒、3 分钟、15 分钟三档项目介绍
- [ ] 简历中的每个技术点和数字都有文件、提交或报告可追溯
- [ ] 完成最终模拟面试复盘

---

## 3. 暂时不要做的事

在完成 L08 前，不要同时展开以下内容：

- 不要逐行阅读所有注释和全部测试。
- 不要先研究多副本扩容、Nginx 或 Kubernetes。
- 不要频繁更换模型来比较“哪个最好”。
- 不要直接开始写大型前端。
- 不要把原作者生产环境的 77 篇文档和评估数字当成自己的成果。

先掌握索引侧、查询侧和生成侧三条主线，再学习外围工程能力。

## 4. 每课学习记录模板

每完成一课，在本节末尾追加一条记录：

```markdown
### YYYY-MM-DD · Lxx 课程名

- 状态：完成 / 进行中 / 需要复习
- 我理解的执行链：
- 最重要的三个知识点：
  1.
  2.
  3.
- 做过的实验及结果：
- 仍不明白的问题：
- 修改过的文件：
- 下一课：
```

### 学习记录

#### 2026-09-13 · L03 文档下载、解析与标准化

- 状态：完成。
- 已掌握：统一 `Element` 接缝，以及 Markdown 与 MinerU 两条输入路径如何汇合。
- 本课执行链：`原始文档 → Markdown/RST 轻量标准化或 MinerU 解析 → content_list.json → from_mineru() → Element[] → Chunker`。
- 本课小结：`content_list.json` 保存解析后的内容单元，`metadata.json` 保存文档身份与来源信息；两条解析路径最终都输出 `Element[]`，使后续 Chunker 不必关心原文件格式。
- 下一课：L04 标题树、切块与 small-to-big 的索引基础。

#### 2026-09-13 · L04 标题树、切块与 small-to-big 的索引基础

- 状态：完成。
- 本课主线：`Element[] → 噪声过滤 → 标题与面包屑 → 小 Chunk → Section 树与元数据 → ChunkResult`；查询时再把命中的小块扩展成 `BigBlock`。
- 已掌握：标题层级与标题栈、`Section` 树、章节分组、token 预算切块、资产原子块、Chunk 元数据盖章，以及完整章节上爬和章节内开窗的区别。
- 实验结果：两级标题样例在 `target=18` 时产生 4 个 Chunk，其中“存储”被切成 `[3]`、`[4]` 两块；改为 `target=60` 后合并为 `[3,4]` 一块。命中“存储”小块后向父级上爬 1 层，得到 `anchor=[0,7]`、`windowed=False` 的完整文档级 BigBlock。
- 本课小结：固定字符切块会破坏语义边界并丢失标题语境；本项目用小 Chunk 提升召回精度，同时保留 Section sidecar，在查询期按 token 预算恢复完整章节或受限窗口。
- 下一课：L05 Embedding、稀疏向量与 Qdrant 建库。

#### 2026-09-15–16 · L05 Embedding、稀疏向量与 Qdrant 建库

- 状态：代码与原理学习完成；隔离 Collection 建库实验按学习者选择跳过。
- 本课主线：`Chunk → Embedder → dense/sparse vectors + payload → PointStruct → Store.upsert() → Qdrant collection`。
- 已掌握：Dense 将一个文本 Chunk 编码并按 MRL 截取、归一化为 1024 维向量；Sparse 用统一分词和稳定哈希保存 token 编号与文档词频；payload 保存正文、结构定位、来源和 ACL。
- 关键设计：`make_dense()` 按配置选择本地 `Dense` 或远程 `RemoteDense`；普通文本 point 有 dense、sparse 和 payload，`image_only` point 只有图片 dense 和 payload；重索引先准备向量与 Sidecar 临时文件，再删除旧 Point、批量 upsert 并原子替换 Sidecar。
- 本课小结：建库与查询必须使用同一 Embedding 模型、维度和归一化规则，使文档向量与查询向量处于同一坐标空间；即使维度相同，不同模型的向量也不能混用，更换模型必须重建 Collection。
- 下一课：L06 Dense、Sparse、Hybrid 与 RRF。

#### 2026-09-16 · L06 Dense、Sparse、Hybrid 与 RRF

- 状态：代码与原理学习完成；Dense/Sparse/Hybrid 接口对比实验按学习者选择跳过。
- 本课主线：`query → dense query vector + sparse query vector → ACL 下推 → 两路 prefetch → Qdrant RRF → Hit[]`。
- 检索对比：Dense 擅长同义表达和概念语义；Sparse/BM25 擅长命令、版本号、错误码和精确术语；Hybrid 用 RRF 按两路名次融合，避免直接相加 cosine 与 BM25 两种不同量纲的分数。
- 代码定位：`Retriever.search()` 生成两种查询向量并选择策略；`Store.hybrid_search()` 把 ACL 放入每条召回路径，`FusionQuery(fusion=Fusion.RRF)` 让 Qdrant 执行排名融合，出口再复核 ACL。
- 本课小结：RRF 是低成本的候选融合，不是模型精排；先在权限范围内召回，才能避免无权结果占满候选池后再过滤造成的漏召回。
- 下一课：L07 Rerank、去重与 small-to-big。

#### 2026-09-16 · L07 Rerank、去重与 small-to-big

- 状态：代码与原理学习完成；`rerank`/`expand` 接口对比实验按学习者选择跳过。
- 本课主线：`Hit 候选池 → 可选 Reranker → section 去重 → 读取并缓存每篇文档的 Sidecar → assemble_big → Context`。
- 已掌握：Reranker 把 query 与候选正文一起输入模型，重新写入相关性分数并截取最终 top-k；失败时安全降级为原召回结果。`search_with_context()` 先按 section 去重，表格和图表按 chunk 独立保留，再按实际 BigBlock anchor 去除重复上下文。
- 上下文扩展：Sidecar 保存整篇文档的 Elements、Sections、banners 与 ACL 索引，不保存 Hit；同文档多个 Hit 在一次查询中复用同一份缓存。当前章节超过 `max_tokens` 时在当前章节内围绕命中位置开窗；当前章节太小但父章节超过上限时，在父章节内开窗并可能包含兄弟小节。
- 本课小结：召回到的 Hit 是用于定位的相关小块，最终 Context 是经过权限校验、章节去重和 token 预算控制后交给生成模型的证据，两者不是同一份数据。
- 下一课：L08 Prompt、Grounding 与引用。

#### 2026-09-16–20 · L08 Prompt、Grounding 与引用

- 状态：完成。
- 本课主线：`Hit/Context → Generator.answer() → PromptBuilder → LLMClient.complete() → [cite:n] 解析 → Answer/Citation`。
- 已掌握：零召回时由代码确定性拒答；SYSTEM 将检索正文声明为不可信证据；PromptBuilder 中和正文与问题里的伪造引用标记；合法 `[cite:n]` 按位置映射回 `meta[n-1]` 并构造 Citation。
- LLM 装配：`LLMClient` 是行为协议，只要求对象实现 `complete(messages)`；生产环境由 `build_generator()` 注入 `OpenAICompatibleLLM`，测试可注入 `MockLLM`，不是依靠类名匹配。
- 本课小结：引用证明答案使用了哪段证据，但不能单独证明论断一定正确；Grounding 依赖 Prompt 软约束、零召回硬拒答、引用协议和评测共同防守。
- 下一课：L09 FastAPI 服务、错误契约和可观测性。

#### 2026-09-20 · L09 FastAPI 服务、错误契约和可观测性

- 状态：代码与原理学习完成；轻量接口实验因 Docker 已关闭而跳过。
- 本课主线：`pharos serve → create_app() → lifespan 装配共享资源 → _observe/_auth 中间件 → FastAPI 路由 → toolcore/Generator → 结构化响应与日志`。
- 已掌握：`app.state` 保存进程级共享资源，`request.state` 保存单次请求身份；API Key 决定身份，Retriever ACL 决定可见内容；`/healthz` 只判断进程存活，`/readyz` 检查 Qdrant、Collection 和远程推理服务是否可用。
- 错误契约：HTTP 401/403/422/503 表示认证、权限、请求结构或服务可用性问题；查询域中的 `empty_query`、`bad_arg`、`backend_unavailable` 等用稳定的 `status/retriable/hint` 让程序决定下一步，观测层同时检查 HTTP 状态和业务状态。
- 可观测性：`Stats` 用锁保护每端点次数、错误数和最近延迟窗口；`RequestLog` 在隐私收口后无阻塞放入有界队列，由后台单线程写 JSONL，队满时丢日志并计数，保证观测故障不拖垮问答服务。
- 本课小结：服务层不负责重新实现 RAG，而是把身份、生命周期、HTTP 契约、健康检查、并发资源和可观测性包在 Retriever/Generator 外面，使脚本能力成为可长期运行、可被多个客户端安全调用的后端。
- 下一课：L10 Docker 与在线推理适配器。

#### 2026-09-20 · L10 Docker 与在线推理适配器

- 状态：代码、配置和原理学习完成；停止在线推理服务与自动 reload 实验因 Docker 已按学习者要求关闭而跳过。
- 本课主线：`浏览器/curl → pharos → Qdrant + cloud-inference → 阿里云 Embedding/Rerank → DeepSeek`；上传时扩展为 `pharos → PostgreSQL/Outbox → Redis/Celery → worker → MinerU/Chunker/Embedding → Qdrant`。
- 已掌握：镜像是只读运行模板，容器是镜像的运行实例；服务之间在 `pharos-net` 中使用 Compose 服务名通信，宿主机只通过显式发布到 `127.0.0.1` 的端口访问服务。
- 数据边界：`postgres-data`、`redis-data`、`qdrant-data` 是 Docker 管理的 named volume；源码、索引、上传文件和密钥使用 bind mount，便于本地开发、持久化和受控共享。停止或普通 `down` 不删除数据，`down -v` 会删除 named volume。
- 在线推理：`PHAROS_INFERENCE_URL` 使 `pharos` 和 `worker` 使用 `RemoteDense/RemoteReranker`，由轻量 `cloud-inference` 适配器负责参数校验、顺序恢复、向量归一化和云端错误翻译，因此业务容器无需加载 torch、模型权重或 GPU 运行时。
- 生命周期：`depends_on` 只控制启动时的健康依赖；运行期故障由 health/readiness、重试、降级与 restart policy 处理。源码 bind mount 配合 uvicorn reload，依赖或镜像内容变化则需要 rebuild/recreate。
- 本课小结：Compose 不只是“一键启动”，而是明确服务职责、网络边界、数据生命周期和启动顺序；在线推理适配器把本地 RAG 工程与具体云模型 API 解耦。
- 下一课：L11 身份认证、ACL 与会话隔离。

#### 2026-09-20 · 后续学习路线重排

- 原因：旧 L17 仍把已经实现的 Agentic Runner 写成“计划能力”，旧 L18 仍把已经存在的前端写成待开发范围，后续几课也缺少明确代码入口。
- 调整：L11–L20 全部改为学习仓库中已经存在的代码、文档、测试和评测产物；MCP 工具面与内置 Agent 状态机拆成两课，上传解析与可靠任务拆成两课。
- 新顺序：`安全边界 → MCP → 内置 Agent → 上传解析 → 异步任务 → 生命周期并发 → 前端 → 评测 → 运维部署 → Git/简历`。
- 实验原则：Docker 关闭时优先做代码跟踪和无外部费用的单测；真实双身份、MinerU、在线模型和故障实验等到对应课程需要时集中启动服务，不因环境关闭打乱学习顺序。
- 下一课：L11 身份认证、ACL 与会话隔离。

#### 2026-09-12 · 开发检查点：上传任务与文档生命周期

- 状态：代码实现、自动化测试和 Docker 实测完成；对应知识尚未结课。
- 已实现链路：`FastAPI → PostgreSQL/Outbox → Redis/Celery → Worker → MinerU/Chunker/Embedding → Qdrant`。
- 已实现管理能力：上传任务查询与重试、管理库存、重建索引、ACL 更新、软删除和失败恢复。
- 验证结果：全量测试 `298 passed, 7 skipped`；真实 Docker 环境完成重建、权限更新和删除；同时发现并修复 PostgreSQL 锁顺序死锁。
- 学习安排：这些改造分别归入 L14、L15 和 L16，届时结合设计文档、代码、测试与提交历史学习。
- 下一课：先完成 L02 收尾，再进入 L03；不直接跳到新增模块。

#### 2026-09-11 · L02 配置、装配与核心数据结构

- 状态：主体完成，实验与结课复述待补。
- 已阅读：`config.py`、`engine.py`、`chunker/types.py`、`embedder/types.py`、`generator/types.py`，并跟踪本地/在线模型装配差异。
- 已理解主线：`Element → Chunk → Hit/Context → Answer/Citation`，以及 Dense、Sparse、Qdrant、Rerank、sidecar 和引用对象的职责。
- 提前预习：阅读了部分 `chunker/core.py`；该内容将在 L04 按完整索引链路复盘。
- 下一步：不看讲解独立完成两张图和一次口头复述，补齐 L02 完成标准。

#### 2026-09-11 · L01 一次 `/v1/ask` 请求的完整生命周期

- 状态：主体完成，结课复述待补
- 我理解的执行链：`/v1/ask → service.ask() → Generator.answer() → Retriever.search_with_context() → Retriever.search() → Store.hybrid_search() → Qdrant/Rerank → PromptBuilder → DeepSeek → Answer/Citation`。
- 最重要的三个知识点：
  1. `/v1/retrieve` 停在检索证据，`/v1/ask` 继续执行生成与引用解析。
  2. Dense 与 Sparse 在 ACL 范围内召回，RRF 融合候选，Reranker 再精排。
  3. Qdrant 命中小块后，`search_with_context()` 通过 sidecar 做去重和 small-to-big 扩展。
- 做过的实验及结果：分别调用 `/v1/retrieve` 与 `/v1/ask`；检索命中 Docker 官方文档，问答返回 DeepSeek 生成结果和三条引用。
- 仍不明白的问题：需在阶段一复盘时独立画出链路图，并完成 150–300 字口头或书面小结。
- 修改过的文件：仅更新学习计划，无业务代码修改。
- 下一课：L02 配置、装配与核心数据结构。

#### 2026-09-09 · 环境与首个知识库验证

- 状态：完成
- 已完成：Docker 三容器启动、在线模型配置、10 篇官方技术文档导入、204 chunks 建库。
- 实验结果：Docker volume 问题能够命中正确章节，DeepSeek 返回中文答案和三条引用。
- 测试结果：249 passed、12 skipped。
- 下一课：L01 一次 `/v1/ask` 请求的完整生命周期。

## 5. 后续对话续学口令

新对话或上下文不确定时，直接发送下面这句话：

> 继续 PharosRAG 学习。先读取 `docs/learning/PHAROS_CODE_STUDY_PLAN.md` 的“当前进度”和“学习记录”，从下一课开始；本课结束后更新计划文档。

后续协作约定：

1. 开课前先读取本文当前进度。
2. 一次只推进一课，不擅自跳课。
3. 我负责解释、带读代码、设计实验和检查理解；学习者亲自复述核心知识。
4. 课程结束后，更新勾选项、当前进度和学习记录。
5. 如果中途改项目功能，要把改动归入对应课程，避免学习线和开发线混在一起。
