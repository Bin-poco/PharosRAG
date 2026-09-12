# 可靠文档上传任务

这一层把“收到文件后在 Web 进程里跑一段后台代码”升级为可恢复、可观察、可水平扩展的摄取任务。
它不改变 RAG 的切块、Embedding、Qdrant 和 ACL 逻辑，只改变这些耗时步骤如何被可靠地调度。

## 组件职责

```text
POST /v1/documents
        |
        |  同一数据库事务
        v
PostgreSQL: documents + ingestion_jobs + job_outbox
        |                              |
        | API 尝试即时投递              | scheduler 定时补投
        +------------------------------+
                       |
                    Redis
                       |
                 Celery Worker
                       |
     MinerU -> Chunker -> Embedding -> Qdrant + sidecar
```

- PostgreSQL 是文档和任务状态的唯一真相来源；Redis 丢消息不会丢任务。
- Outbox 与任务在同一事务创建，避免“数据库已有任务，但消息没有发出去”的双写裂缝。
- 消息只带 `job_id`；Worker 从数据库重新读取可信的文件路径、tenant、owner 和 ACL。
- `worker_id=hostname:celery_task_id` 是一次领取的租约标识。旧 Worker 丢失租约后不能写阶段或完成状态。
- Heartbeat 每 15 秒续租；scheduler 每 30 秒检查超过 120 秒无心跳的 `running` 任务。

## 状态机

```text
queued -> running -> succeeded
             |
             +-- 永久错误 -----------------> failed
             |
             +-- 瞬态错误且仍有次数 -> retrying --(到期投递)--> running
             |
             +-- Worker 失联 -----------> retrying / failed

failed --(人工 retry，创建新 job)--> queued
```

文档状态与任务状态刻意分开：

- `document.status`: `queued | processing | ready | failed`，回答“文档现在能否使用”；
- `ingestion_job.status`: `queued | running | retrying | succeeded | failed`，回答“这次任务如何执行”；
- `stage`: `uploaded | parsing | mineru_parsing | chunking | embedding | waiting_retry | ready | failed`，用于定位耗时和故障位置。

## 自动重试边界

只重试很可能自行恢复的基础设施故障：连接/超时、HTTP 429/5xx、MinerU 暂时不可用、Qdrant
或数据库连接中断。无效 PDF、UTF-8 错误、权限错误、配置缺失和 MinerU 明确解析失败不会重试。

默认最多执行 3 次，退避约为 10 秒、30 秒、90 秒并带稳定抖动，避免上游恢复瞬间所有任务同时
重放。每次解析写入独立临时目录，成功后才替换正式 `parsed/`，失败尝试不会污染下一次执行。

## 故障恢复为什么有效

1. Redis 在 API 投递时不可用：Outbox 保持 `pending`，scheduler 后续补投。
2. 同一消息被重复投递：数据库行锁只允许一个 Worker 从 `queued/retrying` 转为 `running`。
3. Worker 执行中崩溃：心跳停止，stale recovery 将任务重新入队；超过次数则失败。
4. 被判失联的旧 Worker 又恢复：它的 `worker_id` 已失效，租约校验拒绝它覆盖新 Worker 状态。
5. MinerU/在线推理暂时超时：任务进入 `waiting_retry`，到期后 Outbox 再次投递。

这里采用“至少一次投递 + 业务幂等”，不是假设消息永远只来一次。`doc_id` 和 `chunk_id` 稳定，
重建同一文档时 Embedder 会先删除该文档旧 point，再用确定性 ID 写入，并原子替换 sidecar。

## 配置与运行

关键配置：

```dotenv
PHAROS_DATABASE_URL=postgresql+psycopg://...
PHAROS_REDIS_URL=redis://redis:6379/0
PHAROS_JOB_MAX_ATTEMPTS=3
PHAROS_JOB_HEARTBEAT_SECONDS=15
PHAROS_JOB_STALE_SECONDS=120
PHAROS_JOB_VISIBILITY_TIMEOUT=3600
PHAROS_JOB_SOFT_TIME_LIMIT=2100
PHAROS_JOB_TIME_LIMIT=2400
```

Mac 开发环境已经在 `compose.mac.yml` 中提供 PostgreSQL、Redis、migrate、worker 和 scheduler。
常用观察命令：

```bash
docker compose --env-file .env.mac -f compose.mac.yml ps
docker compose --env-file .env.mac -f compose.mac.yml logs -f pharos worker scheduler
```

任务查询与人工重试：

```bash
curl -sS http://127.0.0.1:8787/v1/jobs/job_xxx -H "X-API-Key: $PHAROS_DEV_API_KEY"
curl -sS -X POST http://127.0.0.1:8787/v1/jobs/job_xxx/retry -H "X-API-Key: $PHAROS_DEV_API_KEY"
```

## 建议的故障演练

1. 正常上传 Markdown，观察 `queued -> running -> ready`。
2. 上传过程中停止 Redis，确认已提交任务最终由 Outbox 补投。
3. 处理过程中停止 Worker，等待超过 stale 时间后重新启动，确认任务被另一 Worker 领取。
4. 临时填写错误的推理 URL，观察 `waiting_retry` 和 `attempts`；恢复 URL 后确认成功。
5. 上传非法 UTF-8 Markdown，确认直接 `failed`，不会浪费自动重试次数。

## 简历与面试表述

可描述为：为 Agentic RAG 知识库实现多租户文档摄取链路，使用 FastAPI 接收 Markdown/PDF，
服务端派生 ACL；使用 PostgreSQL Outbox、Redis/Celery、任务租约和 Worker 心跳实现至少一次投递、
幂等消费、指数退避与失联恢复；解析产物采用尝试级临时目录，成功后原子发布，并提供任务查询与
人工重试 API。

面试时要能解释三个取舍：为什么 Redis 不是状态真相来源，为什么必须有 Outbox，以及为什么
“消息可能重复”时依然要做数据库领取和稳定 `doc_id/chunk_id`。
