# 官方技术文档 Gold 题库复核（2026-09-19）

## 范围与结论

- 复核对象：`official_agent_gold.json` 的 26 题（5 道 single、7 道 multi_section、9 道 cross_doc、5 道 no_answer），以及 2026-09-12 的 78 次运行报告。逐题对照仓库中 `data/parsed/<doc_id>/source.md` / `source.rst` 的固定语料，核对问题、参考答案、必需事实和文档范围；对历史运行只做了有针对性的答案抽查，**没有逐条签收 78 份输出**。
- 结论：23 题的核心参考答案与指定来源一致；3 题存在需要收窄/更新的标准答案措辞。另发现 1 个自动裁判的明确漏判，以及 2 处跨文档引用组检查过宽。这里是 **AI 辅助证据复核**，不是独立人工审核；`provenance.human_review` 应继续保持 `pending`。
- 未改动现有 Gold JSON 或历史报告，避免改变已跑过的 suite SHA 和基线。本文中的修改建议供下一版题库采用。

下表的 `doc_id:行号` 指向 `data/parsed/<doc_id>/source.md`；Celery 文档的扩展名是 `.rst`。这些行号对应当前固定语料，不代表将来官网页面的行号。

## 逐题核对

| Case ID | 结论 | 关键证据 / 审核意见 |
| --- | --- | --- |
| `single_fastapi_request_body` | 通过 | `fastapi__request_body:68-81` 明确列出 JSON、类型转换、校验错误、Schema、OpenAPI。 |
| `single_docker_volume_lifecycle` | **需修订** | `docker__volumes:18-26,63-71` 说明 Docker 管理及一般情况下容器删除后的数据存续；但 `:94-102` 明确指出以 `--rm` 创建的容器关联的**匿名卷**会被删除。现有必需事实“删除容器不会自动删除 volume 数据”太绝对；应限定为“通常不会；`--rm` 的匿名卷是例外”，或明确问具名 volume。 |
| `single_qdrant_point_updates` | 通过 | `qdrant__points:161-168` 直接说明相同 ID 覆盖和幂等性；安全重试限定为相同操作，不等于并发写入没有竞态。 |
| `single_celery_broker_backend` | 通过 | `celery__first_steps:38-83,305-306` 说明 broker 必需、backend 可选及 RabbitMQ/Redis 差异。 |
| `single_fastapi_testing` | 通过 | `fastapi__testing:3-7,35-41` 说明 TestClient 基于 HTTPX，普通同步测试无需 `await`。 |
| `multi_fastapi_lifespan` | 通过 | `fastapi__lifespan_events:35-37,91` 分别说明 `yield` 前后及事件处理器不混用。 |
| `multi_fastapi_oauth2_jwt` | 通过 | `fastapi__oauth2_jwt:17-19,53-65,179-199,237-243` 支撑签名非加密、密码哈希、唯一字符串 `sub` 和 Bearer 链路。 |
| `multi_docker_resource_limits` | 通过 | `docker__resource_constraints:11-12,72-88,94-119,158-162` 支撑默认无约束、硬/软内存、swap、CPU 上限/权重。 |
| `multi_docker_bind_mounts` | 通过 | `docker__bind_mounts:35-59,82-98,124-126` 支撑遮蔽、默认可写、daemon 主机路径及 `--mount`/`--volume` 差异。 |
| `multi_qdrant_indexing` | 通过 | `qdrant__indexing:13-25,39-53,321-339` 支撑向量/载荷索引功能及提前建索引。 |
| `multi_qdrant_storage` | **需修订** | `qdrant__storage:27-33,78-102` 支撑 cached/cold/WAL，但其“已索引字段保留在 RAM”表述与同批固定语料的 `qdrant__indexing:135-143`（payload index 默认 `pinned`、可配置内存层）不完全一致。不能把“无条件常驻 RAM”作为唯一正确答案。建议改为“默认加载到 pinned 内存层；具体内存/磁盘占用可按索引内存层配置，注意两份文档措辞差异”。 |
| `multi_celery_task_reliability` | 通过 | `celery__tasks:16-35,692-748,777-802` 支撑幂等、晚确认、自动重试、指数退避与 jitter。需要记住：`acks_late` 不保证子进程异常终止时重投（同文档 `:32-47`）。 |
| `cross_fastapi_background_celery` | 通过，评分需加强 | `fastapi__background_tasks:76-82` 推荐重计算用 Celery；`celery__first_steps:305-306` 与 `celery__tasks:21-30` 分别支撑 broker 和幂等/晚确认。问题要求“选择建议”，不只是罗列事实。 |
| `cross_docker_volume_bind` | 通过 | `docker__volumes:18-44,63-71` 与 `docker__bind_mounts:13-22,48-59` 支撑管理、主机耦合和场景比较。 |
| `cross_docker_secrets` | **需修订** | `docker__compose_secrets:20-28` 是 **Compose 服务级运行时 secrets**；但同一页 `:97-114` 也讲 **Compose `build.secrets`**。现有题面/金标笼统说“Compose secrets 用于运行时”，容易把 Compose 构建秘密排除。建议题面写“Compose 中 `services.<name>.secrets` 与构建阶段的 `build.secrets`/Docker Build secrets”，答案明确前者按服务挂载、后者仅在指定构建步骤使用。ARG/ENV 风险见 `docker__build_secrets:13-15`。 |
| `cross_docker_networking` | 通过，引用检查需加强 | `docker__compose_networking:15-17,41-49`、`docker__bridge_network:49-50`、`docker__port_publishing:40-50` 支撑服务名、容器端口、DNS 和 localhost。现有第二个引用组允许 bridge **或** port-publishing 任一篇，不能保证同时覆盖 DNS 与发布端口安全点。 |
| `cross_docker_build_image` | 通过 | `docker__multi_stage_builds:17-22,59-61` 与 `fastapi__docker_deployment:189-213` 支撑多阶段精简和依赖层缓存。 |
| `cross_qdrant_multitenancy` | 通过 | `qdrant__multitenancy:13-40` 支撑 collection 开销、租户 payload、`is_tenant`、独立 shard；`qdrant__indexing:53,147-167` 支撑提前建索引。 |
| `cross_qdrant_hybrid_quantization` | 通过 | `qdrant__hybrid_queries:21-30,40-65,123-139` 支撑 prefetch、融合、两阶段；`qdrant__quantization:19-20,325-349` 支撑压缩及原向量重评分。 |
| `cross_qdrant_availability` | 通过，建议补边界 | `qdrant__storage:100-112`、`qdrant__snapshots:16-26,46-61`、`qdrant__distributed_deployment:130-153,372-386` 支撑 WAL、快照、副本、分片。自托管**已有** collection 后仅调大 `replication_factor` 不会自动补副本；分布式快照需逐节点创建。建议作为必需事实或另出边界题。 |
| `cross_fastapi_workers_docker` | 通过 | `fastapi__server_workers:18-30`、`fastapi__docker_deployment:231-255` 支撑单机多 worker、集群单进程/容器及 exec-form CMD。 |
| `noanswer_fastapi_approval_contact` | 通过 | 指定 FastAPI 官方部署文档并非内部审批人/电话名册；应说明缺证据。 |
| `noanswer_qdrant_guaranteed_qps` | 通过 | Qdrant 混合查询和分布式配置文档不能给特定 3 节点、特定数据集的**保证** QPS；应说明需实际基准测试。 |
| `noanswer_qdrant_cloud_price` | 通过 | 指定 Qdrant 技术文档没有当前价格、实例规格、人民币汇率，不能精确计价。 |
| `noanswer_docker_secret_value` | 通过 | 指定 Docker secrets 页仅有机制和示例名称，不能推导用户生产数据库的真实凭据。 |
| `noanswer_celery_internal_sla` | 通过 | 指定 Celery 通用文档不包含用户组织的 SLA、负责人、电话。 |

## 对现有评测结果的抽查发现

1. **自动裁判漏判了“选择建议”。** 在 `agent-benchmark-20260912-212712.json` 的 `cross_fastapi_background_celery` 中，`agent` 和 `auto` 两个回答都以“无法给出确定/明确的选择建议”收尾，尽管题目要求给出建议、官方 FastAPI 文档已给出重计算任务可考虑 Celery 的依据。裁判仍将两者判为 `correct=true`。建议将“明确建议优先选 Celery，同时说明没有绝对时长阈值”列为单独必需事实，并以人工规则复查裁判结果。
2. **合同检查只核文档级引用，不核具体断言。** `agent_benchmark.py:105-151` 检查引用是否来自指定 `doc_ids`、是否覆盖引用组；它无法判断某个论断旁边的 `[cite:n]` 是否真的对应支撑段落。语义裁判也为可选且属于同厂模型，不能替代人工抽检。
3. **两个引用组过宽。** `cross_fastapi_background_celery` 的 Celery 组允许 first_steps **或** tasks，不能同时保证 broker 与晚确认；建议拆成两个独立组。`cross_docker_networking` 的 bridge/port-publishing 也应拆成两个组。注意即便拆组，仍需检查“引用贴在正确断言上”。
4. **“100% 正确”不是上线结论。** 2026-09-12 报告中的 agent 正确性 100% 来自同厂模型裁判；同一报告 `cross_qdrant_multitenancy`/agent 有 `finish_reason=length`，自动裁判仍判正确。应分别报告语义裁判分、合同通过率、截断率及人工复核率。此次没有重新调用在线模型，也没有重跑 78 次测试。

## 第 2 项：覆盖缺口与下一版补题草案

现有 5 道拒答题主要是明显不存在的公司内部信息；26 题没有真正困难的边界条件、配置冲突、条件计算，也没有在语义评测中覆盖权限隔离。权限回归已有独立的 `eval/acl_regression.py`，不能说项目完全没测 ACL；只是当前 Gold 套件无法衡量“回答是否泄露别的租户的内容”。建议保留 v1 的 26 题不变，在 v2 中至少加入以下 6 题，并为每题写独立必需事实、来源片段和拒答标准：

| 优先 | 新题目草案 | 应判定的关键点与来源 |
| --- | --- | --- |
| P0 | “文档解析任务持续几分钟且可在独立 worker 运行，BackgroundTasks 和 Celery 你建议选哪个？有官方规定的分钟阈值吗？” | 优先建议 Celery；**没有固定分钟阈值**，依据是任务重计算及可跨进程/服务器运行。`fastapi__background_tasks:76-82`。修补当前“只罗列不建议也得分”的漏判。 |
| P0 | “Celery 设 `acks_late=True` 后，执行任务的子进程被 signal 杀死，消息一定重新投递吗？” | **不一定**；文档明确说该情形仍确认消息，若希望重投可考虑 `task_reject_on_worker_lost`。`celery__tasks:28-47`。 |
| P0 | “三节点自托管 Qdrant 已有 collection，把 `replication_factor` 从 1 改 2，就会自动出现第二份副本吗？备份只抓一个节点的 snapshot 够吗？” | 两个答案都是否：自托管需手工创建副本，分布式快照要逐节点。`qdrant__distributed_deployment:374-386`、`qdrant__snapshots:16-26`。 |
| P1 | “Qdrant 主查询 `limit=10, offset=5`，每个 prefetch 的 `limit` 至少应设多少？不足可能怎样？” | 至少 **15**；否则可能得到空结果。`qdrant__hybrid_queries:21-30`。增加精确条件/计算覆盖。 |
| P1 | “Compose 文件能不能把同一个顶层 secret 用在 `build.secrets`？这和服务运行时 `secrets` 暴露时机有什么不同？” | 能；前者构建阶段供指定 `RUN`，后者运行时按服务授权并挂载文件。`docker__compose_secrets:20-28,97-114`、`docker__build_secrets:35-73`。 |
| P1 | “FastAPI 主应用配置了 lifespan，挂载子应用的 lifespan 会自动执行吗？” | 不会；文档限定为主应用。`fastapi__lifespan_events:163-165`。 |

另开一套**平台业务评测**更合适：用两个租户、公开/私有文档和两个测试用户，测试入库后搜索、`/v1/ask`、`/v1/agent/ask` 的跨租户不可见性；加入含伪造 SYSTEM 指令的文档作为提示注入样例。这需要稳定的隔离 fixture，不能仅靠当前官方技术文档套件模拟，也不应把其中的虚构权限题混入 v1。

## 下一步执行顺序

1. 将上述三题措辞及两个引用组修订到新的 v2 Gold；v1 保留用于旧报告可追溯。
2. 将 6 道补题写成结构化用例，先在固定语料中核对每个事实的实际 chunk 是否可检索，再运行 direct/agent/auto 配对评测。
3. 对所有失败题和随机抽样的通过题，人工查看 **答案句子 → citation marker → 具体 chunk 原文**，记录证据及裁决者；这样才可把 `human_review` 改为完成。

## V2 落地进度

已另建 `official_agent_gold_v2.json`：修订了第 1 步中的 3 题与 2 组引用要求，加入上述 6 道边界题；v1 原文件保留以便追溯。已完成结构、manifest、来源文件及本地评测代码测试。尚未证明所有所需证据块可由当前索引召回，也没有运行在线模型配对评测或独立人工签收；第 2 步后半段与第 3 步仍待完成。
