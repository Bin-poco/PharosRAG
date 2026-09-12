# PharosRAG 代码学习计划（唯一进度源）

> 作用：固定学习顺序、记录完成情况，并让后续对话在上下文压缩后仍能准确续学。
>
> 学习原则：每次只学习一课；先读对应教学文档，再沿真实代码执行链阅读，最后做实验和小结。没有完成实验与复述，不勾选完成。

## 0. 当前进度

- 当前阶段：阶段一——建立完整请求地图
- 当前课程：`L02 配置、装配与核心数据结构`
- 下一步：阅读 `src/pharos/config.py`，追踪 `.env.mac → PharosConfig → engine.py → 运行对象`
- 最近更新：2026-09-11
- 当前环境：Apple Silicon Mac + Docker Compose + Qdrant + 阿里云 Embedding/Rerank + DeepSeek
- 当前知识库：10 篇官方技术文档，204 chunks
- 当前验证：`/readyz` 正常；`/v1/retrieve` 与 `/v1/ask` 均已成功；全量测试 249 passed、12 skipped

### 已完成的准备工作

- [x] 拉取并了解 PharosRAG 项目定位
- [x] 安装 Docker Desktop
- [x] 跑通三个容器：`pharos`、`qdrant`、`cloud-inference`
- [x] 配置阿里云 Embedding 与 Rerank
- [x] 配置 DeepSeek 生成模型
- [x] 导入 FastAPI、Docker、Qdrant 共 10 篇官方文档
- [x] 完成第一次带引用的知识库问答
- [x] 开始按代码调用链系统学习

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
  L14 来源链接改造 → L15 文档管理与前端 → L16 简历与面试复盘
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

### L14 第一个独立功能：Markdown 引用返回来源链接

**问题背景**：当前 Markdown 没有物理页码，因此 Citation 中显示 `page: 0`；但导入时已经保存 `source_url`，API 尚未把它返回给用户。

**目标功能**：

- Citation 增加可选 `source_url`
- 从 `doc_meta` 传递到生成结果
- API 返回官方文档链接
- 不影响 PDF 页码引用
- 添加单元测试和接口测试

**预计涉及**：

- `src/generator/types.py`
- `src/generator/generate.py`
- `src/pharos/service.py` 或其响应转换逻辑
- 对应 tests

**完成标准**：

- [ ] 先写清需求和数据流
- [ ] 自己完成第一版实现
- [ ] 测试通过
- [ ] Docker 环境真实问答返回 `source_url`
- [ ] 能讲清遇到的问题和设计取舍

### L15 产品化功能：文档管理与简单前端

**目标**：把只能由开发者执行命令的后端，变成用户能操作的产品。

建议按顺序实现：

1. 文档列表与详情页面
2. 对话页面和引用展示
3. 文档上传接口
4. 异步解析/建库任务与状态查询
5. 删除文档和增量重建
6. 错误提示、加载状态、空库引导

**完成标准**：

- [ ] 前端能完成一次问答并点击来源
- [ ] 用户能上传文档并观察处理状态
- [ ] 新文档无需手动进入容器执行命令即可检索
- [ ] 失败任务可定位、可重试

### L16 简历、架构图和面试复盘

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
