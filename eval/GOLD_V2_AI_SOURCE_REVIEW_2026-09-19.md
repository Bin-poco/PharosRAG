# 官方技术文档 Gold v2：外部模型证据复核（2026-09-19）

## 身份与范围

这是由 Codex 对固定在仓库中的 32 道题进行的 **AI 证据复核**，不是人工标注、领域专家签收或被测服务的在线效果评测。Codex 不参与 `/v1/ask` 的被测模型推理，因此可从服务外部检查题目和来源；但 Codex 曾协助编写 v2 题库及上一版复核记录，**不是与题库编写者相互独立的盲审者**。不同模型本身也不保证无偏。

核对对象为 `official_agent_gold_v2.json` 中题面、参考答案、每条必需事实、允许文档与引用来源组。前 26 道的逐题来源核查见 [上一版证据复核](GOLD_REVIEW_2026-09-19.md#逐题核对)；本次再次查看了有歧义的修改点、引用要求和新增 6 题所依赖的本地文档。所有 32 题通过结构与 manifest 校验；这只表示题目所列来源存在，**不表示检索器一定能召回所需 chunk**。

## 复核结论

- 前 26 题沿用上一版逐题核查的结论，其中 3 题在 v2 中按来源订正：`single_docker_volume_lifecycle` 明确询问 `--rm` 的匿名卷例外；`multi_qdrant_storage` 同时使用 Storage 和 Indexing 文档，避免“索引总在 RAM”的过度断言；`cross_docker_secrets` 区分服务级运行时秘密与 `build.secrets`。
- `cross_fastapi_background_celery` 单独要求明确选择建议，并要求 FastAPI、Celery first_steps、Celery tasks 三个来源；`cross_docker_networking` 单独要求 Compose、bridge、port publishing 三个来源。本次额外修正了后者的题面和标准答案：Docker 文档明确警告 **28.0.0 以前**绑定 localhost 的发布端口仍可能被同一二层网络的主机访问；不能把 localhost 绑定写成所有版本的绝对安全保证。来源：`data/parsed/docker__port_publishing/source.md:40-57`。
- 新增 6 题的证据与边界如下。每题的 `citation_doc_groups` 均落在自身允许的 `doc_ids` 中；无答案题的“拒答”只针对题面指定的官方文档范围。

| 新题 ID | 结论与来源 |
| --- | --- |
| `single_fastapi_heavy_task_choice` | 通过：重计算且无需共享 Web 进程时 FastAPI 建议考虑 Celery，文档没有固定分钟阈值；`data/parsed/fastapi__background_tasks/source.md:76-83`。题设已给足选择前提，不能只罗列两者。 |
| `single_celery_late_ack_worker_lost` | 通过：即便 `acks_late`，执行子进程被 signal 终止时 worker 仍确认消息；若需重投可考虑 `task_reject_on_worker_lost`；`data/parsed/celery__tasks/source.rst:28-47`。 |
| `cross_qdrant_existing_replicas_snapshots` | 通过：自托管现有 collection 改副本系数不会自动补副本，需手动建 shard replica；分布式快照需逐节点创建；`data/parsed/qdrant__distributed_deployment/source.md:374-389`、`data/parsed/qdrant__snapshots/source.md:16-27`。 |
| `single_qdrant_prefetch_offset` | 通过：主查询 `limit=10,offset=5` 时每个 prefetch 的 limit 至少为 15，不足可能返回空结果；`data/parsed/qdrant__hybrid_queries/source.md:21-30`。 |
| `cross_docker_compose_build_secrets` | 通过：Compose 顶层 secret 可以配置到 `build.secrets`；Dockerfile 在指定 `RUN --mount=type=secret` 指令中读取，服务级秘密运行时按服务授权并挂载；`data/parsed/docker__compose_secrets/source.md:18-28,97-114`、`data/parsed/docker__build_secrets/source.md:33-73`。 |
| `single_fastapi_subapp_lifespan` | 通过：指定 FastAPI 文档说主应用的 lifespan 事件不会自动在挂载子应用中运行；`data/parsed/fastapi__lifespan_events/source.md:161-165`。 |

静态题库层面，目前未发现新的、足以阻止使用 v2 作为**待人工确认的回归考卷**的来源冲突。这里的“通过”不等于 32 个被测系统答案正确，也不等于全部引用正确；本次没有运行在线评测，没有对每个生成答案做句子→引用→原始 chunk 的签收。

## 签收边界与后续

题库 `provenance.ai_source_review` 记录上述模型复核；`provenance.human_review` **继续为 `pending`**。若对外声称“人工审核的 gold”或“经人工证明的准确率”，仍需由真实审核人核对题目与来源，并在 v2 实测后对错误题及抽样正确题逐条核验答案和引用。若只在学习项目内使用，可如实写作“项目外模型进行来源交叉复核，保留人工审核待办”；不要把 AI 签字改写成人工签字。
