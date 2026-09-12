# PharosRAG 代码学习计划（唯一进度源）

> 作用：固定学习顺序、记录完成情况，并让后续对话在上下文压缩后仍能准确续学。
>
> 学习原则：每次只学习一课；先读对应教学文档，再沿真实代码执行链阅读，最后做实验和小结。没有完成实验与复述，不勾选完成。

## 0. 当前进度

- 当前阶段：阶段一——建立完整请求地图
- 当前课程：`L02 配置、装配与核心数据结构（收尾）`
- 下一步：完成 L02 的两个收尾实验：复述 `.env.mac → PharosConfig → engine.py → 运行对象`，再独立画出 `Element → Chunk → Hit/Context → Answer/Citation`；记录小结后进入 L03
- 最近更新：2026-09-12
- 当前环境：Apple Silicon Mac + Docker Compose + Qdrant + 阿里云 Embedding/Rerank + DeepSeek
- 当前知识库：10 篇官方技术文档，204 chunks
- 当前验证：`/readyz`、`/v1/retrieve`、`/v1/ask` 正常；文档上传、异步入库、重建索引、权限变更和软删除均完成 Docker 实测；全量测试 298 passed、7 skipped

### 学习进度与开发进度不是一回事

- `L01`：主体已学，独立复述与书面小结待补。
- `L02`：配置、装配和核心数据结构主体已学；下一次先完成实验与结课复述。
- `L03`：L02 结课后从这里继续按顺序学习。
- `L04` 的部分 Chunker 代码曾提前预习，不计作结课；走到 L04 时仍按本计划完整复盘。
- 文档上传、可靠异步任务和文档生命周期已经实现并合入 `main`，但安排到 `L15–L16` 再系统学习。
- “代码已实现”只表示功能和测试完成；只有完成对应阅读、实验与复述，才表示“已经掌握”。

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

阶段四：产品与 Agent
  L09 FastAPI 服务 → L10 Docker 与在线推理 → L11 ACL 与会话
  → L12 MCP Agentic RAG → L13 评估与测试

阶段五：把项目变成自己的
  L14 用 Git 划清上游与个人改造 → L15 可靠异步上传
  → L16 文档生命周期与并发一致性 → L17 可观察的 Agentic 工作流
  → L18 简单前端 → L19 工程化、评估与部署 → L20 简历与面试复盘
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

- [ ] 能解释依赖注入在本项目中的作用
- [ ] 能区分 `Element`、`Chunk`、检索命中和 `Citation`
- [ ] 能说明为什么测试不必真的调用云模型
- [ ] 完成本课小结

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

- [ ] 能解释为什么要有统一 Element 层
- [ ] 能说明 Markdown 导入和 MinerU 导入在哪里汇合
- [ ] 能解释 `metadata.json` 的作用
- [ ] 完成本课小结

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

- [ ] 能解释标题树如何保留文档结构
- [ ] 能解释“小块用于检索，大块用于生成”
- [ ] 能说出固定长度切块的两个问题
- [ ] 完成本课小结

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
- 确认每个 point 同时包含 dense、sparse 和 payload。

**注意**：不要直接清空当前 `tech_docs`；实验应使用新 collection。

**完成标准**：

- [ ] 能解释 Embedding 的输入与 1024 维输出
- [ ] 能解释 sparse 向量保存了什么
- [ ] 能说清 Qdrant point 的 vector 与 payload
- [ ] 能解释为什么建库和查询必须使用同一个 Embedding 模型
- [ ] 完成本课小结

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

- [ ] 能解释 Dense 和 Sparse 各自擅长什么
- [ ] 能用自己的话解释 RRF，不背公式也能讲明白
- [ ] 能根据问题类型预测哪条检索路线更有优势
- [ ] 完成本课小结和对比表

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

- [ ] 能解释召回候选池与 top-k 的区别
- [ ] 能解释 Rerank 为什么更准但更慢
- [ ] 能解释 section 去重与上下文扩展
- [ ] 完成本课小结

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

- [ ] 能解释零召回时为什么不应该让 LLM 自由回答
- [ ] 能解释 `[cite:n]` 到 Citation 对象的映射
- [ ] 能说出至少两种幻觉或提示注入防线
- [ ] 完成本课小结

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

- [ ] 能解释 liveness 和 readiness 的区别
- [ ] 能解释为什么部分业务失败仍返回结构化 JSON
- [ ] 能找到请求耗时和错误统计的位置
- [ ] 完成本课小结

### L10 Docker 与在线推理适配器

**目标**：真正理解三个容器的职责和网络调用，而不是只会启动命令。

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

- 画出三个容器、两个云 API 和端口之间的连接图。
- 单独停止 `cloud-inference`，观察 `/readyz` 与检索如何变化，然后恢复。
- 修改一条无关紧要的日志文字，观察自动 reload。

**完成标准**：

- [ ] 能解释容器与镜像的区别
- [ ] 能解释 bind mount 和 named volume 在本项目中分别保存什么
- [ ] 能解释为什么 `pharos` 容器不需要 GPU/torch
- [ ] 完成本课小结

### L11 身份、ACL、会话与 fail-closed

**目标**：理解这个项目与普通 RAG Demo 的关键工程差异。

**先读**：

- `docs/learning/04-acl-security.md`

**看代码**：

- `src/pharos/identity.py`
- `src/embedder/acl.py`
- `src/pharos/sessions.py`
- `src/pharos/service.py`：鉴权 middleware
- `src/chunker/types.py`：ACL 字段

**实验**：

- 使用错误 API Key 验证 401。
- 创建一份仅特定 principal 可见的小测试文档。
- 用两种身份验证：允许身份能检索，其他身份得到空结果。

**完成标准**：

- [ ] 能区分身份认证与内容授权
- [ ] 能解释 ACL 为什么必须在检索阶段过滤
- [ ] 能解释 fail-closed
- [ ] 能说明会话去重为什么必须绑定身份
- [ ] 完成本课小结

### L12 MCP 与 Agentic RAG

**目标**：从闭管道问答过渡到由 Agent 自己规划检索步骤。

**先读**：

- `docs/learning/06-agentic-mcp.md`

**看代码**：

- `src/pharos/mcp_adapter.py`
- `src/pharos/toolcore.py`
- `src/pharos/mcp_stdio.py`：只比较 direct 模式差异
- `.mcp.json.example`

**实验**：

- 配置本地 MCP 客户端连接 Pharos。
- 让 Agent 先 `list_documents`，再 `get_outline`，然后 `retrieve`。
- 设计一个必须 `expand` 或跨文档检索的问题。
- 对比相同问题在 `/v1/ask` 和 Agentic 路径下的调用次数、答案与成本。

**完成标准**：

- [ ] 能解释为什么 `/v1/ask` 不是 Agentic RAG
- [ ] 能说出六个 MCP 工具的职责
- [ ] 能解释 Agent 在哪里做规划、Pharos 在哪里执行检索
- [ ] 能说出 Agentic 模式的优势和风险
- [ ] 完成本课小结

### L13 测试、评估与证据

**目标**：学会用数据判断改动，而不是只看单个问答感觉不错。

**先读**：

- `docs/learning/07-evaluation.md`
- `docs/TESTING.md`

**看代码**：

- `tests/test_service.py`
- `tests/engine/test_retrieve.py`
- `tests/engine/test_generate.py`
- `eval/` 中的入口脚本和样例格式

**实验**：

- 为一个已理解的函数补一个单元测试。
- 建立 10–20 题属于当前技术文档库的小评估集。
- 至少记录召回命中、答案正确和引用正确三项。

**完成标准**：

- [ ] 能区分组件测试和端到端评估
- [ ] 能解释 Recall、MRR、正确性、忠实度和引用正确性
- [ ] 能说明为什么不能只展示一条成功案例
- [ ] 完成本课小结

---

## 阶段五：把项目变成自己的

### L14 用 Git 划清上游与个人改造

**目标**：先分清原项目能力和个人新增能力，后续学习、简历和面试都不混淆归属。

**按顺序查看**：

1. `162c7ca`：拉取项目时的上游基线。
2. `0995802`：个人新增的 Markdown/PDF 上传与 MinerU 接入。
3. `6e01f28`：Apple Silicon + 在线推理开发栈。
4. `9f787cc..cd6629d`：可靠异步上传任务演进。
5. `f0cb7ba`：可审计文档生命周期。

**实验**：

- 查看每个里程碑相对上一个里程碑的文件变化。
- 任选一个新增接口，沿提交记录说明它为什么出现、后来修过什么问题。
- 建立一张“上游已有 / 我们新增 / 后续计划”对照表。

**完成标准**：

- [ ] 能诚实区分上游能力和个人改造
- [ ] 能用提交历史讲出功能演进，而不是只报最终代码量
- [ ] 能解释分支、提交、合并提交各自的作用
- [ ] 完成本课小结

### L15 可靠异步上传：从 HTTP 请求到可检索文档

**目标**：理解上传为什么不能在一次 HTTP 请求里同步完成，以及 PostgreSQL、Redis、Celery、Worker 和 Outbox 如何协作。

**先读**：

- `docs/RELIABLE_UPLOAD_JOBS.md`
- `docs/API.md`：文档上传和任务查询部分

**按执行顺序看代码**：

1. `src/pharos/service.py`：`upload_document()`、任务查询与重试入口。
2. `src/pharos/uploads.py`：文件校验、ACL 标准化和本地落盘。
3. `src/pharos/jobs/models.py`：文档、任务与 Outbox 的状态字段。
4. `src/pharos/jobs/repository.py`：事务写入、任务认领和状态更新。
5. `src/pharos/jobs/dispatcher.py` 与 `src/pharos/worker/tasks.py`：消息分发和 Worker 执行。
6. `src/pharos/ingestion/pipeline.py`：解析、切块、Embedding 与索引发布。

**实验**：

- 上传一份短 Markdown 和一份 PDF，轮询任务直至 `succeeded`。
- 暂停 Worker 后上传文档，观察请求、数据库任务和 Outbox 的状态；恢复后确认任务最终执行。
- 构造一次可重试失败，验证手动重试不会覆盖旧任务历史。

**完成标准**：

- [ ] 能画出 `API → PostgreSQL/Outbox → Redis → Celery Worker → MinerU → Qdrant` 链路
- [ ] 能解释为什么任务状态不能只放 Redis
- [ ] 能解释 Outbox 解决的“双写一致性”问题
- [ ] 能说明幂等、认领、重试和恢复分别防什么故障
- [ ] 完成本课小结

### L16 文档生命周期、ACL 变更与并发一致性

**目标**：理解文档从上传到重建、改权限和删除的完整状态机，以及为什么这部分已经不再只是 Demo 逻辑。

**先读**：

- `docs/DOCUMENT_LIFECYCLE.md`
- `docs/API.md`：`/v1/uploads`、`reindex`、`access` 和删除接口

**按场景看代码**：

1. `src/pharos/service.py`：四个生命周期 API 的权限和错误契约。
2. `src/pharos/jobs/repository.py`：普通用户/管理员列表范围、held job、Outbox 与恢复。
3. `src/pharos/ingestion/pipeline.py`：旧索引删除与新索引发布。
4. `tests/test_uploads.py`：接口、身份、ACL 与失败分支。
5. `tests/test_jobs.py`：并发认领、恢复和数据库锁顺序。

**实验**：

- 对同一文档依次执行列表、重建索引、收紧 ACL 和软删除，记录每一步的文档状态与任务状态。
- 用普通用户和同租户管理员对比 `/v1/uploads` 可见范围。
- 在任务运行期间重复发起冲突操作，确认服务拒绝并发生命周期变更。
- 根据真实修复记录复述 PostgreSQL 死锁的两条锁路径，以及统一锁顺序为什么能解决问题。

**完成标准**：

- [ ] 能区分 Qdrant 可检索库存 `/v1/documents` 与数据库管理库存 `/v1/uploads`
- [ ] 能解释为什么 ACL 更新先进入 held 状态，再删除旧索引并发布新任务
- [ ] 能解释软删除为何保留数据库审计记录，但删除向量和本地资产
- [ ] 能解释 `job → outbox` 统一锁顺序如何避免死锁
- [ ] 完成本课小结和一张文档状态机图

### L17 可观察的 Agentic RAG 工作流

**目标**：在现有 MCP 工具面之上实现真正可评估的 Agent 编排，而不把“接入 MCP”直接等同于 Agentic RAG。

**计划能力**：

1. 判断是否需要检索并生成检索计划。
2. 查询改写、首次召回和证据充足度判断。
3. 证据不足时按章节、文档或子问题继续检索。
4. 限制最大步骤、最大 token 与超时，失败时降级或拒答。
5. 返回每步 trace，并与 `/v1/ask` 做正确率、引用、延迟和成本对比。

**完成标准**：

- [ ] 先完成设计文档和状态图，再写业务代码
- [ ] 至少覆盖单跳、单篇多跳、跨文档和无答案四类问题
- [ ] 每一步可观察、可限制、可测试
- [ ] 用评估数据说明 Agentic 路径何时更好、何时不值得

### L18 简单前端：把后端能力变成可演示产品

**目标**：让非开发者能够上传文档、查看任务进度、提问并检查引用和 Agent trace。

**最小范围**：

1. 登录身份或开发身份选择。
2. 文档列表、上传、任务进度和失败重试。
3. 对话页、来源卡片和无答案提示。
4. 管理员执行重建索引、ACL 更新和软删除。
5. Agentic 模式的步骤 trace 展示。

**完成标准**：

- [ ] 前端能完成一份文档从上传到问答的完整演示
- [ ] 普通用户和管理员看到的管理能力符合权限设计
- [ ] 错误、空库和处理中状态有明确反馈
- [ ] 引用可以定位到来源文档

### L19 工程化、评估与部署

**目标**：用可重复证据证明系统可靠、有效且能够部署，而不是只演示一条成功问答。

**任务**：

- 建立 20–50 题个人评估集，覆盖检索、答案、引用、权限和 Agentic 多跳。
- 增加 CI、结构化日志、关键指标、限流与备份恢复说明。
- 分离开发和部署 Compose，补 HTTPS、随机密钥和数据持久化方案。
- 记录 Recall@K、MRR、正确率、引用正确率、P95 延迟和单次成本。

**完成标准**：

- [ ] 评估可重复运行且结果可追溯
- [ ] 服务重启后任务、文档记录和向量仍然存在
- [ ] 至少完成一次从空环境开始的部署演练
- [ ] README 中只使用自己实测的数字

### L20 简历、架构图和面试复盘

**先读**：

- `docs/learning/10-methodology-stories.md`
- `docs/learning/11-interview-qa.md`

**最终产出**：

- [ ] 一张自己能讲清的系统架构图
- [ ] 一份 README：问题、架构、功能、运行方式、指标、截图
- [ ] 20–30 道当前知识库评估集及结果
- [ ] 3 个自己完成的功能或优化
- [ ] 1 个真实故障排查故事
- [ ] 30 秒、3 分钟、15 分钟三档项目介绍
- [ ] 简历项目描述中的每个数字都有测试依据
- [ ] 能明确说明上游基础、个人改造和仍未完成的部分

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
